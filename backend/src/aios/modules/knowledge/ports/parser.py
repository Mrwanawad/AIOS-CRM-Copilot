"""Port: turn a source file into ordered sections."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from aios.modules.knowledge.domain.models import DocumentMeta, Section


class DocumentParser(Protocol):
    def supports(self, path: Path) -> bool: ...

    def parse(self, path: Path, meta: DocumentMeta) -> list[Section]: ...
