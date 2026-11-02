"""Port: re-score retrieval candidates against the query with a cross-encoder."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RerankResult:
    index: int  # position in the input ``documents`` sequence
    relevance: float  # higher is more relevant; scale is model-specific


class Reranker(Protocol):
    """Implementations return at most ``top_n`` results, best first.

    Every ``index`` must point into ``documents`` and appear at most once.
    Failures after retries raise ``ExternalServiceError``.
    """

    @property
    def model_id(self) -> str: ...

    async def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int
    ) -> list[RerankResult]: ...
