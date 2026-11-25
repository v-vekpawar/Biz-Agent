"""The decision endpoint: deterministic, prioritized founder actions."""

from __future__ import annotations

import pytest
from conftest import LOCK, future, sprint_payload
from test_scan_testkit_brief import install_fakes

API = "/api/v1"


@pytest.fixture()
def scan_client(app_ctx, monkeypatch):
    """Same pattern as test_scan_testkit_brief: a scan executor against fakes."""
    client, factory, app = app_ctx
    from app.api import deps
    from app.services.riskscan import execute_scan

    holder = {}

    def executor_dep():
        return lambda job_id: execute_scan(factory, job_id, holder["deps"])

    app.dependency_overrides[deps.get_scan_executor] = executor_dep
    return client, holder


def run_scan(scan_client, monkeypatch, auth, case_id, **fake_kw):
    client, holder = scan_client
    holder["deps"] = install_fakes(monkeypatch, **fake_kw)
    r = client.post(f"{API}/business-cases/{case_id}/scan", headers=auth)
    assert r.status_code == 202, r.text
    return client.get(f"{API}/business-cases/{case_id}/scan", headers=auth).json()["job"]


def get_decisions(client, auth, case_id):
    r = client.get(f"{API}/business-cases/{case_id}/decision", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def test_decision_for_a_fresh_idea_says_run_the_scan(client, auth, case_id):
    d = get_decisions(client, auth, case_id)
    assert d["verdict"]["key"] == "none" and d["verdict"]["label"] == "NOT ASSESSED"
    assert d["decisions"][0]["priority"] == "now"
    assert d["decisions"][0]["title"] == "Run the risk scan"
    assert d["sprint"] is None and d["evidence"]["total"] == 0
    assert d["risks"] == []


def test_decision_for_a_scanned_idea_points_at_the_top_risk(scan_client, monkeypatch, auth, case_id):
    run_scan(scan_client, monkeypatch, auth, case_id)
    d = get_decisions(scan_client[0], auth, case_id)
    assert d["verdict"]["key"] == "untested"
    first = d["decisions"][0]
    assert first["priority"] == "now" and "Test your riskiest assumption" in first["title"]
    assert "People will pay INR 499 per month" in first["detail"]  # the top, testable risk
    assert any(x["priority"] == "next" for x in d["decisions"])
    assert d["risks"] and d["risks"][0]["level"] == "critical"


def test_decision_for_a_running_test_says_drive_traffic(client, auth, case_id):
    draft = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=sprint_payload()).json()
    client.post(f"{API}/sprints/{draft['id']}/lock", headers=auth, json=LOCK)
    for i in range(20):
        client.post(f"/public/p/{draft['slug']}/visit", json={"vid": f"v-{i:04d}-abcdef"})
    d = get_decisions(client, auth, case_id)
    assert d["sprint"]["evaluation"]["verdict"] == "keep_running"
    first = d["decisions"][0]
    assert first["priority"] == "now" and "Drive about 10 more unique visitors" in first["title"]  # 30 min - 20 seen
    assert any("Log every conversation" in x["title"] for x in d["decisions"])
    assert any(x["priority"] == "later" and "Decision day" in x["title"] for x in d["decisions"])


def test_decision_after_concluded_test_matches_the_verdict(client, auth, case_id):
    draft = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=sprint_payload()).json()
    client.post(f"{API}/sprints/{draft['id']}/lock", headers=auth, json=LOCK)
    slug = draft["slug"]
    for i in range(40):
        client.post(f"/public/p/{slug}/visit", json={"vid": f"v-{i:04d}-abcdef"})
        if i < 30:  # 75% conversion clears a 10% target decisively
            client.post(f"/public/p/{slug}/signup", json={"vid": f"v-{i:04d}-abcdef", "email": f"p{i}@example.com", "consent": True})
    client.post(f"{API}/sprints/{draft['id']}/conclude", headers=auth, json={"force": False})
    d = get_decisions(client, auth, case_id)
    assert d["sprint"]["evaluation"]["verdict"] == "go"
    first = d["decisions"][0]
    assert first["title"] == "Raise the commitment" and first["priority"] == "now"
    assert any("30 people" in x["detail"] for x in d["decisions"])  # signups count feeds the next action
    assert any(x["priority"] == "later" and x["title"] == "Share the evidence" for x in d["decisions"])
    assert d["sprint"]["claim"] == sprint_payload()["protocol"]["claim"]


def test_decision_evidence_counts_are_reported(client, auth, case_id):
    d = get_decisions(client, auth, case_id)
    keys = {"total", "verified", "indeterminate", "unverified", "failed"}
    assert set(d["evidence"].keys()) == keys
    assert sum(v for k, v in d["evidence"].items() if k != "total") == d["evidence"]["total"]


def test_decision_is_owner_scoped(client, auth, case_id):
    from conftest import register

    other = register(client, email="someone-else@example.com")
    assert client.get(f"{API}/business-cases/{case_id}/decision", headers=other).status_code == 404
