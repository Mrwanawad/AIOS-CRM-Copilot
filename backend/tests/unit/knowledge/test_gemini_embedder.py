import asyncio
import math
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors, types

from aios.modules.knowledge.adapters.gemini_embedder import GeminiEmbedder, l2_normalize
from aios.modules.knowledge.ports.embedder import Embedder
from aios.shared.errors import ExternalServiceError, InvalidInputError

DIM = 4


def _api_error(code: int) -> errors.APIError:
    return errors.APIError(code, {"error": {"code": code, "message": "boom", "status": "X"}})


@dataclass
class FakeModels:
    """Stands in for ``client.aio.models``; records calls, can fail N times first."""

    fail_with: list[errors.APIError] = field(default_factory=list)
    drop_one: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def embed_content(
        self, *, model: str, contents: list[types.Content], config: types.EmbedContentConfig
    ) -> types.EmbedContentResponse:
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.fail_with:
            raise self.fail_with.pop(0)
        n = len(contents) - (1 if self.drop_one else 0)
        return types.EmbedContentResponse(
            embeddings=[types.ContentEmbedding(values=[3.0, 4.0, 0.0, 0.0]) for _ in range(n)]
        )


def make(models: FakeModels, **kw: Any) -> GeminiEmbedder:
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    emb = GeminiEmbedder(
        client,  # type: ignore[arg-type]
        model_id="gemini-embedding-001",
        dimension=DIM,
        sleep=fake_sleep,
        **kw,
    )
    emb.sleeps = sleeps  # type: ignore[attr-defined]
    return emb


def test_satisfies_port() -> None:
    emb: Embedder = make(FakeModels())
    assert emb.dimension == DIM


def test_documents_are_batched_and_normalized() -> None:
    models = FakeModels()
    vecs = asyncio.run(make(models, batch_size=2).embed_documents(["a", "b", "c"]))
    assert len(vecs) == 3
    assert [len(c["contents"]) for c in models.calls] == [2, 1]
    assert vecs[0] == pytest.approx([0.6, 0.8, 0.0, 0.0])
    cfg = models.calls[0]["config"]
    assert cfg.task_type == "RETRIEVAL_DOCUMENT"
    assert cfg.output_dimensionality == DIM


def test_each_text_is_its_own_content() -> None:
    models = FakeModels()
    asyncio.run(make(models).embed_documents(["unit A-101", "وحدة ب-202"]))
    contents = models.calls[0]["contents"]
    assert [c.parts[0].text for c in contents] == ["unit A-101", "وحدة ب-202"]


def test_query_uses_query_task_type() -> None:
    models = FakeModels()
    vec = asyncio.run(make(models).embed_query("3 bedrooms under 5M"))
    assert models.calls[0]["config"].task_type == "RETRIEVAL_QUERY"
    assert math.isclose(sum(x * x for x in vec), 1.0)


def test_retries_transient_errors_with_backoff() -> None:
    models = FakeModels(fail_with=[_api_error(429), _api_error(503)])
    emb = make(models)
    vec = asyncio.run(emb.embed_query("x"))
    assert len(vec) == DIM
    assert emb.sleeps == [1.0, 2.0]  # type: ignore[attr-defined]


def test_does_not_retry_client_errors() -> None:
    models = FakeModels(fail_with=[_api_error(400)])
    with pytest.raises(ExternalServiceError):
        asyncio.run(make(models).embed_query("x"))
    assert len(models.calls) == 1


def test_gives_up_after_max_retries() -> None:
    models = FakeModels(fail_with=[_api_error(429)] * 3)
    with pytest.raises(ExternalServiceError):
        asyncio.run(make(models, max_retries=2).embed_query("x"))
    assert len(models.calls) == 3


def test_count_mismatch_is_an_error() -> None:
    with pytest.raises(ExternalServiceError, match="expected 2 embeddings"):
        asyncio.run(make(FakeModels(drop_one=True)).embed_documents(["a", "b"]))


def test_rejects_empty_text() -> None:
    with pytest.raises(InvalidInputError):
        asyncio.run(make(FakeModels()).embed_documents(["ok", "  "]))


def test_zero_vector_rejected() -> None:
    with pytest.raises(ExternalServiceError):
        l2_normalize([0.0, 0.0])
