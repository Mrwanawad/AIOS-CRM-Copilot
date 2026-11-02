import asyncio
import json
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx
import pytest

from aios.modules.knowledge.adapters.cohere_reranker import COHERE_RERANK_URL, CohereReranker
from aios.modules.knowledge.application.evaluation import (
    GoldQuestion,
    document_rank,
    load_retrieval_gold,
    section_rank,
)
from aios.modules.knowledge.application.retrieve import HybridRetriever, rerank_text
from aios.modules.knowledge.domain.models import DocType, RetrievedChunk
from aios.modules.knowledge.ports.reranker import Reranker, RerankResult
from aios.shared.errors import ExternalServiceError, InvalidInputError

REPO_ROOT = Path(__file__).resolve().parents[4]
PARAPHRASED = REPO_ROOT / "evals" / "retrieval_paraphrased.jsonl"


# --- Cohere adapter -------------------------------------------------------------------


def _reranker(
    handler: Callable[[httpx.Request], httpx.Response], sleeps: list[float] | None = None
) -> CohereReranker:
    async def fake_sleep(s: float) -> None:
        (sleeps if sleeps is not None else []).append(s)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return CohereReranker(
        client, api_key="test-key", model_id="rerank-v3.5", max_retries=2, sleep=fake_sleep
    )


def _ok(results: list[dict[str, float]]) -> httpx.Response:
    return httpx.Response(200, json={"id": "x", "results": results})


def test_satisfies_port() -> None:
    reranker: Reranker = _reranker(lambda _: _ok([]))
    assert reranker.model_id == "rerank-v3.5"


def test_request_shape_and_sorted_results() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok([{"index": 0, "relevance_score": 0.2}, {"index": 2, "relevance_score": 0.9}])

    out = asyncio.run(_reranker(handler).rerank("q", ["a", "b", "c"], top_n=10))
    assert [r.index for r in out] == [2, 0]
    req = seen[0]
    assert str(req.url) == COHERE_RERANK_URL
    assert req.headers["Authorization"] == "Bearer test-key"
    body = json.loads(req.content)
    assert body == {"model": "rerank-v3.5", "query": "q", "documents": ["a", "b", "c"], "top_n": 3}


def test_retries_rate_limit_then_succeeds() -> None:
    calls = iter([httpx.Response(429), httpx.Response(503)])
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return next(calls, _ok([{"index": 0, "relevance_score": 1.0}]))

    out = asyncio.run(_reranker(handler, sleeps).rerank("q", ["a"], top_n=1))
    assert out == [RerankResult(0, 1.0)]
    assert sleeps == [0.5, 1.0]


def test_transport_errors_are_retried_then_surface() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ExternalServiceError, match="transport error"):
        asyncio.run(_reranker(handler).rerank("q", ["a"], top_n=1))


def test_client_errors_are_not_retried() -> None:
    sleeps: list[float] = []
    with pytest.raises(ExternalServiceError, match="401"):
        asyncio.run(_reranker(lambda _: httpx.Response(401), sleeps).rerank("q", ["a"], top_n=1))
    assert sleeps == []


@pytest.mark.parametrize(
    "body",
    [
        {"nope": []},
        {"results": [{"index": 5, "relevance_score": 1.0}]},
        {"results": [{"index": 0, "relevance_score": 1.0}, {"index": 0, "relevance_score": 0.5}]},
    ],
)
def test_bad_responses_are_rejected(body: dict[str, object]) -> None:
    reranker = _reranker(lambda _: httpx.Response(200, json=body))
    with pytest.raises(ExternalServiceError):
        asyncio.run(reranker.rerank("q", ["a", "b"], top_n=2))


def test_input_validation_and_empty_documents() -> None:
    reranker = _reranker(lambda _: pytest.fail("must not call the API"))
    assert asyncio.run(reranker.rerank("q", [], top_n=3)) == []
    with pytest.raises(InvalidInputError):
        asyncio.run(reranker.rerank(" ", ["a"], top_n=1))
    with pytest.raises(InvalidInputError):
        asyncio.run(reranker.rerank("q", ["a"], top_n=0))


# --- Retriever rerank stage -----------------------------------------------------------


def _chunk(cid: uuid.UUID, heading: str) -> RetrievedChunk:
    return RetrievedChunk(
        cid, "doc:x", "X", ("X", heading), f"text {heading}", 0.0, DocType.FAQ, None
    )


class _Repo:
    def __init__(self, n: int) -> None:
        self.ids = [uuid.uuid4() for _ in range(n)]

    async def vector_search(self, *_: object) -> list[uuid.UUID]:
        return list(self.ids)

    async def keyword_search(self, *_: object) -> list[uuid.UUID]:
        return list(self.ids)

    async def fetch_chunks(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, RetrievedChunk]:
        return {i: _chunk(i, f"h{self.ids.index(i)}") for i in ids}


class _Embedder:
    model_id = "e"
    dimension = 4

    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0, 0, 0]


class _ReverseReranker:
    model_id = "reverse"

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int
    ) -> list[RerankResult]:
        self.seen = list(documents)
        n = len(documents)
        return [RerankResult(n - 1 - i, float(n - i)) for i in range(min(top_n, n))]


class _DownReranker:
    model_id = "down"

    async def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int
    ) -> list[RerankResult]:
        raise ExternalServiceError("down")


def test_reranker_sees_the_candidate_pool_and_reorders() -> None:
    repo = _Repo(6)
    reranker = _ReverseReranker()
    r = HybridRetriever(repo, _Embedder(), reranker=reranker, rerank_candidates=5)  # type: ignore[arg-type]
    out = asyncio.run(r.search("q", k=2))
    assert len(reranker.seen) == 5  # pool is rerank_candidates, not k
    assert reranker.seen[0] == "X > X > h0\ntext h0"
    assert [c.chunk_id for c in out] == [repo.ids[4], repo.ids[3]]
    assert out[0].ranks["rerank"] == 1
    assert out[1].ranks["rerank"] == 2
    assert out[0].score == 5.0


def test_reranker_down_keeps_fused_order() -> None:
    repo = _Repo(4)
    r = HybridRetriever(repo, _Embedder(), reranker=_DownReranker())  # type: ignore[arg-type]
    out = asyncio.run(r.search("q", k=3))
    assert [c.chunk_id for c in out] == repo.ids[:3]
    assert all("rerank" not in c.ranks for c in out)


def test_no_reranker_returns_k() -> None:
    repo = _Repo(5)
    out = asyncio.run(HybridRetriever(repo, _Embedder()).search("q", k=2))  # type: ignore[arg-type]
    assert [c.chunk_id for c in out] == repo.ids[:2]


def test_rerank_text_includes_context() -> None:
    assert rerank_text(_chunk(uuid.uuid4(), "Fees")) == "X > X > Fees\ntext Fees"


# --- Evaluation -----------------------------------------------------------------------


def test_section_rank_requires_the_right_section() -> None:
    item = GoldQuestion("p1", "ar", "c", "q", ("doc:x",), (("doc:x", "h2"),))
    results = [_chunk(uuid.uuid4(), h) for h in ("h0", "h1", "h2")]
    assert document_rank(results, item) == 1
    assert section_rank(results, item) == 3


def test_loads_both_gold_formats(tmp_path: Path) -> None:
    path = tmp_path / "gold.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {
                    "id": "g1",
                    "language": "en",
                    "category": "c",
                    "question": "q1",
                    "expected_sources": ["doc:a", "tool:inventory"],
                    "requires_tool": None,
                },
                {
                    "id": "g2",
                    "language": "en",
                    "category": "c",
                    "question": "q2",
                    "expected_sources": ["tool:x"],
                    "requires_tool": "inventory",
                },
                {
                    "id": "p1",
                    "language": "franco",
                    "category": "c",
                    "question": "q3",
                    "relevant": [
                        {"source": "doc:a", "section": "S1"},
                        {"source": "doc:b", "section": "S2"},
                        {"source": "doc:a", "section": "S3"},
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )
    g1, p1 = load_retrieval_gold(path)
    assert g1.expected_sources == ("doc:a",)
    assert g1.expected_sections == ()
    assert p1.expected_sources == ("doc:a", "doc:b")
    assert p1.expected_sections == (("doc:a", "S1"), ("doc:b", "S2"), ("doc:a", "S3"))


def test_paraphrased_set_is_well_formed() -> None:
    gold = load_retrieval_gold(PARAPHRASED)
    assert len(gold) >= 40
    assert {g.language for g in gold} == {"en", "ar", "franco"}
    assert len({g.id for g in gold}) == len(gold)
    assert all(g.expected_sections for g in gold)
