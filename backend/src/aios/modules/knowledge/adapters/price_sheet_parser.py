"""Adapter: developer price sheet (.xlsx) -> payment-plan and price-range sections.

Per-unit prices are deliberately NOT turned into text chunks. Exact prices are served
by the inventory tool from the live database, so a retired or stale sheet can never
leak a price through retrieval. The sheet contributes only:
- its payment plans,
- price ranges per unit type (for "roughly how much are 3-bedroom apartments?").
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from aios.modules.knowledge.domain.models import DocumentMeta, Section
from aios.shared.errors import InvalidInputError

_PRICE_HEADERS = ("unit code", "type", "bedrooms", "bua (m2)", "floor", "view", "price (egp)")
_PLAN_HEADERS = ("plan", "down %", "delivery %", "years", "frequency", "cash discount %")


def _norm(row: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(str(c).strip().lower() for c in row if c is not None)


class PriceSheetParser:
    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".xlsx"

    def parse(self, path: Path, meta: DocumentMeta) -> list[Section]:
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            if "Price List" not in wb.sheetnames or "Payment Plans" not in wb.sheetnames:
                raise InvalidInputError(f"{path.name}: expected 'Price List' and 'Payment Plans'")
            price_rows = list(wb["Price List"].iter_rows(values_only=True))
            plan_rows = list(wb["Payment Plans"].iter_rows(values_only=True))
        finally:
            wb.close()

        sections: list[Section] = []
        plans = _parse_plans(plan_rows, path.name)
        if plans:
            sections.append(Section((meta.title, "Payment plans"), "\n".join(plans)))
        ranges = _price_ranges(price_rows, path.name)
        if ranges:
            header = (
                f"Price ranges from price list {meta.version}, effective "
                f"{meta.effective_date.isoformat()}. For an exact unit price, use the "
                "inventory system."
            )
            sections.append(Section((meta.title, "Price ranges"), "\n".join([header, *ranges])))
        return sections


def _find_header(rows: Sequence[tuple[Any, ...]], expected: tuple[str, ...], name: str) -> int:
    for i, row in enumerate(rows):
        if _norm(row)[: len(expected)] == expected:
            return i
    raise InvalidInputError(f"{name}: header row {expected} not found")


def _parse_plans(rows: Sequence[tuple[Any, ...]], name: str) -> list[str]:
    start = _find_header(rows, _PLAN_HEADERS, name) + 1
    lines: list[str] = []
    for row in rows[start:]:
        if not row or row[0] is None:
            continue
        code, down, delivery, years, freq, cash = row[:6]
        if not years:
            lines.append(f"{code}: cash payment, {cash}% cash discount.")
            continue
        on_delivery = f", {delivery}% on delivery" if delivery else ""
        lines.append(
            f"{code}: {down}% down payment{on_delivery}, remainder over {years} years, "
            f"{str(freq).replace('_', '-')} installments."
        )
    return lines


def _price_ranges(rows: Sequence[tuple[Any, ...]], name: str) -> list[str]:
    start = _find_header(rows, _PRICE_HEADERS, name) + 1
    groups: dict[tuple[str, int], list[int]] = defaultdict(list)
    areas: dict[tuple[str, int], list[int]] = defaultdict(list)
    for row in rows[start:]:
        if not row or row[0] is None:
            continue
        _, unit_type, bedrooms, area, _, _, price = row[:7]
        key = (str(unit_type), int(str(bedrooms)))
        groups[key].append(int(str(price)))
        areas[key].append(int(str(area)))
    lines = []
    for (unit_type, beds), prices in sorted(groups.items()):
        a = areas[(unit_type, beds)]
        lines.append(
            f"{unit_type.replace('_', ' ')}, {beds} bedrooms: EGP {min(prices):,} to "
            f"EGP {max(prices):,} ({min(a)}-{max(a)} m2, {len(prices)} units listed)."
        )
    return lines
