"""Use case: hybrid retrieval (dense + keyword, fused with RRF)."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid

from aios.modules.knowledge.domain.fusion import rrf_fuse
from aios.modules.knowledge.domain.models import RetrievedChunk
from aios.modules.knowledge.ports.embedder import Embedder
from aios.modules.knowledge.ports.repository import KnowledgeRepository, SearchFilter
from aios.shared.errors import ExternalServiceError, InvalidInputError
from aios.shared.text import normalize_for_search

logger = logging.getLogger(__name__)

DENSE = "dense"
KEYWORD = "keyword"


class HybridRetriever:
    """Dense search finds paraphrases; keyword search finds exact unit codes and names.

    If the embedding service is down, retrieval degrades to keyword-only instead of
    failing the whole answer.
    """

    def __init__(
        self,
        repository: KnowledgeRepository,
        embedder: Embedder,
        *,
        candidates_per_retriever: int = 40,
    ) -> None:
        self._repo = repository
        self._embedder = embedder
        self._candidates = candidates_per_retriever

    async def search(
        self, query: str, flt: SearchFilter | None = None, *, k: int = 8
    ) -> list[RetrievedChunk]:
        query = query.strip()
        if not query:
            raise InvalidInputError("query must not be empty")
        flt = flt or SearchFilter()

        dense, keyword = await asyncio.gather(
            self._dense(query, flt),
            self._repo.keyword_search(normalize_for_search(query), flt, self._candidates),
        )
        rankings: dict[str, list[uuid.UUID]] = {KEYWORD: keyword}
        if dense is not None:
            rankings[DENSE] = dense

        fused = rrf_fuse(rankings, limit=k)
        payloads = await self._repo.fetch_chunks([cid for cid, _, _ in fused])
        return [
            dataclasses.replace(payloads[cid], score=score, ranks=ranks)
            for cid, score, ranks in fused
            if cid in payloads
        ]

    async def _dense(self, query: str, flt: SearchFilter) -> list[uuid.UUID] | None:
        try:
            vector = await self._embedder.embed_query(query)
        except ExternalServiceError:
            logger.warning("embedding unavailable, falling back to keyword-only retrieval")
            return None
        return await self._repo.vector_search(vector, flt, self._candidates)
