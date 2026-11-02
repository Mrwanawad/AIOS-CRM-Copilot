"""Use case: hybrid retrieval (dense + keyword, fused with RRF), then optional reranking."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid

from aios.modules.knowledge.domain.fusion import rrf_fuse
from aios.modules.knowledge.domain.models import RetrievedChunk
from aios.modules.knowledge.ports.embedder import Embedder
from aios.modules.knowledge.ports.repository import KnowledgeRepository, SearchFilter
from aios.modules.knowledge.ports.reranker import Reranker
from aios.shared.errors import ExternalServiceError, InvalidInputError
from aios.shared.text import normalize_for_search

logger = logging.getLogger(__name__)

DENSE = "dense"
KEYWORD = "keyword"
RERANK = "rerank"


def rerank_text(chunk: RetrievedChunk) -> str:
    """What the cross-encoder sees: title and heading trail give it the context."""
    return f"{chunk.title} > {' > '.join(chunk.heading_path)}\n{chunk.text}"


class HybridRetriever:
    """Dense search finds paraphrases; keyword search finds exact unit codes and names.

    If the embedding service is down, retrieval degrades to keyword-only instead of
    failing the whole answer. With a reranker, the top ``rerank_candidates`` fused
    chunks are re-scored; if the reranker is down, the fused order is kept.
    """

    def __init__(
        self,
        repository: KnowledgeRepository,
        embedder: Embedder,
        *,
        candidates_per_retriever: int = 40,
        reranker: Reranker | None = None,
        rerank_candidates: int = 30,
    ) -> None:
        if rerank_candidates <= 0:
            raise ValueError("rerank_candidates must be positive")
        self._repo = repository
        self._embedder = embedder
        self._candidates = candidates_per_retriever
        self._reranker = reranker
        self._rerank_candidates = rerank_candidates

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

        pool = max(k, self._rerank_candidates) if self._reranker else k
        fused = rrf_fuse(rankings, limit=pool)
        payloads = await self._repo.fetch_chunks([cid for cid, _, _ in fused])
        chunks = [
            dataclasses.replace(payloads[cid], score=score, ranks=ranks)
            for cid, score, ranks in fused
            if cid in payloads
        ]
        if self._reranker is None or not chunks:
            return chunks[:k]
        return await self._rerank(self._reranker, query, chunks, k)

    async def _rerank(
        self, reranker: Reranker, query: str, chunks: list[RetrievedChunk], k: int
    ) -> list[RetrievedChunk]:
        try:
            results = await reranker.rerank(query, [rerank_text(c) for c in chunks], top_n=k)
        except ExternalServiceError:
            logger.warning("reranker unavailable, keeping fused order")
            return chunks[:k]
        return [
            dataclasses.replace(
                chunks[r.index],
                score=r.relevance,
                ranks={**chunks[r.index].ranks, RERANK: pos},
            )
            for pos, r in enumerate(results[:k], 1)
        ]

    async def _dense(self, query: str, flt: SearchFilter) -> list[uuid.UUID] | None:
        try:
            vector = await self._embedder.embed_query(query)
        except ExternalServiceError:
            logger.warning("embedding unavailable, falling back to keyword-only retrieval")
            return None
        return await self._repo.vector_search(vector, flt, self._candidates)
