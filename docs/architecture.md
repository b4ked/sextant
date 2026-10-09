# Architecture

SILO is one Python package and one directory of data. This note explains each stage and
the decisions behind it.

## Data layout

```
$SILO_HOME (default ~/.silo)
├── config.toml              optional settings
├── models/                  written only by `silo models pull`; stays with the machine
│   ├── docling/             layout, TableFormer, RapidOCR weights
│   └── fastembed/           embedding + reranker ONNX files
└── index/                   the default index store; any other directory can be used instead
    ├── catalogue.sqlite     one row per document: path, hash, pages, status, errors
    └── lance/               passages, vectors and the BM25 index (LanceDB)
```

Your documents are never copied or modified. The index stores extracted text, so treat
`index/` with the same care as the documents themselves.

## Indexing

1. **Discover.** Walk the folder, skipping hidden files, editor lock files and VCS/dependency
   directories.
2. **Decide.** A file is skipped when its size and modification time match the catalogue. If
   only the timestamp changed, the SHA-256 is compared before re-parsing. Files that vanished
   from an indexed folder are removed from the index.
3. **Parse.** Docling converts the file to a structured document. For PDFs this runs a layout
   model (headings, paragraphs, lists, tables, reading order) and TableFormer for table
   structure. SILO pins the accelerator to `cpu`, so behaviour is identical on a laptop
   and a server and no GPU is picked up implicitly. OCR (RapidOCR) is opt-in because most
   business PDFs already contain text and OCR is the slowest stage.
4. **Chunk.** Docling's `HybridChunker` splits along document structure, merges undersized
   neighbours, and caps each passage at 384 tokens as counted by the embedding model's own
   tokenizer. Each passage keeps its heading path and page range.
5. **Embed.** The passage, prefixed with its heading path, is embedded with
   `bge-small-en-v1.5` through ONNX Runtime. The same contextualised text feeds the keyword
   index, so a query can match a section title as well as body text.
6. **Store.** Passages go into LanceDB; the catalogue row is updated. After the run the BM25
   index is rebuilt and the table compacted.

One failed file never stops a run. It is recorded with its error and shown by `silo status`
and the Library view.

## Search

- **Keyword** — LanceDB's native BM25 index with stemming and stop-word removal.
- **Semantic** — cosine similarity over the 384-dimension vectors. Below 100,000 passages the
  scan is exact (brute force), which is both accurate and fast at that size. Above it an
  IVF-HNSW index is built automatically.
- **Fusion** — reciprocal rank fusion: `score = Σ 1 / (60 + rank)`. It needs no score
  normalisation, which is why it is the standard way to combine BM25 with vectors.
- **Rerank** — the top 20 fused candidates are scored by a cross-encoder that reads the query
  and passage together. This is the slowest query stage (roughly 30 ms per passage on a laptop
  CPU) and can be switched off per query.

The interface shows each result's vector rank, BM25 rank, fusion score and rerank score, so you
can see why a passage surfaced.

## Answer generation

`ask` retrieves the top passages, regroups them into reading order per document, numbers them,
and sends them with the question to the configured chat endpoint. The prompt requires a
citation after each statement and an explicit "not covered" when the passages are irrelevant.
Reading order matters: retrieval ranks passages individually, and a numbered list split across
three passages is much easier for a small model to use when it arrives in sequence.

## Choosing other models

| Setting | Default | Alternatives |
|---|---|---|
| `embedding_model` | `BAAI/bge-small-en-v1.5` | `ibm-granite/granite-embedding-small-english-r2` (Apache-2.0, long context), `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (multilingual), `BAAI/bge-base-en-v1.5` (larger) |
| `reranker_model` | `Xenova/ms-marco-MiniLM-L-6-v2` | `jinaai/jina-reranker-v1-tiny-en`, `BAAI/bge-reranker-v2-m3-int8` (multilingual, heavier) |

Any model supported by fastembed works. Changing the embedding model requires
`silo reset` and a re-index; SILO refuses to mix vectors from different models. The
defaults are English-focused: for other languages change both models.

## Modules

| Module | Role |
|---|---|
| `_offline.py` | Forces model libraries offline before they load |
| `config.py` | Settings from defaults, `config.toml`, environment |
| `models.py` | The one download step; presence checks |
| `parse.py` | Docling conversion and chunking, CPU-pinned |
| `embed.py` | ONNX embedding and reranking |
| `store.py` | An index store: SQLite catalogue + LanceDB table; read-only mode; relocation |
| `engine.py` | Opens a store and adopts the models it was built with |
| `indexer.py` | Incremental indexing |
| `search.py` | Hybrid retrieval, fusion, reranking |
| `llm.py` | Optional OpenAI-compatible answer generation |
| `server.py` + `web/` | JSON API and the self-contained interface |
| `mcp_server.py` | MCP tools over stdio |
| `cli.py` | The `silo` command |

## Known limits

- Single process, single writer. Concurrent indexing runs are not coordinated.
- No authentication or access control (see `deployment.md`).
- Page links rely on the browser's built-in PDF viewer honouring `#page=N`.
- Figures and images are not described or searched; formulas are kept as extracted text.
- Tested at hundreds of pages. Large-corpus behaviour (hundreds of thousands of pages) is
  designed for but not yet measured.
