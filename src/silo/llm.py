"""Optional answer generation over retrieved passages.

Disabled unless ``llm_base_url`` and ``llm_model`` are set. Speaks the OpenAI
``/chat/completions`` protocol, which Ollama, llama.cpp, LM Studio, vLLM and the
hosted providers all expose, so "local or online" is a configuration choice.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from collections.abc import Iterator
from urllib.parse import urlparse

import httpx

from silo.config import Settings
from silo.search import Hit

SYSTEM_PROMPT = (
    "You answer questions about a document collection. You are given numbered source "
    "passages retrieved from it. They are excerpts: they may begin mid-list or be "
    "incomplete, so use everything relevant they do contain.\n"
    "Rules:\n"
    "- Use only the passages. Do not add outside knowledge.\n"
    "- After each statement, cite the passage it came from in square brackets, like [2].\n"
    "- If the passages only partly answer the question, give the partial answer and say "
    "what is missing.\n"
    "- If nothing in the passages is relevant, say that the indexed documents do not "
    "cover it.\n"
    "- Be concise."
)


class LLMError(RuntimeError):
    pass


def egress(settings: Settings) -> str:
    """Where prompts would travel: 'none', 'loopback', 'private' or 'external'."""
    if not settings.llm_enabled:
        return "none"
    host = urlparse(settings.llm_base_url).hostname or ""
    if host in ("localhost", ""):
        return "loopback"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(host))
        except OSError:
            return "external"
    if ip.is_loopback:
        return "loopback"
    return "private" if ip.is_private else "external"


def build_messages(question: str, hits: list[Hit]) -> list[dict]:
    blocks = []
    for n, hit in enumerate(hits, start=1):
        where = hit.rel_path + (f", page {hit.page_start}" if hit.page_start else "")
        heading = f" — {hit.headings}" if hit.headings else ""
        blocks.append(f"[{n}] {where}{heading}\n{hit.text}")
    user = "Source passages:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def stream_answer(settings: Settings, question: str, hits: list[Hit]) -> Iterator[str]:
    if not settings.llm_enabled:
        raise LLMError("No LLM configured. Set SILO_LLM_BASE_URL and SILO_LLM_MODEL.")
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    payload = {
        "model": settings.llm_model,
        "messages": build_messages(question, hits),
        "temperature": 0,
        "stream": True,
    }
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    try:
        with httpx.stream("POST", url, headers=headers, json=payload,
                          timeout=httpx.Timeout(settings.llm_timeout, connect=10.0)) as response:
            if response.status_code >= 400:
                detail = response.read().decode("utf-8", "replace")[:300]
                raise LLMError(f"LLM endpoint returned {response.status_code}: {detail}")
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    choices = json.loads(data).get("choices") or []
                except json.JSONDecodeError:
                    continue
                if choices:
                    token = (choices[0].get("delta") or {}).get("content")
                    if token:
                        yield token
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach the LLM endpoint at {url}: {exc}") from exc
