"""Adapter: Cohere Rerank over plain HTTP (``POST /v2/rerank``).

Plain ``httpx`` instead of the ``cohere`` SDK: the call is one endpoint, and this
keeps the dependency surface small and the adapter easy to test with a mock transport.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx

from aios.modules.knowledge.ports.reranker import RerankResult
from aios.shared.errors import ExternalServiceError, InvalidInputError

logger = logging.getLogger(__name__)

COHERE_RERANK_URL = "https://api.cohere.com/v2/rerank"
_RETRYABLE_CODES = frozenset({429, 500, 502, 503, 504})


class CohereReranker:
    """Implements ``Reranker``. Retries 429/5xx and transport errors with backoff."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str,
        model_id: str,
        url: str = COHERE_RERANK_URL,
        max_retries: int = 3,
        base_delay_s: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty")
        self._client = client
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model_id = model_id
        self._url = url
        self._max_retries = max_retries
        self._base_delay_s = base_delay_s
        self._sleep = sleep

    @property
    def model_id(self) -> str:
        return self._model_id

    async def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int
    ) -> list[RerankResult]:
        if not query.strip():
            raise InvalidInputError("query must not be empty")
        if top_n <= 0:
            raise InvalidInputError("top_n must be positive")
        if not documents:
            return []
        payload = {
            "model": self._model_id,
            "query": query,
            "documents": list(documents),
            "top_n": min(top_n, len(documents)),
        }
        body = await self._post_with_retry(payload)
        return _parse(body, n_documents=len(documents))

    async def _post_with_retry(self, payload: dict[str, Any]) -> Any:
        attempt = 0
        while True:
            status: int | None
            cause: Exception | None
            try:
                response = await self._client.post(self._url, json=payload, headers=self._headers)
            except httpx.TransportError as exc:
                status, cause = None, exc
            else:
                if response.is_success:
                    return response.json()
                status, cause = response.status_code, None
            retryable = status is None or status in _RETRYABLE_CODES
            if not retryable or attempt >= self._max_retries:
                raise ExternalServiceError(
                    f"rerank request failed ({status or 'transport error'}) "
                    f"after {attempt + 1} attempt(s)"
                ) from cause
            delay = self._base_delay_s * 2**attempt
            logger.warning("rerank call failed with %s, retrying in %.1fs", status, delay)
            await self._sleep(delay)
            attempt += 1


def _parse(body: Any, *, n_documents: int) -> list[RerankResult]:
    try:
        raw = body["results"]
        results = [RerankResult(int(r["index"]), float(r["relevance_score"])) for r in raw]
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalServiceError("unexpected rerank response shape") from exc
    indexes = [r.index for r in results]
    if len(set(indexes)) != len(indexes) or any(not 0 <= i < n_documents for i in indexes):
        raise ExternalServiceError("rerank response has invalid document indexes")
    return sorted(results, key=lambda r: r.relevance, reverse=True)
