"""Shared fixtures: isolated SQLite per test, migrated with Alembic (so the
migration chain itself is under test), stubbed scan executor, rate limit off."""

from __future__ import annotations

import datetime as dt
import os

import pytest

os.environ.setdefault("BIZAGENT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ["BIZAGENT_RATE_LIMIT"] = "off"
os.environ["BIZAGENT_AUTO_MIGRATE"] = "0"


@pytest.fixture()
def app_ctx(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import deps
    from app.core import ratelimit
    from app.db.migrate import upgrade_to_head
    from app.db.session import make_engine, make_session_factory
    from app.main import app

    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    upgrade_to_head(url)
    engine = make_engine(url)
    factory = make_session_factory(engine)
    monkeypatch.setattr(deps, "_session_factory", factory)
    monkeypatch.setenv("BIZAGENT_UPLOADS_DIR", str(tmp_path / "uploads"))
    ratelimit.reset()
    client = TestClient(app)
    yield client, factory, app
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture()
def client(app_ctx):
    return app_ctx[0]


@pytest.fixture()
def factory(app_ctx):
    return app_ctx[1]


def register(client, email="asha@example.com", name="Asha", password="correct-horse-1"):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password, "display_name": name})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def auth(client):
    return register(client)


@pytest.fixture()
def case_id(client, auth):
    r = client.post("/api/v1/business-cases", headers=auth, json={
        "title": "Chai subscription", "idea_description": "Monthly small-batch chai for office workers in Pune.",
        "target_customer": "Office workers in Pune", "pricing_model": "INR 499 per month"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def future(days=30):
    return (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=days)).isoformat()


def sprint_payload(**over):
    payload = {
        "content": {
            "headline": "Fresh small-batch chai at your desk", "subheadline": "A box every month.",
            "bullets": ["Six blends", "Cancel any time"], "cta_label": "Join the waitlist",
            "extra_question": "What do you drink at work today?", "price_hint": "INR 499/month",
            "creator_name": "Asha", "contact_email": "asha@example.com",
        },
        "protocol": {
            "claim": "At least 10% of Pune office workers who see this page will join the waitlist.",
            "audience": "Office workers in Pune", "confidence": 0.9, "deadline": future(),
            "metrics": [{"key": "waitlist_conversion", "role": "primary", "success_rate": 0.10,
                         "failure_rate": 0.03, "min_sample": 30}],
        },
    }
    payload.update(over)
    return payload


@pytest.fixture()
def draft(client, auth, case_id):
    r = client.post(f"/api/v1/business-cases/{case_id}/sprints", headers=auth, json=sprint_payload())
    assert r.status_code == 201, r.text
    return r.json()


LOCK = {"acknowledge_public_page": True, "acknowledge_frozen": True}


@pytest.fixture()
def live(client, auth, draft):
    r = client.post(f"/api/v1/sprints/{draft['id']}/lock", headers=auth, json=LOCK)
    assert r.status_code == 200, r.text
    return r.json()
