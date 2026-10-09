"""Settings: defaults, then ``$SEXTANT_HOME/config.toml``, then ``SEXTANT_*`` env vars."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


def _default_home() -> Path:
    return Path(os.environ.get("SEXTANT_HOME", Path.home() / ".sextant")).expanduser().resolve()


@dataclass
class Settings:
    home: Path

    # Retrieval models. Both run on CPU through ONNX Runtime.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank: bool = True

    # Parsing.
    ocr: bool = False  # scanned PDFs / images; slower, off by default
    tables: bool = True  # TableFormer table structure recovery
    table_mode: str = "fast"  # "fast" | "accurate"
    threads: int = 0  # 0 = all logical cores
    document_timeout: float = 600.0  # seconds per document

    # Chunking.
    chunk_tokens: int = 384

    # Search.
    candidates: int = 50  # per retriever, before fusion
    rerank_top: int = 20  # fused candidates sent to the cross-encoder
    rrf_k: int = 60

    # Optional LLM (any OpenAI-compatible /chat/completions endpoint). Off unless set.
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_context_chunks: int = 8
    llm_timeout: float = 300.0

    # Server.
    host: str = "127.0.0.1"
    port: int = 8321

    @property
    def models_dir(self) -> Path:
        return self.home / "models"

    @property
    def docling_dir(self) -> Path:
        return self.models_dir / "docling"

    @property
    def fastembed_dir(self) -> Path:
        return self.models_dir / "fastembed"

    @property
    def index_dir(self) -> Path:
        return self.home / "index"

    @property
    def catalogue_path(self) -> Path:
        return self.index_dir / "catalogue.sqlite"

    @property
    def lance_dir(self) -> Path:
        return self.index_dir / "lance"

    @property
    def num_threads(self) -> int:
        return self.threads if self.threads > 0 else (os.cpu_count() or 4)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)


def _coerce(value: object, target: type) -> object:
    if target is bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if target is int:
        return int(value)  # type: ignore[arg-type]
    if target is float:
        return float(value)  # type: ignore[arg-type]
    return str(value)


def load_settings(home: Path | None = None) -> Settings:
    home = (home or _default_home()).expanduser().resolve()
    settings = Settings(home=home)
    file_values: dict[str, object] = {}
    config_file = home / "config.toml"
    if config_file.exists():
        file_values = tomllib.loads(config_file.read_text())
    for f in fields(Settings):
        if f.name == "home":
            continue
        target = type(getattr(settings, f.name))
        if f.name in file_values:
            setattr(settings, f.name, _coerce(file_values[f.name], target))
        env = os.environ.get(f"SEXTANT_{f.name.upper()}")
        if env is not None and env != "":
            setattr(settings, f.name, _coerce(env, target))
    return settings
