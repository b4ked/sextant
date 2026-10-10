"""Open an index store and the models that match it."""

from __future__ import annotations

from dataclasses import dataclass, field

from silo import models
from silo.config import Settings
from silo.embed import Embedder
from silo.search import Searcher
from silo.store import Store


@dataclass
class Engine:
    settings: Settings
    store: Store
    embedder: Embedder
    searcher: Searcher
    notices: list[str] = field(default_factory=list)


def open_engine(settings: Settings, read_only: bool | None = None) -> Engine:
    """Open the configured store, adopt its recorded settings, and check the models.

    An index is only meaningful with the embedding model that built it, so the store,
    not the local configuration, decides which model answers queries. That is what
    lets someone pick up an index built elsewhere and search it straight away.
    """
    store = Store(settings, read_only=read_only)
    notices: list[str] = []
    manifest = store.manifest()
    stored_model = manifest.get("embedding_model")
    if stored_model and stored_model != settings.embedding_model:
        notices.append(
            f"Using embedding model {stored_model} recorded in this index store "
            f"(configured: {settings.embedding_model})."
        )
        settings.embedding_model = stored_model
    stored_tokens = manifest.get("chunk_tokens")
    if stored_tokens and int(stored_tokens) != settings.chunk_tokens:
        settings.chunk_tokens = int(stored_tokens)
    models.require(settings)
    embedder = Embedder(settings)
    return Engine(settings, store, embedder, Searcher(settings, store, embedder), notices)
