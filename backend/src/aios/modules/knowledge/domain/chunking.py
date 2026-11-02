"""Section-aware chunking: never merge text across headings, split long sections on paragraphs."""

from __future__ import annotations

from collections.abc import Iterable

from aios.modules.knowledge.domain.models import Chunk, DocumentMeta, Section

DEFAULT_MAX_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 150


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    """Pack paragraphs (then lines) into pieces of at most ``max_chars``.

    A single line longer than ``max_chars`` is hard-split; that only happens on
    malformed input, so we prefer a slightly ugly cut over dropping text.
    """
    if len(text) <= max_chars:
        return [text]
    units: list[str] = []
    for para in text.split("\n\n"):
        if len(para) <= max_chars:
            units.append(para)
            continue
        for line in para.split("\n"):
            while len(line) > max_chars:
                units.append(line[:max_chars])
                line = line[max_chars - overlap :]
            units.append(line)

    pieces: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            pieces.append(current)
            tail = current[-overlap:] if overlap else ""
            current = (
                f"{tail}\n\n{unit}" if tail and len(tail) + len(unit) + 2 <= max_chars else unit
            )
        else:
            current = unit
    if current:
        pieces.append(current)
    return pieces


def chunk_sections(
    meta: DocumentMeta,
    sections: Iterable[Section],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    if overlap_chars >= max_chars:
        raise ValueError("overlap must be smaller than max_chars")
    chunks: list[Chunk] = []
    for section in sections:
        body = section.text.strip()
        if not body:
            continue
        for piece in _split_long(body, max_chars, overlap_chars):
            chunks.append(
                Chunk(
                    source_id=meta.source_id,
                    version=meta.version,
                    ordinal=len(chunks),
                    heading_path=section.heading_path,
                    text=piece.strip(),
                )
            )
    return chunks
