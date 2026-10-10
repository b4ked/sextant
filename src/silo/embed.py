"""CPU embedding and reranking through ONNX Runtime (fastembed). No PyTorch, no GPU."""

from __future__ import annotations

from functools import cached_property

import numpy as np

from silo.config import Settings


class Embedder:
    def __init__(self, settings: Settings):
        self.settings = settings

    @cached_property
    def _model(self):
        from fastembed import TextEmbedding

        return TextEmbedding(
            self.settings.embedding_model,
            cache_dir=str(self.settings.fastembed_dir),
            threads=self.settings.num_threads,
            providers=["CPUExecutionProvider"],
            local_files_only=True,
        )

    @cached_property
    def dim(self) -> int:
        return int(len(self.embed_query("dimension probe")))

    @cached_property
    def tokenizer(self):
        """A copy of the embedding model's tokenizer with truncation off, for chunk sizing."""
        from tokenizers import Tokenizer

        tok = Tokenizer.from_str(self._model.model.tokenizer.to_str())
        tok.no_truncation()
        tok.no_padding()
        return tok

    def embed_passages(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = list(self._model.passage_embed(texts, batch_size=batch_size))
        return np.asarray(vectors, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return np.asarray(next(iter(self._model.query_embed(text))), dtype=np.float32)


class Reranker:
    def __init__(self, settings: Settings):
        self.settings = settings

    @cached_property
    def _model(self):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        return TextCrossEncoder(
            self.settings.reranker_model,
            cache_dir=str(self.settings.fastembed_dir),
            threads=self.settings.num_threads,
            providers=["CPUExecutionProvider"],
            local_files_only=True,
        )

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return [float(s) for s in self._model.rerank(query, passages, batch_size=16)]
