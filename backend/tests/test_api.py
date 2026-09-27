import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import acc, cat
from tests.test_imports import ABN_MT940


@pytest.fixture()
def client(db, user):
    return TestClient(create_app())


def login(client) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": "dima@example.com", "password": "correct horse battery"})
    assert r.status_code == 200, r.text
    assert "budget_refresh" in r.cookies
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_auth_required_and_problem_json(client):
    r = client.get("/api/v1/accounts")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "unauthenticated"


def test_wrong_password(client):
    r = client.post("/api/v1/auth/login", json={"email": "dima@example.com", "password": "nope-nope-nope"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"


def test_refresh_rotates_cookie(client):
    login(client)
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 200 and r.json()["access_token"]


def test_end_to_end_txn_and_reports(client, db):
    h = login(client)
    accounts = client.get("/api/v1/accounts", headers=h).json()
    assert {a["name"] for a in accounts} >= {"ABN", "Sparen ABN", "Sparen Bunq", "Rubles", "Cash", "Credit card", "ABN Invest"}
    body = {"date": "2026-03-10", "kind": "expense", "description": "AH",
            "legs": [{"account_id": acc(db, "ABN").id, "amount": -4520}],
            "splits": [{"amount": -4520, "category_id": cat(db, "Eetwaar").id}]}
    r = client.post("/api/v1/txns", json=body, headers={**h, "Idempotency-Key": "k1"})
    assert r.status_code == 201, r.text
    again = client.post("/api/v1/txns", json=body, headers={**h, "Idempotency-Key": "k1"})
    assert again.json()["id"] == r.json()["id"]
    page = client.get("/api/v1/txns", params={"text": "ah"}, headers=h).json()
    assert len(page["items"]) == 1 and page["totals"] == {"EUR": -4520}
    bad = client.post("/api/v1/txns", json={**body, "splits": [{"amount": -1, "category_id": cat(db, "Eetwaar").id}]}, headers=h)
    assert bad.status_code == 422 and bad.json()["code"] == "split_sum"
    for url in ("/api/v1/reports/month/2026-03", "/api/v1/reports/year/2026", "/api/v1/reports/balances",
                "/api/v1/reports/budget/2026-03", "/api/v1/reports/debts",
                "/api/v1/reports/net-worth?start=2026-01-01&end=2026-03-31",
                "/api/v1/reports/net-worth-bridge?start=2026-03-01&end=2026-03-31",
                "/api/v1/categories", "/api/v1/debts", "/api/v1/assets", "/api/v1/earmarks", "/api/v1/projects",
                "/api/v1/settings", "/api/v1/imports", "/api/v1/import-rules", "/api/v1/investments/holdings",
                "/api/v1/export/txns.csv"):
        resp = client.get(url, headers=h)
        assert resp.status_code == 200, (url, resp.text)
    month = client.get("/api/v1/reports/month/2026-03", headers=h).json()
    assert month["summary_ref"]["expenses"] == -4520


def test_upload_and_review_via_api(client):
    h = login(client)
    r = client.post("/api/v1/imports", files={"file": ("abn.sta", ABN_MT940)}, headers=h)
    assert r.status_code == 201, r.text
    batch = r.json()
    assert batch["source"] == "abn_mt940" and batch["status"] == "reviewing"
    rows = client.get(f"/api/v1/imports/{batch['id']}/rows", headers=h).json()
    assert len(rows) == 4
    dup = client.post("/api/v1/imports", files={"file": ("abn.sta", ABN_MT940)}, headers=h)
    assert dup.status_code == 409
    ai = client.post(f"/api/v1/imports/{batch['id']}/suggest", json={}, headers=h)
    assert ai.status_code in (200, 503)  # 503 when no API key is configured


def test_openapi_schema(client):
    spec = client.get("/api/v1/openapi.json").json()
    assert "/api/v1/txns" in spec["paths"]
