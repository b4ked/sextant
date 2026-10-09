"""Storage: a SQLite catalogue of documents and a LanceDB table of chunks.

LanceDB is an embedded, file-based store: it holds the vectors and a native BM25
full-text index side by side, so there is no database server to run or secure.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import warnings
from typing import Any

import numpy as np
import pyarrow as pa

from sextant.config import Settings

CHUNK_TABLE = "chunks"
# Below this many chunks an exact (brute-force) vector scan is both faster to build
# and perfectly accurate; above it we build an approximate index.
ANN_THRESHOLD = 100_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,
    root          TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    suffix        TEXT NOT NULL DEFAULT '',
    size          INTEGER NOT NULL,
    mtime         REAL NOT NULL,
    sha256        TEXT NOT NULL,
    pages         INTEGER NOT NULL DEFAULT 0,
    chunks        INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL,
    error         TEXT NOT NULL DEFAULT '',
    parse_seconds REAL NOT NULL DEFAULT 0,
    indexed_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class IndexMismatch(RuntimeError):
    pass


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.index_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(settings.catalogue_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()
        self._lance = None
        self._table = None

    # ---- catalogue -------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._db.commit()

    def check_embedding(self, model: str, dim: int) -> None:
        """Vectors from different models are not comparable; refuse to mix them."""
        stored = self.get_meta("embedding_model")
        if stored is None:
            self.set_meta("embedding_model", model)
            self.set_meta("embedding_dim", str(dim))
        elif stored != model:
            raise IndexMismatch(
                f"This index was built with embedding model {stored!r} but the current "
                f"setting is {model!r}. Run `sextant reset` and re-index, or restore the setting."
            )

    def document_by_path(self, path: str) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute("SELECT * FROM documents WHERE path = ?", (path,)).fetchone()

    def document(self, doc_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute(
                "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
            ).fetchone()

    def documents(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute("SELECT * FROM documents ORDER BY rel_path").fetchall()

    def documents_by_ids(self, ids: list[str]) -> dict[str, sqlite3.Row]:
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._db.execute(
                f"SELECT * FROM documents WHERE doc_id IN ({marks})", ids
            ).fetchall()
        return {r["doc_id"]: r for r in rows}

    def roots(self) -> list[str]:
        with self._lock:
            rows = self._db.execute("SELECT DISTINCT root FROM documents ORDER BY root").fetchall()
        return [r["root"] for r in rows]

    def upsert_document(self, **doc: Any) -> None:
        doc.setdefault("indexed_at", time.time())
        cols = list(doc)
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "doc_id")
        with self._lock:
            self._db.execute(
                f"INSERT INTO documents({', '.join(cols)}) VALUES({', '.join('?' for _ in cols)}) "
                f"ON CONFLICT(doc_id) DO UPDATE SET {updates}",
                [doc[c] for c in cols],
            )
            self._db.commit()

    def touch_document(self, doc_id: str, mtime: float) -> None:
        with self._lock:
            self._db.execute("UPDATE documents SET mtime = ? WHERE doc_id = ?", (mtime, doc_id))
            self._db.commit()

    def delete_document(self, doc_id: str) -> None:
        self.delete_chunks(doc_id)
        with self._lock:
            self._db.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            self._db.commit()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS docs, "
                "COALESCE(SUM(status = 'indexed'), 0) AS indexed, "
                "COALESCE(SUM(status = 'failed'), 0) AS failed, "
                "COALESCE(SUM(status = 'empty'), 0) AS empty, "
                "COALESCE(SUM(pages), 0) AS pages, COALESCE(SUM(chunks), 0) AS chunks, "
                "COALESCE(SUM(size), 0) AS bytes, MAX(indexed_at) AS last_indexed FROM documents"
            ).fetchone()
        return dict(row)

    # ---- chunks ----------------------------------------------------------

    def _open_table(self, dim: int | None = None, create: bool = False):
        if self._table is not None:
            return self._table
        import lancedb

        if self._lance is None:
            self._lance = lancedb.connect(str(self.settings.lance_dir))
        try:
            self._table = self._lance.open_table(CHUNK_TABLE)
        except Exception:
            if not create or dim is None:
                return None
            schema = pa.schema(
                [
                    pa.field("id", pa.string()),
                    pa.field("doc_id", pa.string()),
                    pa.field("chunk_index", pa.int32()),
                    pa.field("text", pa.string()),
                    pa.field("search_text", pa.string()),
                    pa.field("headings", pa.string()),
                    pa.field("page_start", pa.int32()),
                    pa.field("page_end", pa.int32()),
                    pa.field("vector", pa.list_(pa.float32(), dim)),
                ]
            )
            self._table = self._lance.create_table(CHUNK_TABLE, schema=schema)
        return self._table

    def add_chunks(self, doc_id: str, chunks: list, vectors: np.ndarray) -> None:
        if not chunks:
            return
        table = self._open_table(dim=int(vectors.shape[1]), create=True)
        rows = [
            {
                "id": f"{doc_id}:{c.index}",
                "doc_id": doc_id,
                "chunk_index": c.index,
                "text": c.text,
                "search_text": c.search_text,
                "headings": " › ".join(c.headings),
                "page_start": c.page_start,
                "page_end": c.page_end,
                "vector": vectors[i].tolist(),
            }
            for i, c in enumerate(chunks)
        ]
        with self._lock:
            table.add(rows)

    def delete_chunks(self, doc_id: str) -> None:
        table = self._open_table()
        if table is not None:
            with self._lock:
                table.delete(f"doc_id = {_sql_quote(doc_id)}")

    def chunk_count(self) -> int:
        table = self._open_table()
        return table.count_rows() if table is not None else 0

    def finalize(self) -> None:
        """Rebuild the keyword index (and the ANN index for large corpora), then compact."""
        table = self._open_table()
        if table is None or table.count_rows() == 0:
            return
        with self._lock, warnings.catch_warnings():
            # Native (non-tantivy) BM25 index. The call is stable across the LanceDB
            # versions Sextant supports; newer releases only warn about its spelling.
            warnings.simplefilter("ignore")
            table.create_fts_index(
                "search_text", replace=True, use_tantivy=False,
                stem=True, remove_stop_words=True, ascii_folding=True, lower_case=True,
            )
            if table.count_rows() >= ANN_THRESHOLD:
                table.create_index(
                    metric="cosine", index_type="IVF_HNSW_SQ", vector_column_name="vector",
                    replace=True,
                )
            table.optimize()

    _COLUMNS = ["id", "doc_id", "chunk_index", "text", "search_text", "headings",
                "page_start", "page_end"]

    def vector_search(self, vector: np.ndarray, limit: int) -> list[dict]:
        table = self._open_table()
        if table is None:
            return []
        return (
            table.search(vector.tolist(), vector_column_name="vector")
            .distance_type("cosine").select([*self._COLUMNS, "_distance"]).limit(limit).to_list()
        )

    def keyword_search(self, query: str, limit: int) -> list[dict]:
        table = self._open_table()
        if table is None:
            return []
        try:
            return (
                table.search(query, query_type="fts", fts_columns="search_text")
                .select([*self._COLUMNS, "_score"]).limit(limit).to_list()
            )
        except Exception:
            # No keyword index yet, or the query reduced to nothing but stop words.
            return []

    def reset(self) -> None:
        import shutil

        with self._lock:
            self._db.close()
            self._table = None
            self._lance = None
            shutil.rmtree(self.settings.index_dir, ignore_errors=True)
            self.settings.index_dir.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(self.settings.catalogue_path, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            self._db.executescript(SCHEMA)
            self._db.commit()
