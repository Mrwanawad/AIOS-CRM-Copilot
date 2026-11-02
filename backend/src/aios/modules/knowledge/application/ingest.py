"""Use case: ingest documents listed in a manifest (parse -> chunk -> embed -> store -> retire)."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path

from aios.modules.knowledge.domain.chunking import chunk_sections
from aios.modules.knowledge.domain.models import DocStatus, DocType, DocumentMeta
from aios.modules.knowledge.ports.embedder import Embedder
from aios.modules.knowledge.ports.parser import DocumentParser
from aios.modules.knowledge.ports.repository import KnowledgeRepository
from aios.shared.errors import InvalidInputError
from aios.shared.text import normalize_for_search

logger = logging.getLogger(__name__)


class IngestOutcome(StrEnum):
    INGESTED = "ingested"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class IngestResult:
    source_id: str
    version: str
    outcome: IngestOutcome
    chunks: int = 0
    retired: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    path: Path
    meta: DocumentMeta


def load_manifest(manifest_path: Path) -> list[ManifestEntry]:
    """Read ``manifest.json``: a list of {path, source_id, series, title, doc_type, version,
    effective_date, status?, compound_code?}. Paths are relative to the manifest file."""
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise InvalidInputError("manifest must be a JSON list")
    base = manifest_path.parent
    entries = []
    for item in raw:
        try:
            meta = DocumentMeta(
                source_id=item["source_id"],
                series=item["series"],
                title=item["title"],
                doc_type=DocType(item["doc_type"]),
                version=item["version"],
                effective_date=date.fromisoformat(item["effective_date"]),
                status=DocStatus(item.get("status", "active")),
                compound_code=item.get("compound_code"),
            )
        except (KeyError, ValueError) as exc:
            raise InvalidInputError(f"bad manifest entry {item!r}: {exc}") from exc
        path = (base / item["path"]).resolve()
        if not path.is_relative_to(base.resolve()):
            raise InvalidInputError(f"manifest path escapes its directory: {item['path']}")
        entries.append(ManifestEntry(path=path, meta=meta))
    # Oldest first, so superseding versions retire their predecessors in order.
    return sorted(entries, key=lambda e: (e.meta.series, e.meta.effective_date))


class IngestService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        embedder: Embedder,
        parsers: Sequence[DocumentParser],
    ) -> None:
        self._repo = repository
        self._embedder = embedder
        self._parsers = parsers

    async def ingest(self, path: Path, meta: DocumentMeta, *, force: bool = False) -> IngestResult:
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        existing = await self._repo.get_document(meta.source_id, meta.version)
        if (
            not force
            and existing is not None
            and existing.content_hash == content_hash
            and existing.embedding_model == self._embedder.model_id
        ):
            return IngestResult(meta.source_id, meta.version, IngestOutcome.UNCHANGED)

        parser = next((p for p in self._parsers if p.supports(path)), None)
        if parser is None:
            raise InvalidInputError(f"no parser for {path.name}")
        chunks = chunk_sections(meta, parser.parse(path, meta))
        if not chunks:
            raise InvalidInputError(f"{path.name} produced no text")

        embed_texts = [c.embedding_text(meta.title) for c in chunks]
        vectors = await self._embedder.embed_documents(embed_texts)
        search_texts = [normalize_for_search(t) for t in embed_texts]
        await self._repo.save_document(
            meta, content_hash, self._embedder.model_id, chunks, search_texts, vectors
        )
        retired = (
            await self._repo.retire_superseded(meta) if meta.status is DocStatus.ACTIVE else []
        )
        logger.info(
            "ingested %s@%s: %d chunks, retired %s",
            meta.source_id,
            meta.version,
            len(chunks),
            retired,
        )
        return IngestResult(
            meta.source_id, meta.version, IngestOutcome.INGESTED, len(chunks), retired
        )

    async def ingest_manifest(
        self, manifest_path: Path, *, force: bool = False
    ) -> list[IngestResult]:
        return [
            await self.ingest(e.path, e.meta, force=force) for e in load_manifest(manifest_path)
        ]
