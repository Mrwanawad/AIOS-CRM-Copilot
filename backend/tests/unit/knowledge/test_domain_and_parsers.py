import asyncio
import json
import uuid
from datetime import date
from pathlib import Path

import pytest

import synthetic_data as sd
from aios.modules.knowledge.adapters.markdown_parser import parse_markdown
from aios.modules.knowledge.adapters.price_sheet_parser import PriceSheetParser
from aios.modules.knowledge.application.ingest import load_manifest
from aios.modules.knowledge.application.retrieve import HybridRetriever
from aios.modules.knowledge.domain.chunking import chunk_sections
from aios.modules.knowledge.domain.fusion import rrf_fuse
from aios.modules.knowledge.domain.models import (
    DocStatus,
    DocType,
    DocumentMeta,
    RetrievedChunk,
    Section,
)
from aios.modules.knowledge.ports.repository import SearchFilter
from aios.shared.errors import ExternalServiceError, InvalidInputError
from aios.shared.text import normalize_for_search


def meta(**kw: object) -> DocumentMeta:
    base: dict[str, object] = {
        "source_id": "doc:x",
        "series": "brochure:X",
        "title": "X brochure",
        "doc_type": DocType.BROCHURE,
        "version": "v1",
        "effective_date": date(2026, 10, 1),
    }
    return DocumentMeta(**(base | kw))  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("corpus")
    sd.generate(out)
    return out


class TestNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("أسعار", "اسعار"),
            ("إسعار", "اسعار"),
            ("مُقَدَّم", "مقدم"),
            ("شقــة", "شقه"),
            ("مبنى", "مبني"),
            ("٣ غرف", "3 غرف"),
            ("  QMH-8Y   Plan ", "qmh-8y plan"),
        ],
    )
    def test_variants(self, raw: str, expected: str) -> None:
        assert normalize_for_search(raw) == expected


class TestChunking:
    def test_never_merges_sections(self) -> None:
        chunks = chunk_sections(meta(), [Section(("T", "A"), "alpha"), Section(("T", "B"), "beta")])
        assert [c.text for c in chunks] == ["alpha", "beta"]
        assert [c.ordinal for c in chunks] == [0, 1]

    def test_long_section_split_within_limit(self) -> None:
        body = "\n\n".join(f"paragraph {i} " + "x" * 80 for i in range(40))
        chunks = chunk_sections(meta(), [Section(("T",), body)], max_chars=500, overlap_chars=50)
        assert len(chunks) > 1
        assert all(len(c.text) <= 500 for c in chunks)
        assert "paragraph 39" in chunks[-1].text

    def test_chunk_ids_are_deterministic_and_version_scoped(self) -> None:
        a = chunk_sections(meta(), [Section(("T",), "same")])[0]
        b = chunk_sections(meta(), [Section(("T",), "same")])[0]
        c = chunk_sections(meta(version="v2"), [Section(("T",), "same")])[0]
        assert a.chunk_id == b.chunk_id != c.chunk_id

    def test_embedding_text_has_contextual_header(self) -> None:
        ch = chunk_sections(meta(), [Section(("X brochure", "Fees"), "10% maintenance")])[0]
        assert ch.embedding_text("X brochure") == "X brochure > Fees\n10% maintenance"


class TestFusion:
    def test_rrf_rewards_agreement(self) -> None:
        fused = rrf_fuse({"dense": ["a", "b", "c"], "keyword": ["c", "a", "d"]})
        assert [i for i, _, _ in fused][:2] == ["a", "c"]
        assert fused[0][2] == {"dense": 1, "keyword": 2}

    def test_limit_and_determinism(self) -> None:
        fused = rrf_fuse({"x": ["a", "b"], "y": ["b", "a"]}, limit=1)
        assert [i for i, _, _ in fused] == ["a"]


class TestMarkdownParser:
    def test_heading_trail_and_banner_removed(self) -> None:
        md = "# Title\n\n> SYNTHETIC DEMO DATA. x\n\nintro\n\n## Fees\nten\n### Sub\nnine\n## Plans\none"
        sections = parse_markdown(md, "Doc")
        assert [s.heading_path for s in sections] == [
            ("Doc",),
            ("Doc", "Fees"),
            ("Doc", "Fees", "Sub"),
            ("Doc", "Plans"),
        ]
        assert all("SYNTHETIC" not in s.text for s in sections)

    def test_synthetic_brochure(self, corpus: Path) -> None:
        text = (corpus / "docs" / "brochure_LZB.md").read_text(encoding="utf-8")
        sections = parse_markdown(text, "Lazuli Bay brochure")
        headings = {s.heading_path[-1] for s in sections}
        assert {"Payment plans", "أنظمة السداد", "Fees | المصاريف"} <= headings


class TestPriceSheetParser:
    def test_plans_and_ranges_but_no_unit_codes(self, corpus: Path) -> None:
        path = next((corpus / "price_sheets").glob("QMH_price_sheet_v2_*.xlsx"))
        m = meta(
            source_id="doc:QMH_price_sheet_v2",
            doc_type=DocType.PRICE_SHEET,
            version="v2",
            compound_code="QMH",
        )
        sections = PriceSheetParser().parse(path, m)
        joined = "\n".join(s.text for s in sections)
        assert "QMH-8Y: 10% down payment, remainder over 8 years, quarterly" in joined
        assert "QMH-CASH: cash payment, 20% cash discount." in joined
        assert "apartment, 2 bedrooms: EGP" in joined
        assert "QMH-B" not in joined  # unit codes/prices stay in the inventory system

    def test_rejects_unexpected_workbook(self, tmp_path: Path) -> None:
        from openpyxl import Workbook

        p = tmp_path / "bad.xlsx"
        Workbook().save(p)
        with pytest.raises(InvalidInputError):
            PriceSheetParser().parse(p, meta())


class TestManifest:
    def test_synthetic_manifest_loads_sorted(self, corpus: Path) -> None:
        entries = load_manifest(corpus / "manifest.json")
        assert len(entries) == 15
        assert all(e.path.exists() for e in entries)
        qmh = [e.meta for e in entries if e.meta.series == "price_sheet:QMH"]
        assert [(m.version, m.status) for m in qmh] == [
            ("v1", DocStatus.RETIRED),
            ("v2", DocStatus.ACTIVE),
        ]

    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.json").write_text(
            json.dumps(
                [
                    {
                        "path": "../etc/passwd",
                        "source_id": "doc:x",
                        "series": "s",
                        "title": "t",
                        "doc_type": "faq",
                        "version": "v1",
                        "effective_date": "2026-01-01",
                    }
                ]
            )
        )
        with pytest.raises(InvalidInputError, match="escapes"):
            load_manifest(tmp_path / "manifest.json")


class _FakeRepo:
    def __init__(self) -> None:
        self.ids = [uuid.uuid4() for _ in range(3)]

    async def vector_search(self, *_: object) -> list[uuid.UUID]:
        return [self.ids[0], self.ids[1]]

    async def keyword_search(self, *_: object) -> list[uuid.UUID]:
        return [self.ids[2], self.ids[0]]

    async def fetch_chunks(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, RetrievedChunk]:
        return {
            i: RetrievedChunk(i, "doc:x", "X", ("X",), "t", 0.0, DocType.FAQ, None) for i in ids
        }


class _DownEmbedder:
    model_id = "down"
    dimension = 4

    async def embed_query(self, text: str) -> list[float]:
        raise ExternalServiceError("down")


class _UpEmbedder(_DownEmbedder):
    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0, 0, 0]


def test_retriever_fuses_both_retrievers() -> None:
    repo = _FakeRepo()
    r = HybridRetriever(repo, _UpEmbedder())  # type: ignore[arg-type]
    out = asyncio.run(r.search("q", SearchFilter(), k=3))
    assert out[0].chunk_id == repo.ids[0]
    assert out[0].ranks == {"keyword": 2, "dense": 1}
    assert out[0].score > 0


def test_retriever_degrades_to_keyword_when_embedder_down() -> None:
    repo = _FakeRepo()
    r = HybridRetriever(repo, _DownEmbedder())  # type: ignore[arg-type]
    out = asyncio.run(r.search("q"))
    assert [c.chunk_id for c in out] == [repo.ids[2], repo.ids[0]]
    assert all(set(c.ranks) == {"keyword"} for c in out)


def test_retriever_rejects_blank_query() -> None:
    with pytest.raises(InvalidInputError):
        asyncio.run(HybridRetriever(_FakeRepo(), _UpEmbedder()).search("  "))  # type: ignore[arg-type]
