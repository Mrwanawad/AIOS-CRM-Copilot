from decimal import Decimal

import pytest

from aios.modules.pricing.domain.models import (
    InstallmentPlanRequest,
    MortgageRequest,
    PaymentFrequency,
)
from aios.modules.pricing.domain.services import (
    calculate_installment_plan,
    calculate_mortgage,
    evaluate_discount,
)
from aios.shared.errors import InvalidInputError
from aios.shared.security import Role

D = Decimal
LIMITS = {Role.REP: D("2"), Role.TEAM_LEAD: D("5"), Role.MANAGER: D("10")}


class TestInstallmentPlan:
    def test_typical_quarterly_plan(self) -> None:
        s = calculate_installment_plan(
            InstallmentPlanRequest(
                list_price=D("4500000"),
                down_payment_pct=D("10"),
                years=8,
                frequency=PaymentFrequency.QUARTERLY,
            )
        )
        assert s.down_payment == D("450000.00")
        assert s.installment_count == 32
        assert s.regular_installment == D("126562.50")
        assert s.total_paid == D("4500000")

    def test_rounding_residue_goes_to_last_installment(self) -> None:
        s = calculate_installment_plan(
            InstallmentPlanRequest(
                list_price=D("1000000"),
                down_payment_pct=D("0"),
                years=1,
                frequency=PaymentFrequency.MONTHLY,
            )
        )
        assert s.regular_installment == D("83333.33")
        assert s.installments[-1].amount == D("83333.37")
        assert s.total_paid == D("1000000")

    def test_discount_and_delivery_payment_apply_to_net_price(self) -> None:
        s = calculate_installment_plan(
            InstallmentPlanRequest(
                list_price=D("2000000"),
                down_payment_pct=D("5"),
                delivery_payment_pct=D("10"),
                discount_pct=D("3"),
                years=5,
                frequency=PaymentFrequency.SEMI_ANNUAL,
            )
        )
        assert s.discount_amount == D("60000.00")
        assert s.net_price == D("1940000.00")
        assert s.down_payment == D("97000.00")
        assert s.delivery_payment == D("194000.00")
        assert s.installment_count == 10
        assert s.total_paid == s.net_price

    def test_cash_deal_has_no_installments(self) -> None:
        s = calculate_installment_plan(
            InstallmentPlanRequest(
                list_price=D("3000000"),
                down_payment_pct=D("100"),
                years=0,
                frequency=PaymentFrequency.MONTHLY,
            )
        )
        assert s.installments == ()
        assert s.total_paid == D("3000000")

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("list_price", D("0")),
            ("down_payment_pct", D("101")),
            ("years", 16),
            ("discount_pct", D("-1")),
        ],
    )
    def test_rejects_invalid_input(self, field: str, value: object) -> None:
        kwargs: dict[str, object] = {
            "list_price": D("1000000"),
            "down_payment_pct": D("10"),
            "years": 5,
            "frequency": PaymentFrequency.MONTHLY,
            field: value,
        }
        with pytest.raises(InvalidInputError):
            InstallmentPlanRequest(**kwargs)  # type: ignore[arg-type]

    def test_rejects_zero_years_with_remaining_balance(self) -> None:
        with pytest.raises(InvalidInputError):
            InstallmentPlanRequest(
                list_price=D("1000000"),
                down_payment_pct=D("10"),
                years=0,
                frequency=PaymentFrequency.MONTHLY,
            )


class TestMortgage:
    def test_matches_standard_annuity_formula(self) -> None:
        q = calculate_mortgage(
            MortgageRequest(
                property_price=D("1250000"),
                down_payment_pct=D("20"),
                annual_rate_pct=D("12"),
                years=10,
            )
        )
        assert q.financed_amount == D("1000000.00")
        assert q.months == 120
        assert q.monthly_payment == D("14347.09")
        assert q.total_interest == q.monthly_payment * 120 - D("1000000")

    def test_zero_rate_is_straight_division(self) -> None:
        q = calculate_mortgage(
            MortgageRequest(
                property_price=D("1200000"),
                down_payment_pct=D("0"),
                annual_rate_pct=D("0"),
                years=10,
            )
        )
        assert q.monthly_payment == D("10000.00")
        assert q.total_interest == D("0")

    def test_rejects_full_down_payment(self) -> None:
        with pytest.raises(InvalidInputError):
            MortgageRequest(
                property_price=D("1000000"),
                down_payment_pct=D("100"),
                annual_rate_pct=D("10"),
                years=10,
            )


class TestDiscountPolicy:
    def test_within_role_limit_is_approved(self) -> None:
        d = evaluate_discount(D("2"), Role.REP, LIMITS)
        assert d.approved
        assert d.escalate_to is None

    def test_escalates_to_lowest_sufficient_role(self) -> None:
        d = evaluate_discount(D("4"), Role.REP, LIMITS)
        assert not d.approved
        assert d.escalate_to is Role.TEAM_LEAD

    def test_skips_roles_whose_limit_is_too_low(self) -> None:
        d = evaluate_discount(D("8"), Role.REP, LIMITS)
        assert d.escalate_to is Role.MANAGER

    def test_above_all_limits_goes_to_top_role(self) -> None:
        d = evaluate_discount(D("15"), Role.MANAGER, LIMITS)
        assert not d.approved
        assert d.escalate_to is Role.MANAGER

    def test_rejects_out_of_range(self) -> None:
        with pytest.raises(InvalidInputError):
            evaluate_discount(D("120"), Role.REP, LIMITS)
