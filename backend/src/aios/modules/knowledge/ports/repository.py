"""Port: persistence and search over documents and chunks."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from aios.modules.knowledge.domain.models import (
    Chunk,
    DocType,
    DocumentMeta,
    RetrievedChunk,
)
from aios.modules.knowledge.ports.embedder import Vector


@dataclass(frozen=True, slots=True)
class SearchFilter:
    """Only ACTIVE documents are ever searched; these narrow further."""

    compound_codes: tuple[str, ...] = ()
    doc_types: tuple[DocType, ...] = ()


@dataclass(frozen=True, slots=True)
class StoredDocument:
    source_id: str
    version: str
    content_hash: str
    embedding_model: str
    status: str


class KnowledgeRepository(Protocol):
    async def get_document(self, source_id: str, version: str) -> StoredDocument | None: ...

    async def save_document(
        self,
        meta: DocumentMeta,
        content_hash: str,
        embedding_model: str,
        chunks: Sequence[Chunk],
        search_texts: Sequence[str],
        vectors: Sequence[Vector],
    ) -> None:
        """Insert or replace one document version and all its chunks atomically."""
        ...

    async def retire_superseded(self, meta: DocumentMeta) -> list[str]:
        """Retire active docs in ``meta.series`` with an older effective date.

        Returns the retired ``source_id@version`` keys.
        """
        ...

    async def active_embedding_models(self) -> set[str]:
        """Embedding model ids used by active documents (must be exactly one to search)."""
        ...

    async def vector_search(
        self, query_vector: Vector, flt: SearchFilter, limit: int
    ) -> list[uuid.UUID]: ...

    async def keyword_search(
        self, normalized_query: str, flt: SearchFilter, limit: int
    ) -> list[uuid.UUID]: ...

    async def fetch_chunks(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, RetrievedChunk]:
        """Load chunk payloads; the returned ``score`` field is 0 (callers set it)."""
        ...
