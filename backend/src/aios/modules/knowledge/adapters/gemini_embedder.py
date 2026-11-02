"""Adapter: Google Gemini API embeddings (``google-genai`` SDK)."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Sequence
from enum import StrEnum

from google import genai
from google.genai import errors, types

from aios.modules.knowledge.ports.embedder import Vector
from aios.shared.errors import ExternalServiceError, InvalidInputError

logger = logging.getLogger(__name__)

_RETRYABLE_CODES = frozenset({429, 500, 502, 503, 504})


class TaskType(StrEnum):
    DOCUMENT = "RETRIEVAL_DOCUMENT"
    QUERY = "RETRIEVAL_QUERY"


def l2_normalize(vec: Sequence[float]) -> Vector:
    """Unit-normalize. Truncated (Matryoshka) Gemini vectors are not unit length."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        raise ExternalServiceError("embedding service returned a zero vector")
    return [x / norm for x in vec]


class GeminiEmbedder:
    """Implements ``Embedder`` on top of ``client.aio.models.embed_content``.

    Each text is sent as its own ``Content`` so multimodal models
    (``gemini-embedding-2*``) don't merge a batch into one embedding; the
    response count is verified either way.
    """

    def __init__(
        self,
        client: genai.Client,
        *,
        model_id: str,
        dimension: int,
        batch_size: int = 100,
        max_retries: int = 4,
        base_delay_s: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if dimension <= 0 or batch_size <= 0:
            raise ValueError("dimension and batch_size must be positive")
        self._client = client
        self._model_id = model_id
        self._dimension = dimension
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._base_delay_s = base_delay_s
        self._sleep = sleep

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        vectors: list[Vector] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors.extend(await self._embed_batch(batch, TaskType.DOCUMENT))
        return vectors

    async def embed_query(self, text: str) -> Vector:
        return (await self._embed_batch([text], TaskType.QUERY))[0]

    async def _embed_batch(self, texts: Sequence[str], task: TaskType) -> list[Vector]:
        if any(not t.strip() for t in texts):
            raise InvalidInputError("cannot embed empty text")
        contents = [types.Content(parts=[types.Part(text=t)]) for t in texts]
        config = types.EmbedContentConfig(
            task_type=task.value, output_dimensionality=self._dimension
        )
        response = await self._call_with_retry(contents, config)

        embeddings = response.embeddings or []
        if len(embeddings) != len(texts):
            raise ExternalServiceError(
                f"expected {len(texts)} embeddings from {self._model_id}, got {len(embeddings)}"
            )
        vectors: list[Vector] = []
        for emb in embeddings:
            values = emb.values or []
            if len(values) != self._dimension:
                raise ExternalServiceError(
                    f"expected dimension {self._dimension}, got {len(values)}"
                )
            vectors.append(l2_normalize(values))
        return vectors

    async def _call_with_retry(
        self, contents: list[types.Content], config: types.EmbedContentConfig
    ) -> types.EmbedContentResponse:
        attempt = 0
        while True:
            try:
                return await self._client.aio.models.embed_content(
                    model=self._model_id, contents=contents, config=config
                )
            except errors.APIError as exc:
                retryable = exc.code in _RETRYABLE_CODES
                if not retryable or attempt >= self._max_retries:
                    raise ExternalServiceError(
                        f"embedding request failed ({exc.code}) after {attempt + 1} attempt(s)"
                    ) from exc
                delay = self._base_delay_s * 2**attempt
                logger.warning("embedding call failed with %s, retrying in %.1fs", exc.code, delay)
                await self._sleep(delay)
                attempt += 1
