"""Knowledge ingestion + hybrid retrieval against real PostgreSQL/pgvector.

Uses the offline HashingEmbedder (lexical, not semantic), so the retrieval numbers
here are a floor for the plumbing, not a measure of Gemini quality.
"""

import dataclasses
import shutil
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from aios.modules.knowledge.adapters.hashing_embedder import HashingEmbedder
from aios.modules.knowledge.adapters.markdown_parser import MarkdownParser
from aios.modules.knowledge.adapters.pg_repository import PgKnowledgeRepository
from aios.modules.knowledge.adapters.price_sheet_parser import PriceSheetParser
from aios.modules.knowledge.application.evaluation import evaluate_retrieval, load_retrieval_gold
from aios.modules.knowledge.application.ingest import (
    IngestOutcome,
    IngestService,
    load_manifest,
)
from aios.modules.knowledge.application.retrieve import HybridRetriever
from aios.modules.knowledge.domain.models import DocStatus, DocType
from aios.modules.knowledge.ports.repository import SearchFilter

pytestmark = pytest.mark.db

DIM = 1536


def services(engine: AsyncEngine) -> tuple[IngestService, HybridRetriever]:
    repo = PgKnowledgeRepository(engine, dimension=DIM)
    emb = HashingEmbedder(DIM)
    return IngestService(repo, emb, [MarkdownParser(), PriceSheetParser()]), HybridRetriever(
        repo, emb
    )


async def statuses(engine: AsyncEngine) -> dict[str, str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT source_id || '@' || version, status FROM kb_documents")
        )
        return {r[0]: r[1] for r in rows}


async def test_ingest_is_idempotent(clean_db: AsyncEngine, corpus: Path) -> None:
    ingest, _ = services(clean_db)
    first = await ingest.ingest_manifest(corpus / "manifest.json")
    assert len(first) == 15
    assert {r.outcome for r in first} == {IngestOutcome.INGESTED}
    assert all(r.chunks > 0 for r in first)

    second = await ingest.ingest_manifest(corpus / "manifest.json")
    assert {r.outcome for r in second} == {IngestOutcome.UNCHANGED}


async def test_retired_price_sheets_are_never_retrieved(
    clean_db: AsyncEngine, corpus: Path
) -> None:
    ingest, retriever = services(clean_db)
    await ingest.ingest_manifest(corpus / "manifest.json")
    st = await statuses(clean_db)
    assert st["doc:QMH_price_sheet_v1@v1"] == "retired"
    assert st["doc:QMH_price_sheet_v2@v2"] == "active"

    results = await retriever.search("Qamar Heights price list v1 June 2026", k=20)
    assert results
    assert all(not r.source_id.endswith("_v1") for r in results)


async def test_new_version_retires_old_and_late_old_version_stays_retired(
    clean_db: AsyncEngine, corpus: Path, tmp_path: Path
) -> None:
    ingest, _ = services(clean_db)
    entries = {e.meta.source_id: e for e in load_manifest(corpus / "manifest.json")}
    v2 = entries["doc:QMH_price_sheet_v2"]
    await ingest.ingest(v2.path, v2.meta)

    v3_path = tmp_path / "QMH_v3.xlsx"
    shutil.copy(v2.path, v3_path)
    v3_meta = dataclasses.replace(
        v2.meta, source_id="doc:QMH_price_sheet_v3", version="v3", effective_date=date(2026, 12, 1)
    )
    result = await ingest.ingest(v3_path, v3_meta)
    assert result.retired == ["doc:QMH_price_sheet_v2@v2"]

    # An older sheet arriving late, even if marked active, must not become active.
    v1 = entries["doc:QMH_price_sheet_v1"]
    await ingest.ingest(v1.path, dataclasses.replace(v1.meta, status=DocStatus.ACTIVE))
    st = await statuses(clean_db)
    assert st == {
        "doc:QMH_price_sheet_v1@v1": "retired",
        "doc:QMH_price_sheet_v2@v2": "retired",
        "doc:QMH_price_sheet_v3@v3": "active",
    }


async def test_exact_plan_code_found_by_keyword(clean_db: AsyncEngine, corpus: Path) -> None:
    ingest, retriever = services(clean_db)
    await ingest.ingest_manifest(corpus / "manifest.json")
    results = await retriever.search("LZB-5Y", k=3)
    assert results[0].compound_code == "LZB"
    assert "keyword" in results[0].ranks


async def test_compound_filter_keeps_company_docs(clean_db: AsyncEngine, corpus: Path) -> None:
    ingest, retriever = services(clean_db)
    await ingest.ingest_manifest(corpus / "manifest.json")
    results = await retriever.search(
        "discount and maintenance deposit", SearchFilter(compound_codes=("SDG",)), k=20
    )
    assert {r.compound_code for r in results} <= {"SDG", None}
    assert any(r.doc_type is DocType.POLICY for r in results)


async def test_retrieval_quality_floor_on_gold_set(clean_db: AsyncEngine, corpus: Path) -> None:
    ingest, retriever = services(clean_db)
    await ingest.ingest_manifest(corpus / "manifest.json")
    gold = load_retrieval_gold(corpus / "eval" / "gold_qa.jsonl")
    report = await evaluate_retrieval(retriever, gold, k=8)
    print(
        f"\nrecall@8={report.recall_at_k:.2f} mrr={report.mrr:.2f} "
        f"en={report.language_recall('en'):.2f} ar={report.language_recall('ar'):.2f} "
        f"n={report.total} misses={report.misses}"
    )
    assert report.total >= 25
    assert report.recall_at_k >= 0.85
    assert report.language_recall("ar") >= 0.75
