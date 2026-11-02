from fastapi.testclient import TestClient

from aios.entrypoints.api import create_app

client = TestClient(create_app())


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_installments_endpoint_returns_exact_money_strings() -> None:
    r = client.post(
        "/pricing/installments",
        json={
            "list_price": "4500000",
            "down_payment_pct": "10",
            "years": 8,
            "frequency": "quarterly",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["installment_count"] == 32
    assert body["regular_installment"] == "126562.50"
    assert body["total_paid"] == "4500000.00"


def test_mortgage_endpoint() -> None:
    r = client.post(
        "/pricing/mortgage",
        json={
            "property_price": "1250000",
            "down_payment_pct": "20",
            "annual_rate_pct": "12",
            "years": 10,
        },
    )
    assert r.status_code == 200
    assert r.json()["monthly_payment"] == "14347.09"


def test_domain_invariant_violation_maps_to_422() -> None:
    r = client.post(
        "/pricing/installments",
        json={
            "list_price": "1000000",
            "down_payment_pct": "60",
            "delivery_payment_pct": "50",
            "years": 5,
        },
    )
    assert r.status_code == 422
    assert r.json()["code"] == "invalid_input"


def test_unknown_fields_rejected() -> None:
    r = client.post(
        "/pricing/mortgage",
        json={
            "property_price": "1000000",
            "down_payment_pct": "20",
            "annual_rate_pct": "10",
            "years": 10,
            "role": "manager",
        },
    )
    assert r.status_code == 422
