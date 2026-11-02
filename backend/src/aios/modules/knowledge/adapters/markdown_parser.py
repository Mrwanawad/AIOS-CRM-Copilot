"""Adapter: Markdown -> sections split on ATX headings (#, ##, ###)."""

from __future__ import annotations

import re
from pathlib import Path

from aios.modules.knowledge.domain.models import DocumentMeta, Section

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BANNER = re.compile(r"^>\s*SYNTHETIC DEMO DATA\b.*$", re.MULTILINE)


class MarkdownParser:
    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in {".md", ".markdown"}

    def parse(self, path: Path, meta: DocumentMeta) -> list[Section]:
        return parse_markdown(path.read_text(encoding="utf-8"), meta.title)


def parse_markdown(text: str, title: str) -> list[Section]:
    """Each heading starts a section; the trail keeps parent headings for context.

    The synthetic-data banner is dropped from chunk text: it is provenance, not
    knowledge, and would otherwise match every query.
    """
    text = _BANNER.sub("", text)
    sections: list[Section] = []
    trail: list[tuple[int, str]] = [(0, title)]
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append(Section(tuple(h for _, h in trail), body))
        buf.clear()

    for line in text.splitlines():
        m = _HEADING.match(line)
        if not m:
            buf.append(line)
            continue
        flush()
        level, heading = len(m.group(1)), m.group(2)
        if level == 1:
            trail[:] = [(0, title)]
            continue  # H1 is the document title, already in the trail
        while trail and trail[-1][0] >= level:
            trail.pop()
        trail.append((level, heading))
    flush()
    return sections
