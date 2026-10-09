# Configuration

Precedence: built-in defaults → `$SEXTANT_HOME/config.toml` → `SEXTANT_*` environment
variables → command-line flags.

| Key (`config.toml`) | Env var | Default | Meaning |
|---|---|---|---|
| — | `SEXTANT_HOME` | `~/.sextant` | Models and index directory |
| `embedding_model` | `SEXTANT_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Any fastembed text model |
| `reranker_model` | `SEXTANT_RERANKER_MODEL` | `Xenova/ms-marco-MiniLM-L-6-v2` | Any fastembed cross-encoder |
| `rerank` | `SEXTANT_RERANK` | `true` | Rerank by default |
| `ocr` | `SEXTANT_OCR` | `false` | OCR scanned pages and images |
| `tables` | `SEXTANT_TABLES` | `true` | Recover table structure |
| `table_mode` | `SEXTANT_TABLE_MODE` | `fast` | `fast` or `accurate` |
| `threads` | `SEXTANT_THREADS` | `0` (all cores) | CPU threads for inference |
| `document_timeout` | `SEXTANT_DOCUMENT_TIMEOUT` | `600` | Seconds allowed per document |
| `chunk_tokens` | `SEXTANT_CHUNK_TOKENS` | `384` | Maximum passage length |
| `candidates` | `SEXTANT_CANDIDATES` | `50` | Candidates per retriever before fusion |
| `rerank_top` | `SEXTANT_RERANK_TOP` | `20` | Fused candidates sent to the reranker |
| `rrf_k` | `SEXTANT_RRF_K` | `60` | Reciprocal rank fusion constant |
| `llm_base_url` | `SEXTANT_LLM_BASE_URL` | empty (off) | OpenAI-compatible base URL |
| `llm_model` | `SEXTANT_LLM_MODEL` | empty (off) | Model name |
| `llm_api_key` | `SEXTANT_LLM_API_KEY` | empty | Bearer token if required |
| `llm_context_chunks` | `SEXTANT_LLM_CONTEXT_CHUNKS` | `8` | Passages sent to the LLM |
| `host` / `port` | `SEXTANT_HOST` / `SEXTANT_PORT` | `127.0.0.1` / `8321` | Server bind |

Example `~/.sextant/config.toml`:

```toml
ocr = true
threads = 6
llm_base_url = "http://localhost:11434/v1"
llm_model = "gemma4:e2b"
```

Changing `embedding_model` or `chunk_tokens` on an existing index requires `sextant reset`
followed by a full re-index.

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Index statistics, models, LLM egress, indexing job state |
| GET | `/api/search?q=&mode=&k=&rerank=` | Search; returns hits with ranks, scores and timings |
| GET | `/api/documents` | Catalogue listing |
| GET | `/api/documents/{id}/file` | The original file (only catalogued files are served) |
| POST | `/api/ask` `{question, mode}` | Server-sent events: `sources`, `token`…, `done` |
| POST | `/api/index` | Re-scan every indexed folder in the background |
| GET | `/api/openapi.json` | Machine-readable schema |
