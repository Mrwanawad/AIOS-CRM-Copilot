"""Port: turn text into dense vectors for retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

Vector = list[float]


class Embedder(Protocol):
    """Asymmetric embedder: documents and queries may be encoded differently.

    Implementations must return exactly one L2-normalized vector of length
    ``dimension`` per input, in input order.
    """

    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]: ...

    async def embed_query(self, text: str) -> Vector: ...
