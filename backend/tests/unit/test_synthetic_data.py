import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import load_workbook

import synthetic_data as sd
from aios.shared.config import Settings


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("synthetic")
    sd.generate(out, seed=42)
    return out


def _units(corpus: Path) -> dict[str, dict[str, str]]:
    with (corpus / "inventory" / "units.csv").open(encoding="utf-8") as f:
        return {r["unit_id"]: r for r in csv.DictReader(f)}


def _gold(corpus: Path) -> list[dict[str, object]]:
    lines = (corpus / "eval" / "gold_qa.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_deterministic(corpus: Path, tmp_path: Path) -> None:
    sd.generate(tmp_path, seed=42)
    for rel in ("inventory/units.csv", "eval/gold_qa.jsonl", "catalog.json", "docs/faq.md"):
        assert (corpus / rel).read_bytes() == (tmp_path / rel).read_bytes(), rel


def test_unit_ids_unique_and_prices_follow_active_sheet(corpus: Path) -> None:
    units = _units(corpus)
    assert len(units) == sum(len(c.unit_types) for c in sd.COMPOUNDS) * 30
    for u in units.values():
        v1, v2 = int(u["price_v1_egp"]), int(u["price_v2_egp"])
        assert v2 == round(v1 * 1.08 / 1000) * 1000


def test_every_document_is_marked_synthetic(corpus: Path) -> None:
    for doc in (corpus / "docs").glob("*.md"):
        assert sd.SYNTHETIC_BANNER in doc.read_text(encoding="utf-8"), doc.name


def test_price_sheet_matches_inventory(corpus: Path) -> None:
    units = _units(corpus)
    sheet = next((corpus / "price_sheets").glob("QMH_price_sheet_v2_*.xlsx"))
    ws = load_workbook(sheet, read_only=True)["Price List"]
    rows = [r for r in ws.iter_rows(min_row=6, values_only=True) if r[0]]
    assert rows
    for unit_id, *_, price in rows:
        assert int(units[str(unit_id)]["price_v2_egp"]) == price


def test_gold_prices_match_inventory(corpus: Path) -> None:
    units = _units(corpus)
    priced = [g for g in _gold(corpus) if g["category"] == "unit_price"]
    assert priced
    for g in priced:
        unit_id = str(g["expected_sources"][0]).removeprefix("unit:")  # type: ignore[index]
        assert g["expected_answer"] == f"EGP {int(units[unit_id]['price_v2_egp']):,}"


def test_gold_inventory_search_only_lists_available_units(corpus: Path) -> None:
    units = _units(corpus)
    for g in (g for g in _gold(corpus) if g["category"] == "inventory_search"):
        for src in g["expected_sources"]:  # type: ignore[attr-defined]
            assert units[src.removeprefix("unit:")]["status"] == "available"


def test_gold_covers_both_languages(corpus: Path) -> None:
    gold = _gold(corpus)
    assert {g["language"] for g in gold} == {"en", "ar"}
    assert len({g["id"] for g in gold}) == len(gold)


def test_discount_limits_match_app_settings() -> None:
    defaults = Settings().discount_limits_pct
    assert {k: Decimal(v) for k, v in sd.DISCOUNT_LIMITS.items()} == defaults
