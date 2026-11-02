"""Knowledge domain: documents, chunks, retrieval results. Pure data, no IO."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from aios.shared.errors import InvalidInputError

_CHUNK_NS = uuid.UUID("6f1d3c1e-6a2b-4c55-9a8e-2f4b7d0c9e11")


class DocType(StrEnum):
    BROCHURE = "brochure"
    PRICE_SHEET = "price_sheet"
    POLICY = "policy"
    FAQ = "faq"
    PLAYBOOK = "playbook"


class DocStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    """What ingestion is told about a file. Never inferred from content."""

    source_id: str  # stable citation id, e.g. "doc:brochure_QMH"
    series: str  # documents that supersede each other share a series, e.g. "price_sheet:QMH"
    title: str
    doc_type: DocType
    version: str
    effective_date: date
    status: DocStatus = DocStatus.ACTIVE
    compound_code: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id.startswith("doc:"):
            raise InvalidInputError("source_id must start with 'doc:'")
        if not self.series or not self.title or not self.version:
            raise InvalidInputError("series, title and version are required")


@dataclass(frozen=True, slots=True)
class Section:
    """A parsed span of a document with its heading trail (e.g. ("Lazuli Bay", "Fees"))."""

    heading_path: tuple[str, ...]
    text: str


@dataclass(frozen=True, slots=True)
class Chunk:
    source_id: str
    version: str
    ordinal: int
    heading_path: tuple[str, ...]
    text: str

    @property
    def chunk_id(self) -> uuid.UUID:
        """Deterministic: re-ingesting the same version upserts instead of duplicating."""
        return uuid.uuid5(_CHUNK_NS, f"{self.source_id}|{self.version}|{self.ordinal}")

    def embedding_text(self, title: str) -> str:
        """Prefix the chunk with its document title and headings (contextual header)."""
        trail = " > ".join((title, *self.heading_path[1:]))
        return f"{trail}\n{self.text}"


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    source_id: str
    title: str
    heading_path: tuple[str, ...]
    text: str
    score: float
    doc_type: DocType
    compound_code: str | None
    ranks: dict[str, int] = field(default_factory=dict)  # retriever name -> 1-based rank
