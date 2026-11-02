"""Generate the synthetic demo corpus: compounds, inventory, price sheets, docs, gold Q&A.

Every developer, compound, unit, price and policy here is FICTIONAL. Areas (New Cairo,
North Coast, ...) are real Egyptian locations used only for realism.

Deterministic: the same seed always produces the same content.

    uv run python tools/synthetic_data.py --out ../data/synthetic --seed 42
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from openpyxl import Workbook

SYNTHETIC_BANNER = (
    "SYNTHETIC DEMO DATA. All developers, compounds, prices and policies are fictional."
)
FIXED_TS = datetime(2026, 11, 1, tzinfo=UTC)
PRICE_ROUNDING = 1000

# Price sheet versions: v1 is retired (kept to test stale-document detection), v2 is active.
PRICE_SHEETS = (
    ("v1", date(2026, 6, 1), 1.00, "retired"),
    ("v2", date(2026, 10, 1), 1.08, "active"),
)

# Role discount limits (percent). Must match Settings.discount_limits_pct defaults.
DISCOUNT_LIMITS = {"rep": 2, "team_lead": 5, "manager": 10}


# --------------------------------------------------------------------------- model


@dataclass(frozen=True)
class Developer:
    code: str
    name_en: str
    name_ar: str
    founded: int
    delivered_projects: int


@dataclass(frozen=True)
class UnitType:
    name: str  # apartment, duplex, chalet, townhouse, twin_house, villa
    bedrooms: tuple[int, ...]
    area_sqm: tuple[int, int]
    price_per_sqm: int  # EGP, v1 sheet
    floors: int  # 0 for ground-only product (villas)


@dataclass(frozen=True)
class PaymentPlan:
    code: str
    down_payment_pct: int
    delivery_payment_pct: int
    years: int
    frequency: str  # monthly | quarterly | semi_annual | annual
    cash_discount_pct: int = 0


@dataclass(frozen=True)
class Compound:
    code: str
    name_en: str
    name_ar: str
    developer: str
    area_en: str
    area_ar: str
    land_acres: int
    delivery: date
    finishing: str  # fully_finished | semi_finished | core_and_shell
    maintenance_pct: int
    reservation_fee_egp: int
    buildings: int
    unit_types: tuple[UnitType, ...]
    plans: tuple[PaymentPlan, ...]
    amenities_en: tuple[str, ...]
    amenities_ar: tuple[str, ...]


@dataclass
class Unit:
    unit_id: str
    compound_code: str
    building: str
    unit_type: str
    bedrooms: int
    area_sqm: int
    floor: int
    view: str
    status: str
    delivery_date: str
    price_v1_egp: int
    price_v2_egp: int


@dataclass
class GoldItem:
    id: str
    language: str
    category: str
    question: str
    expected_answer: str
    expected_sources: list[str] = field(default_factory=list)
    requires_tool: str | None = None


DEVELOPERS = (
    Developer("NCD", "Nile Crest Developments", "نايل كرست للتطوير", 2009, 7),
    Developer("SHR", "Sahel Horizon Real Estate", "ساحل هورايزن العقارية", 2014, 4),
    Developer("DSP", "Delta Stone Properties", "دلتا ستون العقارية", 2003, 11),
)

COMPOUNDS = (
    Compound(
        code="QMH",
        name_en="Qamar Heights",
        name_ar="قمر هايتس",
        developer="NCD",
        area_en="New Cairo",
        area_ar="القاهرة الجديدة",
        land_acres=62,
        delivery=date(2029, 6, 30),
        finishing="semi_finished",
        maintenance_pct=8,
        reservation_fee_egp=100_000,
        buildings=12,
        unit_types=(
            UnitType("apartment", (2, 3), (115, 185), 58_000, 7),
            UnitType("duplex", (4,), (230, 290), 61_000, 7),
        ),
        plans=(
            PaymentPlan("QMH-8Y", 10, 0, 8, "quarterly"),
            PaymentPlan("QMH-10Y", 5, 5, 10, "quarterly"),
            PaymentPlan("QMH-CASH", 100, 0, 0, "annual", cash_discount_pct=20),
        ),
        amenities_en=("clubhouse", "central park 14 acres", "international school plot", "mall"),
        amenities_ar=("نادي اجتماعي", "حديقة مركزية 14 فدان", "أرض مدرسة دولية", "مول تجاري"),
    ),
    Compound(
        code="LZB",
        name_en="Lazuli Bay",
        name_ar="لازولي باي",
        developer="SHR",
        area_en="North Coast (Ras El Hekma)",
        area_ar="الساحل الشمالي (رأس الحكمة)",
        land_acres=140,
        delivery=date(2028, 6, 30),
        finishing="fully_finished",
        maintenance_pct=10,
        reservation_fee_egp=150_000,
        buildings=9,
        unit_types=(
            UnitType("chalet", (1, 2, 3), (75, 140), 92_000, 3),
            UnitType("villa", (4, 5), (240, 360), 88_000, 0),
        ),
        plans=(
            PaymentPlan("LZB-7Y", 10, 0, 7, "semi_annual"),
            PaymentPlan("LZB-5Y", 15, 10, 5, "quarterly"),
        ),
        amenities_en=("1.2 km sandy beach", "marina", "lagoons", "beach club", "hotel"),
        amenities_ar=("شاطئ رملي 1.2 كم", "مارينا", "لاجونات", "بيتش كلوب", "فندق"),
    ),
    Compound(
        code="SDG",
        name_en="Sidra Groves",
        name_ar="سدرة جروفز",
        developer="DSP",
        area_en="Sheikh Zayed",
        area_ar="الشيخ زايد",
        land_acres=85,
        delivery=date(2028, 12, 31),
        finishing="core_and_shell",
        maintenance_pct=7,
        reservation_fee_egp=200_000,
        buildings=0,
        unit_types=(
            UnitType("townhouse", (3, 4), (180, 230), 52_000, 0),
            UnitType("twin_house", (4,), (240, 280), 55_000, 0),
            UnitType("villa", (5, 6), (300, 420), 57_000, 0),
        ),
        plans=(
            PaymentPlan("SDG-8Y", 10, 10, 8, "quarterly"),
            PaymentPlan("SDG-6Y", 20, 0, 6, "monthly"),
        ),
        amenities_en=("gated community", "sports club", "jogging track 3 km", "nursery"),
        amenities_ar=("كمبوند مغلق", "نادي رياضي", "مسار جري 3 كم", "حضانة"),
    ),
    Compound(
        code="LTC",
        name_en="Lotus Capital Residence",
        name_ar="لوتس كابيتال ريزيدنس",
        developer="NCD",
        area_en="New Administrative Capital (R7)",
        area_ar="العاصمة الإدارية الجديدة (R7)",
        land_acres=38,
        delivery=date(2027, 12, 31),
        finishing="fully_finished",
        maintenance_pct=8,
        reservation_fee_egp=75_000,
        buildings=10,
        unit_types=(UnitType("apartment", (1, 2, 3), (70, 170), 47_000, 9),),
        plans=(
            PaymentPlan("LTC-9Y", 10, 0, 9, "quarterly"),
            PaymentPlan("LTC-12Y", 0, 10, 12, "quarterly"),
        ),
        amenities_en=("near monorail station", "co-working space", "kids area", "gym"),
        amenities_ar=("بجوار محطة المونوريل", "مساحة عمل مشتركة", "منطقة أطفال", "جيم"),
    ),
)

VIEWS = ("garden", "pool", "street", "landscape", "sea", "lagoon")
VIEW_PREMIUM = {"sea": 0.12, "lagoon": 0.08, "pool": 0.05, "garden": 0.04, "landscape": 0.02}
STATUS_WEIGHTS = (("available", 60), ("reserved", 15), ("sold", 25))


# --------------------------------------------------------------------------- inventory


def _round_price(value: float) -> int:
    return int(round(value / PRICE_ROUNDING) * PRICE_ROUNDING)


def _views_for(c: Compound) -> tuple[str, ...]:
    if c.code == "LZB":
        return ("sea", "lagoon", "pool", "landscape")
    return ("garden", "pool", "street", "landscape")


def generate_units(rng: random.Random, units_per_type: int = 30) -> list[Unit]:
    units: list[Unit] = []
    statuses = [s for s, _ in STATUS_WEIGHTS]
    weights = [w for _, w in STATUS_WEIGHTS]
    for c in COMPOUNDS:
        seq = 0
        for ut in c.unit_types:
            for _ in range(units_per_type):
                seq += 1
                bedrooms = rng.choice(ut.bedrooms)
                lo, hi = ut.area_sqm
                area = rng.randint(lo, hi)
                floor = rng.randint(0, ut.floors) if ut.floors else 0
                view = rng.choice(_views_for(c))
                if c.buildings:
                    building = f"B{rng.randint(1, c.buildings):02d}"
                    unit_id = f"{c.code}-{building}-{floor:02d}{seq:03d}"
                else:
                    building = f"Z{rng.randint(1, 6)}"
                    unit_id = f"{c.code}-{building}-{seq:03d}"
                floor_premium = 0.01 * min(floor, 5) if ut.floors else 0.0
                v1 = _round_price(
                    area * ut.price_per_sqm * (1 + VIEW_PREMIUM.get(view, 0) + floor_premium)
                )
                v2 = _round_price(v1 * PRICE_SHEETS[1][2])
                units.append(
                    Unit(
                        unit_id=unit_id,
                        compound_code=c.code,
                        building=building,
                        unit_type=ut.name,
                        bedrooms=bedrooms,
                        area_sqm=area,
                        floor=floor,
                        view=view,
                        status=rng.choices(statuses, weights)[0],
                        delivery_date=c.delivery.isoformat(),
                        price_v1_egp=v1,
                        price_v2_egp=v2,
                    )
                )
    return units


# --------------------------------------------------------------------------- writers


def write_inventory_csv(units: Iterable[Unit], path: Path) -> None:
    rows = [asdict(u) for u in units]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_price_sheets(units: list[Unit], out: Path) -> list[Path]:
    """One workbook per compound per version, shaped like a developer price sheet."""
    paths: list[Path] = []
    for c in COMPOUNDS:
        for version, effective, _, state in PRICE_SHEETS:
            wb = Workbook()
            ws = wb.active
            assert ws is not None
            ws.title = "Price List"
            ws.append([f"{c.name_en} | {c.name_ar} - Price List {version}"])
            ws.append([f"Effective: {effective.isoformat()}", f"Status: {state}"])
            ws.append([SYNTHETIC_BANNER])
            ws.append([])
            ws.append(["Unit Code", "Type", "Bedrooms", "BUA (m2)", "Floor", "View", "Price (EGP)"])
            price_attr = f"price_{version}_egp"
            for u in (u for u in units if u.compound_code == c.code):
                ws.append(
                    [
                        u.unit_id,
                        u.unit_type,
                        u.bedrooms,
                        u.area_sqm,
                        u.floor,
                        u.view,
                        getattr(u, price_attr),
                    ]
                )
            plans = wb.create_sheet("Payment Plans")
            plans.append(["Plan", "Down %", "Delivery %", "Years", "Frequency", "Cash discount %"])
            for p in c.plans:
                plans.append(
                    [
                        p.code,
                        p.down_payment_pct,
                        p.delivery_payment_pct,
                        p.years,
                        p.frequency,
                        p.cash_discount_pct,
                    ]
                )
            wb.properties.creator = "synthetic-generator"
            wb.properties.created = FIXED_TS.replace(tzinfo=None)
            path = out / f"{c.code}_price_sheet_{version}_{effective.isoformat()}.xlsx"
            wb.save(path)
            paths.append(path)
    return paths


def _developer(code: str) -> Developer:
    return next(d for d in DEVELOPERS if d.code == code)


_FINISHING = {
    "fully_finished": (
        "Fully finished with AC units and kitchen cabinets",
        "تشطيب كامل بالتكييفات والمطبخ",
    ),
    "semi_finished": (
        "Semi-finished (plastering, electrical and plumbing points)",
        "نصف تشطيب (محارة وتأسيس كهرباء وسباكة)",
    ),
    "core_and_shell": (
        "Core and shell (structure and facade only)",
        "على الطوب الأحمر (هيكل وواجهات فقط)",
    ),
}
_FREQ_AR = {"monthly": "شهري", "quarterly": "ربع سنوي", "semi_annual": "نصف سنوي", "annual": "سنوي"}


def _plan_line_en(p: PaymentPlan) -> str:
    if p.years == 0:
        return f"- **{p.code}**: cash payment, {p.cash_discount_pct}% cash discount."
    delivery = f", {p.delivery_payment_pct}% on delivery" if p.delivery_payment_pct else ""
    return (
        f"- **{p.code}**: {p.down_payment_pct}% down payment{delivery}, "
        f"remainder over {p.years} years in {p.frequency.replace('_', '-')} installments."
    )


def _plan_line_ar(p: PaymentPlan) -> str:
    if p.years == 0:
        return f"- **{p.code}**: كاش، خصم {p.cash_discount_pct}%."
    delivery = f"، و{p.delivery_payment_pct}% عند الاستلام" if p.delivery_payment_pct else ""
    return (
        f"- **{p.code}**: مقدم {p.down_payment_pct}%{delivery}، "
        f"والباقي على {p.years} سنين أقساط {_FREQ_AR[p.frequency]}."
    )


def brochure_md(c: Compound, units: list[Unit]) -> str:
    d = _developer(c.developer)
    mine = [u for u in units if u.compound_code == c.code]
    types = sorted({u.unit_type for u in mine})
    fin_en, fin_ar = _FINISHING[c.finishing]
    type_lines = []
    for t in types:
        ts = [u for u in mine if u.unit_type == t]
        beds = sorted({u.bedrooms for u in ts})
        type_lines.append(
            f"- {t.replace('_', ' ').title()}: {min(u.area_sqm for u in ts)}-"
            f"{max(u.area_sqm for u in ts)} m2, {'/'.join(map(str, beds))} bedrooms"
        )
    return "\n".join(
        [
            f"# {c.name_en} | {c.name_ar}",
            "",
            f"> {SYNTHETIC_BANNER}",
            "",
            f"Developer: {d.name_en} ({d.name_ar}), founded {d.founded}, "
            f"{d.delivered_projects} delivered projects.",
            "",
            "## Overview",
            f"{c.name_en} is a {c.land_acres}-acre community in {c.area_en}. "
            f"Expected delivery: {c.delivery.strftime('%B %Y')}.",
            "",
            "## نبذة",
            f"{c.name_ar} كمبوند على مساحة {c.land_acres} فدان في {c.area_ar}. "
            f"الاستلام المتوقع: {c.delivery.year}/{c.delivery.month:02d}.",
            "",
            "## Unit types",
            *type_lines,
            "",
            "## Finishing | التشطيب",
            f"{fin_en}. | {fin_ar}.",
            "",
            "## Amenities | الخدمات",
            *(f"- {en} | {ar}" for en, ar in zip(c.amenities_en, c.amenities_ar, strict=True)),
            "",
            "## Payment plans",
            *(_plan_line_en(p) for p in c.plans),
            "",
            "## أنظمة السداد",
            *(_plan_line_ar(p) for p in c.plans),
            "",
            "## Fees | المصاريف",
            f"- Maintenance deposit: {c.maintenance_pct}% of unit price, paid on delivery. "
            f"| وديعة الصيانة: {c.maintenance_pct}% من سعر الوحدة تدفع عند الاستلام.",
            f"- Reservation fee: EGP {c.reservation_fee_egp:,}, deducted from the down payment. "
            f"| رسوم الحجز: {c.reservation_fee_egp:,} جنيه تخصم من المقدم.",
            "",
        ]
    )


def policies_md() -> str:
    return f"""# Sales Policies | سياسات المبيعات

> {SYNTHETIC_BANNER}

## 1. Discount authority | صلاحيات الخصم
Discounts are a percentage of the active price sheet price.
- Sales rep: up to {DISCOUNT_LIMITS["rep"]}%.
- Team lead: up to {DISCOUNT_LIMITS["team_lead"]}%.
- Sales manager: up to {DISCOUNT_LIMITS["manager"]}%.
- Above {DISCOUNT_LIMITS["manager"]}%: written approval from the commercial director.
Discounts cannot be combined with the cash discount of a cash plan.

السيلز ليه خصم لحد {DISCOUNT_LIMITS["rep"]}%، التيم ليدر لحد {DISCOUNT_LIMITS["team_lead"]}%،
والمانجر لحد {DISCOUNT_LIMITS["manager"]}%. أي حاجة أكتر من كده محتاجة موافقة مكتوبة من الكومرشال دايركتور.
الخصم مش بيتجمع مع خصم الكاش.

## 2. Reservations | الحجز
- A unit is held for 48 hours after the reservation fee is paid.
- The reservation fee is fully refundable within 14 days if no contract is signed.
- After 14 days, 50% of the reservation fee is non-refundable.

الوحدة بتتحجز 48 ساعة بعد دفع رسوم الحجز. الرسوم بترجع كاملة خلال 14 يوم لو مفيش عقد،
وبعد 14 يوم بيتخصم 50% منها.

## 3. Price sheets | قوايم الأسعار
Only the **active** price sheet may be quoted. Retired sheets are kept for audit only.
Never quote a price from memory or from an old brochure; check the live inventory.

## 4. Client data | بيانات العملاء
- Calls are recorded only after the client is informed at the start of the call.
- Share client phone numbers only inside the CRM, never on personal WhatsApp groups.
- Client data is retained for 24 months after the last interaction unless the client asks for deletion.

## 5. Resale and transfer | إعادة البيع والتنازل
- Transfer of ownership before delivery is allowed after paying 30% of the unit price.
- Transfer fee: 5% of the contract value, paid to the developer.
"""


def faq_md() -> str:
    lines = ["# FAQ | أسئلة متكررة", "", f"> {SYNTHETIC_BANNER}", ""]
    for c in COMPOUNDS:
        fin_en, fin_ar = _FINISHING[c.finishing]
        lines += [
            f"## {c.name_en} | {c.name_ar}",
            f"**Q: When is delivery in {c.name_en}?**  ",
            f"A: {c.delivery.strftime('%B %Y')}.",
            "",
            f"**س: الاستلام امتى في {c.name_ar}؟**  ",
            f"ج: {c.delivery.year}/{c.delivery.month:02d}.",
            "",
            "**Q: What is the finishing level?**  ",
            f"A: {fin_en}. | {fin_ar}.",
            "",
            "**Q: What is the maintenance deposit?**  ",
            f"A: {c.maintenance_pct}% of the unit price, paid on delivery.",
            "",
        ]
    return "\n".join(lines)


def playbook_md() -> str:
    return f"""# Team Lead Playbook | بلاي بوك التيم ليدر

> {SYNTHETIC_BANNER}

## Qualify before you pitch | اعرف العميل الأول
Ask these five before recommending any unit:
1. Budget: total, and how much down payment is ready now.
2. Purpose: living, investment or summer home.
3. Timeline: when they need to move in.
4. Location constraints: work, schools, family.
5. Decision makers: who else must agree.

متقترحش وحدة قبل ما تعرف الميزانية، الغرض، الميعاد، المكان، ومين صاحب القرار.

## Objection: "The price is too high" | "السعر غالي"
- Do not jump to a discount. Reframe to the monthly or quarterly installment.
- Compare price per m2 with the compound's area average, not with another area.
- Offer a longer plan before offering a discount. Discount is the last card.
- If you need a discount above your limit, escalate with the full context; never promise it first.

متقولش "هشوفلك خصم" من أول مكالمة. حوّل الكلام للقسط، وبعدين نظام سداد أطول، والخصم آخر كارت.

## Objection: "I'm worried about delivery delays" | "خايف من التأخير"
- Share the developer's delivered-projects record from the brochure.
- Point to construction progress updates (ask the team lead for the latest site photos).
- Never promise a delivery date earlier than the contract date.

## Objection: "Competitor X is cheaper" | "المنافس أرخص"
- Ask for the exact unit and plan they were offered; compare like for like (finishing, delivery, maintenance %).
- A fully finished unit is not comparable to a core-and-shell unit at the same price per m2.

## Investment clients | عملاء الاستثمار
- North Coast (Lazuli Bay): rental demand is seasonal (June-September).
- New Capital (Lotus Capital Residence): earliest delivery, suits clients who want rental income soon.

## Follow-up rules | قواعد المتابعة
- First follow-up within 24 hours of a site visit.
- Send a written summary of every number you quoted (unit, price, plan) on WhatsApp after the call.
- If the client goes silent for 7 days, escalate to the team lead for a second voice.
"""


# --------------------------------------------------------------------------- gold Q&A


def _fmt_egp(n: int) -> str:
    return f"EGP {n:,}"


def gold_items(units: list[Unit], rng: random.Random) -> list[GoldItem]:
    items: list[GoldItem] = []

    def add(**kw: object) -> None:
        items.append(GoldItem(id=f"g{len(items) + 1:03d}", **kw))  # type: ignore[arg-type]

    for c in COMPOUNDS:
        brochure = f"doc:brochure_{c.code}"
        main = c.plans[0]
        add(
            language="en",
            category="payment_plan",
            question=f"What is the down payment and plan length for {c.name_en}'s {main.code} plan?",
            expected_answer=f"{main.down_payment_pct}% down payment, {main.years} years, "
            f"{main.frequency.replace('_', '-')} installments.",
            expected_sources=[brochure],
        )
        add(
            language="ar",
            category="payment_plan",
            question=f"المقدم كام في {c.name_ar} على نظام {main.code}؟",
            expected_answer=f"مقدم {main.down_payment_pct}% والباقي على {main.years} سنين.",
            expected_sources=[brochure],
        )
        add(
            language="en",
            category="fees",
            question=f"What is the maintenance deposit in {c.name_en}?",
            expected_answer=f"{c.maintenance_pct}% of the unit price, paid on delivery.",
            expected_sources=[brochure, "doc:faq"],
        )
        add(
            language="ar",
            category="delivery",
            question=f"الاستلام امتى في {c.name_ar}؟",
            expected_answer=f"{c.delivery.year}/{c.delivery.month:02d}",
            expected_sources=[brochure, "doc:faq"],
        )
        add(
            language="en",
            category="fees",
            question=f"How much is the reservation fee in {c.name_en}, and is it refundable?",
            expected_answer=f"{_fmt_egp(c.reservation_fee_egp)}; fully refundable within 14 days "
            "if no contract is signed, 50% non-refundable after that.",
            expected_sources=[brochure, "doc:policies"],
        )

        available = [u for u in units if u.compound_code == c.code and u.status == "available"]
        for u in rng.sample(available, k=min(2, len(available))):
            add(
                language="en",
                category="unit_price",
                question=f"What is the current price of unit {u.unit_id}?",
                expected_answer=_fmt_egp(u.price_v2_egp),
                expected_sources=[f"unit:{u.unit_id}", f"doc:{c.code}_price_sheet_v2"],
                requires_tool="inventory",
            )
        u = rng.choice(available)
        add(
            language="ar",
            category="unit_price",
            question=f"سعر الوحدة {u.unit_id} كام دلوقتي؟",
            expected_answer=_fmt_egp(u.price_v2_egp),
            expected_sources=[f"unit:{u.unit_id}"],
            requires_tool="inventory",
        )

        beds = c.unit_types[0].bedrooms[-1]
        budget = sorted(x.price_v2_egp for x in available)[len(available) // 2]
        matches = sorted(
            x.unit_id for x in available if x.bedrooms == beds and x.price_v2_egp <= budget
        )
        add(
            language="en",
            category="inventory_search",
            question=f"List available {beds}-bedroom units in {c.name_en} priced up to "
            f"{_fmt_egp(budget)}.",
            expected_answer=", ".join(matches) if matches else "No matching units.",
            expected_sources=[f"unit:{m}" for m in matches],
            requires_tool="inventory",
        )

        plan = next(p for p in c.plans if p.years)
        add(
            language="en",
            category="calculation",
            question=f"For unit {u.unit_id} on plan {plan.code}, what is the down payment amount?",
            expected_answer=_fmt_egp(round(u.price_v2_egp * plan.down_payment_pct / 100)),
            expected_sources=[f"unit:{u.unit_id}", brochure],
            requires_tool="calculator",
        )

    for role, limit in DISCOUNT_LIMITS.items():
        add(
            language="en",
            category="policy",
            question=f"What is the maximum discount a {role.replace('_', ' ')} can approve?",
            expected_answer=f"{limit}% of the active price sheet price.",
            expected_sources=["doc:policies"],
        )
    add(
        language="ar",
        category="policy",
        question="ينفع أجمع خصم السيلز مع خصم الكاش؟",
        expected_answer="لا، الخصم مش بيتجمع مع خصم الكاش.",
        expected_sources=["doc:policies"],
    )
    add(
        language="en",
        category="policy",
        question="Can a client transfer a unit before delivery?",
        expected_answer="Yes, after paying 30% of the unit price; transfer fee is 5% of the "
        "contract value.",
        expected_sources=["doc:policies"],
    )
    add(
        language="en",
        category="policy",
        question="Can I quote a price from the June 2026 price sheet?",
        expected_answer="No. The June 2026 (v1) sheets are retired; only the active v2 sheet "
        "may be quoted.",
        expected_sources=["doc:policies"],
    )
    add(
        language="ar",
        category="playbook",
        question="العميل بيقول السعر غالي، أعمل إيه؟",
        expected_answer="متبدأش بالخصم. حوّل الكلام للقسط، اعرض نظام سداد أطول، والخصم آخر كارت "
        "وفي حدود صلاحيتك.",
        expected_sources=["doc:playbook"],
    )
    add(
        language="en",
        category="playbook",
        question="What should I ask a client before recommending any unit?",
        expected_answer="Budget (total and ready down payment), purpose, timeline, location "
        "constraints, and decision makers.",
        expected_sources=["doc:playbook"],
    )
    add(
        language="en",
        category="out_of_scope",
        question="What is the price per m2 in Marassi?",
        expected_answer="Not in the knowledge base; say so and escalate instead of guessing.",
        expected_sources=[],
    )
    return items


# --------------------------------------------------------------------------- manifest

DOCS_EFFECTIVE = date(2026, 10, 1)


def manifest_entries() -> list[dict[str, object]]:
    """Ingestion manifest: explicit metadata per file (paths relative to the corpus root)."""
    entries: list[dict[str, object]] = []
    company_docs = (
        ("policies", "policy", "Sales Policies"),
        ("faq", "faq", "FAQ"),
        ("playbook", "playbook", "Team Lead Playbook"),
    )
    for name, doc_type, title in company_docs:
        entries.append(
            {
                "path": f"docs/{name}.md",
                "source_id": f"doc:{name}",
                "series": f"{doc_type}:company",
                "title": title,
                "doc_type": doc_type,
                "version": "v1",
                "effective_date": DOCS_EFFECTIVE.isoformat(),
                "status": "active",
                "compound_code": None,
            }
        )
    for c in COMPOUNDS:
        entries.append(
            {
                "path": f"docs/brochure_{c.code}.md",
                "source_id": f"doc:brochure_{c.code}",
                "series": f"brochure:{c.code}",
                "title": f"{c.name_en} brochure",
                "doc_type": "brochure",
                "version": "v1",
                "effective_date": DOCS_EFFECTIVE.isoformat(),
                "status": "active",
                "compound_code": c.code,
            }
        )
        for version, effective, _, state in PRICE_SHEETS:
            entries.append(
                {
                    "path": f"price_sheets/{c.code}_price_sheet_{version}_{effective.isoformat()}.xlsx",
                    "source_id": f"doc:{c.code}_price_sheet_{version}",
                    "series": f"price_sheet:{c.code}",
                    "title": f"{c.name_en} price list {version}",
                    "doc_type": "price_sheet",
                    "version": version,
                    "effective_date": effective.isoformat(),
                    "status": state,
                    "compound_code": c.code,
                }
            )
    return entries


# --------------------------------------------------------------------------- main


def generate(out: Path, seed: int = 42) -> dict[str, int]:
    rng = random.Random(seed)
    for sub in ("docs", "price_sheets", "inventory", "eval"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    units = generate_units(rng)
    write_inventory_csv(units, out / "inventory" / "units.csv")
    sheets = write_price_sheets(units, out / "price_sheets")

    (out / "docs" / "policies.md").write_text(policies_md(), encoding="utf-8")
    (out / "docs" / "faq.md").write_text(faq_md(), encoding="utf-8")
    (out / "docs" / "playbook.md").write_text(playbook_md(), encoding="utf-8")
    for c in COMPOUNDS:
        (out / "docs" / f"brochure_{c.code}.md").write_text(brochure_md(c, units), encoding="utf-8")

    meta = {
        "banner": SYNTHETIC_BANNER,
        "seed": seed,
        "developers": [asdict(d) for d in DEVELOPERS],
        "compounds": [{**asdict(c), "delivery": c.delivery.isoformat()} for c in COMPOUNDS],
        "price_sheets": [
            {"version": v, "effective": e.isoformat(), "multiplier": m, "status": s}
            for v, e, m, s in PRICE_SHEETS
        ],
        "discount_limits_pct": DISCOUNT_LIMITS,
    }
    (out / "catalog.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    (out / "manifest.json").write_text(
        json.dumps(manifest_entries(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    gold = gold_items(units, rng)
    with (out / "eval" / "gold_qa.jsonl").open("w", encoding="utf-8") as f:
        for g in gold:
            f.write(json.dumps(asdict(g), ensure_ascii=False) + "\n")

    return {"units": len(units), "price_sheets": len(sheets), "gold_items": len(gold)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("../data/synthetic"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(generate(args.out, args.seed)))


if __name__ == "__main__":
    main()
