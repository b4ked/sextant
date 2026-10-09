# Connecting an LLM

Search works without one. An LLM adds a written answer with numbered citations on top of the
same retrieval.

SILO speaks the OpenAI `/chat/completions` protocol with streaming. Set two values, by
environment variable or in `$SILO_HOME/config.toml`:

| Endpoint | `SILO_LLM_BASE_URL` | `SILO_LLM_MODEL` |
|---|---|---|
| Ollama (same machine) | `http://localhost:11434/v1` | e.g. `gemma4:e2b` |
| llama.cpp `llama-server` | `http://localhost:8080/v1` | the loaded model's name |
| LM Studio | `http://localhost:1234/v1` | as shown in LM Studio |
| vLLM on an internal server | `http://10.0.0.12:8000/v1` | the served model id |
| Hosted provider | the provider's OpenAI-compatible URL | provider model id, plus `SILO_LLM_API_KEY` |

```bash
export SILO_LLM_BASE_URL=http://localhost:11434/v1
export SILO_LLM_MODEL=gemma4:e2b
silo doctor      # → LLM: gemma4:e2b at http://localhost:11434/v1 (loopback address)
silo ask "What are the tenets of zero trust?"
silo serve       # the interface now shows "Answer with LLM"
```

## What is sent

Only the question and the retrieved passages (8 by default, `llm_context_chunks`), each with
its file name, page and heading. Never whole documents, never the index.

SILO classifies the endpoint as `loopback`, `private` or `external` and shows it in
`doctor`, in `ask`, and as a status chip in the interface. An external endpoint means those
passages leave your network; that is a data-handling decision, not a technical one.

## Choosing a local model

The retrieval stack is CPU-only. A language model is a separate, heavier component:

- Small models (2–4 B parameters, 4-bit) run on CPU with 8–16 GB of memory at reading speed.
  They summarise and quote retrieved passages acceptably, and are weaker at multi-step
  reasoning.
- Larger models answer better and want more memory, or a GPU.
- Runtimes may use hardware you did not ask for: Ollama on Apple Silicon uses the built-in
  GPU by default.

In testing, a 2B-class model went from "the passages do not list them" to a correct, cited
list once passages were supplied in reading order. Retrieval quality and passage ordering
matter more than model size for this task. Verify generated answers against the cited page.
