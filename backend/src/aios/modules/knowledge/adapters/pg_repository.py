"""Adapter: PostgreSQL + pgvector implementation of ``KnowledgeRepository``.

Plain SQL on purpose: the queries (ANN ordering, tsquery building, generated tsvector)
are clearer in SQL than in an ORM. Only fixed SQL fragments are concatenated; every
value is a bound parameter.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from aios.modules.knowledge.domain.models import (
    Chunk,
    DocStatus,
    DocType,
    DocumentMeta,
    RetrievedChunk,
)
from aios.modules.knowledge.ports.embedder import Vector
from aios.modules.knowledge.ports.repository import SearchFilter, StoredDocument

HNSW_EF_SEARCH = 100


def _vec(v: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def _filter_sql(flt: SearchFilter, params: dict[str, Any]) -> str:
    clauses = ["d.status = 'active'"]
    if flt.compound_codes:
        # Company-wide docs (policies, playbook) have no compound and always apply.
        clauses.append("(d.compound_code IS NULL OR d.compound_code = ANY(:codes))")
        params["codes"] = list(flt.compound_codes)
    if flt.doc_types:
        clauses.append("d.doc_type = ANY(:types)")
        params["types"] = [t.value for t in flt.doc_types]
    return " AND ".join(clauses)


# OR of all query lexemes (English + Arabic configs). websearch_to_tsquery would AND
# every word, so a natural-language question would almost never match anything.
_KEYWORD_SQL = """
WITH q AS (
    SELECT NULLIF(array_to_string(ARRAY(
        SELECT DISTINCT quote_literal(lex)
        FROM unnest(tsvector_to_array(
            to_tsvector('english'::regconfig, :q) || to_tsvector('arabic'::regconfig, :q)
        )) AS lex
    ), ' | '), '')::tsquery AS tsq
)
SELECT c.id
FROM kb_chunks c
JOIN kb_documents d ON d.id = c.document_id, q
WHERE c.tsv @@ q.tsq AND {filters}
ORDER BY ts_rank_cd(c.tsv, q.tsq) DESC, c.id
LIMIT :limit
"""

_VECTOR_SQL = """
SELECT c.id
FROM kb_chunks c
JOIN kb_documents d ON d.id = c.document_id
WHERE {filters}
ORDER BY c.embedding <=> CAST(:qv AS vector)
LIMIT :limit
"""


class PgKnowledgeRepository:
    def __init__(self, engine: AsyncEngine, *, dimension: int) -> None:
        self._engine = engine
        self._dimension = dimension

    async def get_document(self, source_id: str, version: str) -> StoredDocument | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT source_id, version, content_hash, embedding_model, status "
                        "FROM kb_documents WHERE source_id = :s AND version = :v"
                    ),
                    {"s": source_id, "v": version},
                )
            ).first()
        return StoredDocument(*row) if row else None

    async def save_document(
        self,
        meta: DocumentMeta,
        content_hash: str,
        embedding_model: str,
        chunks: Sequence[Chunk],
        search_texts: Sequence[str],
        vectors: Sequence[Vector],
    ) -> None:
        if not len(chunks) == len(search_texts) == len(vectors):
            raise ValueError("chunks, search_texts and vectors must align")
        if any(len(v) != self._dimension for v in vectors):
            raise ValueError(f"all vectors must have dimension {self._dimension}")

        async with self._engine.begin() as conn:
            status = await self._effective_status(conn, meta)
            await conn.execute(
                text("DELETE FROM kb_documents WHERE source_id = :s AND version = :v"),
                {"s": meta.source_id, "v": meta.version},
            )
            doc_id = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO kb_documents (source_id, version, series, title, doc_type,
                            compound_code, effective_date, status, content_hash, embedding_model)
                        VALUES (:source_id, :version, :series, :title, :doc_type,
                            :compound_code, :effective_date, :status, :hash, :model)
                        RETURNING id
                        """
                    ),
                    {
                        "source_id": meta.source_id,
                        "version": meta.version,
                        "series": meta.series,
                        "title": meta.title,
                        "doc_type": meta.doc_type.value,
                        "compound_code": meta.compound_code,
                        "effective_date": meta.effective_date,
                        "status": status.value,
                        "hash": content_hash,
                        "model": embedding_model,
                    },
                )
            ).scalar_one()
            if chunks:
                await conn.execute(
                    text(
                        """
                        INSERT INTO kb_chunks (id, document_id, ordinal, heading_path, text,
                            search_text, embedding)
                        VALUES (:id, :doc_id, :ordinal, :heading_path, :text, :search_text,
                            CAST(:embedding AS vector))
                        """
                    ),
                    [
                        {
                            "id": ch.chunk_id,
                            "doc_id": doc_id,
                            "ordinal": ch.ordinal,
                            "heading_path": list(ch.heading_path),
                            "text": ch.text,
                            "search_text": st,
                            "embedding": _vec(v),
                        }
                        for ch, st, v in zip(chunks, search_texts, vectors, strict=True)
                    ],
                )

    async def _effective_status(self, conn: AsyncConnection, meta: DocumentMeta) -> DocStatus:
        """An older version ingested after a newer one must not become active."""
        if meta.status is DocStatus.RETIRED:
            return DocStatus.RETIRED
        newer = (
            await conn.execute(
                text(
                    "SELECT 1 FROM kb_documents WHERE series = :series AND status = 'active' "
                    "AND effective_date > :d LIMIT 1"
                ),
                {"series": meta.series, "d": meta.effective_date},
            )
        ).first()
        return DocStatus.RETIRED if newer else DocStatus.ACTIVE

    async def retire_superseded(self, meta: DocumentMeta) -> list[str]:
        async with self._engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        UPDATE kb_documents SET status = 'retired'
                        WHERE series = :series AND status = 'active' AND effective_date < :d
                          AND NOT (source_id = :s AND version = :v)
                        RETURNING source_id, version
                        """
                    ),
                    {
                        "series": meta.series,
                        "d": meta.effective_date,
                        "s": meta.source_id,
                        "v": meta.version,
                    },
                )
            ).all()
        return [f"{r.source_id}@{r.version}" for r in rows]

    async def active_embedding_models(self) -> set[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT DISTINCT embedding_model FROM kb_documents WHERE status = 'active'")
            )
            return {r[0] for r in rows}

    async def vector_search(
        self, query_vector: Vector, flt: SearchFilter, limit: int
    ) -> list[uuid.UUID]:
        params: dict[str, Any] = {"qv": _vec(query_vector), "limit": limit}
        sql = _VECTOR_SQL.format(filters=_filter_sql(flt, params))
        async with self._engine.begin() as conn:
            await conn.execute(text(f"SET LOCAL hnsw.ef_search = {HNSW_EF_SEARCH:d}"))
            rows = (await conn.execute(text(sql), params)).scalars().all()
        return list(rows)

    async def keyword_search(
        self, normalized_query: str, flt: SearchFilter, limit: int
    ) -> list[uuid.UUID]:
        params: dict[str, Any] = {"q": normalized_query, "limit": limit}
        sql = _KEYWORD_SQL.format(filters=_filter_sql(flt, params))
        async with self._engine.connect() as conn:
            rows = (await conn.execute(text(sql), params)).scalars().all()
        return list(rows)

    async def fetch_chunks(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, RetrievedChunk]:
        if not ids:
            return {}
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT c.id, d.source_id, d.title, c.heading_path, c.text,
                               d.doc_type, d.compound_code
                        FROM kb_chunks c JOIN kb_documents d ON d.id = c.document_id
                        WHERE c.id = ANY(:ids)
                        """
                    ),
                    {"ids": list(ids)},
                )
            ).all()
        return {
            r.id: RetrievedChunk(
                chunk_id=r.id,
                source_id=r.source_id,
                title=r.title,
                heading_path=tuple(r.heading_path),
                text=r.text,
                score=0.0,
                doc_type=DocType(r.doc_type),
                compound_code=r.compound_code,
            )
            for r in rows
        }
