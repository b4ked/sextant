"""Hybrid retrieval: BM25 + dense vectors, fused by reciprocal rank, then reranked."""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from silo.config import Settings
from silo.embed import Embedder, Reranker
from silo.store import Store

MODES = ("hybrid", "semantic", "keyword")


@dataclass
class Hit:
    rank: int
    chunk_id: str
    doc_id: str
    title: str
    rel_path: str
    suffix: str
    text: str
    headings: str
    page_start: int
    page_end: int
    score: float  # the score the final ordering used
    vector_rank: int | None = None
    keyword_rank: int | None = None
    vector_similarity: float | None = None
    bm25: float | None = None
    rrf: float | None = None
    rerank: float | None = None
    file_available: bool = True  # False when the index is used away from its source files


@dataclass
class SearchResult:
    query: str
    mode: str
    reranked: bool
    hits: list[Hit]
    timings_ms: dict[str, float]

    def to_dict(self) -> dict:
        return {
            "query": self.query, "mode": self.mode, "reranked": self.reranked,
            "timings_ms": self.timings_ms, "hits": [asdict(h) for h in self.hits],
        }


def reading_order(result: SearchResult) -> SearchResult:
    """Regroup hits by document (best document first) and sort each group by position.

    Retrieval ranks passages individually, which can hand a language model a list
    whose items arrive out of order. Restoring document order makes split lists and
    multi-paragraph arguments read the way they were written.
    """
    first_seen: dict[str, int] = {}
    for hit in result.hits:
        first_seen.setdefault(hit.doc_id, hit.rank)
    ordered = sorted(
        result.hits,
        key=lambda h: (first_seen[h.doc_id], int(h.chunk_id.rsplit(":", 1)[1])),
    )
    for rank, hit in enumerate(ordered, start=1):
        hit.rank = rank
    result.hits = ordered
    return result


class Searcher:
    def __init__(self, settings: Settings, store: Store, embedder: Embedder,
                 reranker: Reranker | None = None):
        self.settings = settings
        self.store = store
        self.embedder = embedder
        self.reranker = reranker or Reranker(settings)

    def warm(self) -> None:
        """Load both models so the first real query is not the slow one."""
        vector = self.embedder.embed_query("warm up")
        self.store.vector_search(vector, 1)
        self.store.keyword_search("warm up", 1)
        if self.settings.rerank:
            self.reranker.score("warm up", ["warm up"])

    def search(self, query: str, k: int = 10, mode: str = "hybrid",
               rerank: bool | None = None) -> SearchResult:
        query = " ".join(query.split())
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        rerank = self.settings.rerank if rerank is None else rerank
        timings: dict[str, float] = {}
        if not query:
            return SearchResult(query, mode, False, [], timings)
        s = self.settings
        pool = max(s.candidates, k)
        candidates: dict[str, dict] = {}

        if mode in ("hybrid", "semantic"):
            t = time.perf_counter()
            vector = self.embedder.embed_query(query)
            timings["embed"] = (time.perf_counter() - t) * 1000
            t = time.perf_counter()
            for rank, row in enumerate(self.store.vector_search(vector, pool), start=1):
                entry = candidates.setdefault(row["id"], {"row": row})
                entry["vector_rank"] = rank
                entry["vector_similarity"] = 1.0 - float(row.get("_distance", 1.0))
            timings["vector"] = (time.perf_counter() - t) * 1000

        if mode in ("hybrid", "keyword"):
            t = time.perf_counter()
            for rank, row in enumerate(self.store.keyword_search(query, pool), start=1):
                entry = candidates.setdefault(row["id"], {"row": row})
                entry["keyword_rank"] = rank
                entry["bm25"] = float(row.get("_score", 0.0))
            timings["keyword"] = (time.perf_counter() - t) * 1000

        # Reciprocal rank fusion: rank-based, so BM25 scores and cosine similarities
        # never have to be put on a common scale.
        for entry in candidates.values():
            entry["rrf"] = sum(
                1.0 / (s.rrf_k + entry[key])
                for key in ("vector_rank", "keyword_rank") if entry.get(key)
            )
        ordered = sorted(candidates.values(), key=lambda e: e["rrf"], reverse=True)

        reranked = False
        if rerank and ordered:
            t = time.perf_counter()
            head = ordered[: max(s.rerank_top, k)]
            scores = self.reranker.score(query, [e["row"]["search_text"] for e in head])
            for entry, logit in zip(head, scores, strict=True):
                entry["rerank"] = 1.0 / (1.0 + math.exp(-logit))
            ordered = sorted(head, key=lambda e: e["rerank"], reverse=True)
            timings["rerank"] = (time.perf_counter() - t) * 1000
            reranked = True

        ordered = ordered[:k]
        docs = self.store.documents_by_ids(list({e["row"]["doc_id"] for e in ordered}))
        hits: list[Hit] = []
        for rank, entry in enumerate(ordered, start=1):
            row = entry["row"]
            doc = docs.get(row["doc_id"])
            hits.append(
                Hit(
                    rank=rank, chunk_id=row["id"], doc_id=row["doc_id"],
                    title=doc["title"] if doc else "", rel_path=doc["rel_path"] if doc else "",
                    suffix=doc["suffix"] if doc else "", text=row["text"],
                    headings=row["headings"], page_start=row["page_start"],
                    page_end=row["page_end"],
                    score=entry["rerank"] if reranked else entry["rrf"],
                    vector_rank=entry.get("vector_rank"), keyword_rank=entry.get("keyword_rank"),
                    vector_similarity=entry.get("vector_similarity"), bm25=entry.get("bm25"),
                    rrf=entry["rrf"], rerank=entry.get("rerank"),
                    file_available=bool(doc) and Path(doc["path"]).is_file(),
                )
            )
        timings = {name: round(ms, 1) for name, ms in timings.items()}
        timings["total"] = round(sum(timings.values()), 1)
        return SearchResult(query, mode, reranked, hits, timings)
