import datetime as dt

import pytest
from conftest import LOCK, future, register, sprint_payload

API = "/api/v1"


def visit(client, slug, vid, channel=None):
    return client.post(f"/public/p/{slug}/visit", json={"vid": vid, "channel": channel})


def signup(client, slug, vid, email, **kw):
    body = {"vid": vid, "email": email, "consent": True, **kw}
    return client.post(f"/public/p/{slug}/signup", json=body)


def fill(client, slug, visitors, signups):
    """visitors unique visitors, of which `signups` sign up."""
    for i in range(visitors):
        vid = f"visitor-{i:04d}-abcdef"
        assert visit(client, slug, vid).status_code == 200
        if i < signups:
            assert signup(client, slug, vid, f"p{i}@example.com").status_code == 200


# ---- drafts and pre-registration ----------------------------------------------------

def test_draft_is_editable_and_not_public(client, auth, draft):
    assert draft["status"] == "draft" and draft["links"]["public_page"] is None
    assert client.get(f"/p/{draft['slug']}").status_code == 404
    assert visit(client, draft["slug"], "visitor-0001-abcdef").status_code == 404
    new = sprint_payload()["content"] | {"headline": "A sharper headline here"}
    r = client.patch(f"{API}/sprints/{draft['id']}", headers=auth, json={"content": new})
    assert r.status_code == 200 and r.json()["content"]["headline"] == "A sharper headline here"


def test_lock_requires_acknowledgements_and_valid_deadline(client, auth, draft, case_id):
    sid = draft["id"]
    assert client.post(f"{API}/sprints/{sid}/lock", headers=auth, json={}).status_code == 400
    assert client.post(f"{API}/sprints/{sid}/lock", headers=auth,
                       json={"acknowledge_public_page": True, "acknowledge_frozen": False}).status_code == 400
    past = sprint_payload()
    past["protocol"]["deadline"] = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    d2 = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=past).json()
    assert client.post(f"{API}/sprints/{d2['id']}/lock", headers=auth, json=LOCK).status_code == 400
    far = sprint_payload()
    far["protocol"]["deadline"] = future(200)
    d3 = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=far).json()
    r = client.post(f"{API}/sprints/{d3['id']}/lock", headers=auth, json=LOCK)
    assert r.status_code == 400 and "90 days" in r.json()["detail"]


def test_lock_freezes_page_and_protocol_and_records_hash(client, auth, draft):
    sid = draft["id"]
    r = client.post(f"{API}/sprints/{sid}/lock", headers=auth, json=LOCK)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "running"
    assert len(body["protocol_hash"]) == 64 and body["locked_at"] and body["links"]["public_page"].endswith(f"/p/{draft['slug']}")
    # frozen
    edit = client.patch(f"{API}/sprints/{sid}", headers=auth, json={"protocol": sprint_payload()["protocol"]})
    assert edit.status_code == 409 and "locked" in edit.json()["detail"].lower()
    assert client.patch(f"{API}/sprints/{sid}", headers=auth, json={"content": sprint_payload()["content"]}).status_code == 409
    assert client.post(f"{API}/sprints/{sid}/lock", headers=auth, json=LOCK).status_code == 409
    # kit (interview scripts etc.) is not part of the registration and stays editable
    assert client.patch(f"{API}/sprints/{sid}", headers=auth, json={"kit": {"interview_script": ["Q1"]}}).status_code == 200
    # hash unchanged by kit edits
    assert client.get(f"{API}/sprints/{sid}", headers=auth).json()["protocol_hash"] == body["protocol_hash"]


def test_hash_is_deterministic_and_sensitive():
    from app.services.sprints import protocol_hash
    p = sprint_payload()
    a = protocol_hash(p["content"], p["protocol"])
    assert a == protocol_hash(dict(reversed(list(p["content"].items()))), p["protocol"])
    p["protocol"]["metrics"][0]["success_rate"] = 0.11
    assert a != protocol_hash(p["content"], p["protocol"])


@pytest.mark.parametrize("mutate,expect", [
    (lambda p: p["protocol"]["metrics"][0].update(failure_rate=0.2), "failure_rate"),
    (lambda p: p["protocol"]["metrics"][0].update(min_sample=5), "min_sample"),
    (lambda p: p["protocol"].update(confidence=0.5), "confidence"),
    (lambda p: p["protocol"].update(metrics=[]), "metrics"),
    (lambda p: p["content"].update(bullets=[]), "bullets"),
    (lambda p: p["content"].update(contact_email="nope"), "email"),
])
def test_invalid_protocols_rejected(client, auth, case_id, mutate, expect):
    p = sprint_payload()
    mutate(p)
    r = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=p)
    assert r.status_code == 422 and expect in r.text


def test_requires_exactly_one_primary_metric(client, auth, case_id):
    p = sprint_payload()
    p["protocol"]["metrics"].append({"key": "interview_commitment", "role": "primary", "success_rate": 0.3,
                                     "failure_rate": 0.1, "min_sample": 5})
    assert client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=p).status_code == 422


# ---- public page ---------------------------------------------------------------------

def test_public_page_renders_escaped_with_csp(client, auth, case_id):
    p = sprint_payload()
    p["content"]["headline"] = "<script>alert(1)</script> Chai"
    d = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=p).json()
    client.post(f"{API}/sprints/{d['id']}/lock", headers=auth, json=LOCK)
    r = client.get(f"/p/{d['slug']}")
    assert r.status_code == 200 and "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text
    csp = r.headers["content-security-policy"]
    assert "script-src 'nonce-" in csp and "frame-ancestors 'none'" in csp
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"' in r.text
    assert "noindex" in r.text and r.headers["cache-control"] == "no-store"
    assert "Nothing is for sale yet" in r.text and "asha@example.com" in r.text  # disclosure + contact


def test_preview_is_owner_only_and_script_free(client, auth, draft):
    r = client.get(f"{API}/sprints/{draft['id']}/preview", headers=auth)
    assert r.status_code == 200 and "<script" not in r.text and "Preview" in r.text
    assert client.get(f"{API}/sprints/{draft['id']}/preview").status_code == 401


def test_visits_are_unique_per_visitor_and_signups_per_email(client, auth, live):
    slug = live["slug"]
    for _ in range(3):
        assert visit(client, slug, "visitor-aaaa-bbbb", channel="Twitter!").status_code == 200
    assert signup(client, slug, "visitor-aaaa-bbbb", "Same@Example.com", channel="Twitter!").status_code == 200
    assert signup(client, slug, "visitor-zzzz-bbbb", "same@example.com").status_code == 200  # duplicate email
    c = client.get(f"{API}/sprints/{live['id']}", headers=auth).json()["evaluation"]["counts"]
    assert c["visitors"] == 2 and c["signups"] == 1
    signups = client.get(f"{API}/sprints/{live['id']}/signups", headers=auth).json()
    assert signups[0]["email"] == "same@example.com" and signups[0]["channel"] == "twitter"


def test_signup_validation_honeypot_and_consent(client, auth, live):
    slug, sid = live["slug"], live["id"]
    assert signup(client, slug, "visitor-1111-2222", "not-an-email").status_code == 400
    assert signup(client, slug, "visitor-1111-2222", "a@example.com", consent=False).status_code == 400
    bot = signup(client, slug, "visitor-3333-4444", "bot@example.com", website="http://spam")
    assert bot.status_code == 200  # looks successful to the bot...
    assert client.get(f"{API}/sprints/{sid}/signups", headers=auth).json() == []  # ...but nothing stored
    assert client.post(f"/public/p/{slug}/signup", json={"vid": "x", "email": "a@example.com"}).status_code == 422


def test_raw_visitor_id_is_never_stored(client, factory, live):
    from sqlalchemy import select
    from app.domain.models import SprintVisit
    visit(client, live["slug"], "my-secret-visitor-id")
    with factory() as s:
        hashed = s.scalar(select(SprintVisit.visitor_hash))
    assert hashed and "my-secret" not in hashed and len(hashed) == 64


def test_paused_and_deadline_stop_collection(client, auth, live, factory):
    slug, sid = live["slug"], live["id"]
    assert client.post(f"{API}/sprints/{sid}/pause", headers=auth).status_code == 200
    assert visit(client, slug, "visitor-pp-0001-x").status_code == 410
    assert "paused" in client.get(f"/p/{slug}").text.lower()
    assert client.post(f"{API}/sprints/{sid}/resume", headers=auth).status_code == 200
    assert visit(client, slug, "visitor-pp-0001-x").status_code == 200
    from app.domain.models import Sprint
    with factory() as s:  # simulate the deadline passing
        sp = s.get(Sprint, sid)
        sp.protocol = {**sp.protocol, "deadline": (dt.date.today() - dt.timedelta(days=1)).isoformat()}
        s.commit()
    assert visit(client, slug, "visitor-pp-0002-x").status_code == 410
    assert signup(client, slug, "visitor-pp-0002-x", "late@example.com").status_code == 410
    assert "ended" in client.get(f"/p/{slug}").text.lower()
    assert client.post(f"{API}/sprints/{sid}/resume", headers=auth).status_code == 409


# ---- verdicts -------------------------------------------------------------------------

def test_verdict_progression_and_conclude(client, auth, live):
    slug, sid = live["slug"], live["id"]
    ev0 = client.get(f"{API}/sprints/{sid}", headers=auth).json()["evaluation"]
    assert ev0["verdict"] == "keep_running" and ev0["metrics"][0]["trials"] == 0
    assert client.post(f"{API}/sprints/{sid}/conclude", headers=auth, json={}).status_code == 409  # not enough data
    fill(client, slug, visitors=60, signups=24)  # 40% observed, n >= min_sample 30
    detail = client.get(f"{API}/sprints/{sid}", headers=auth).json()
    assert detail["evaluation"]["verdict"] == "go"
    assert any("before your deadline" in n for n in detail["evaluation"]["notes"])
    done = client.post(f"{API}/sprints/{sid}/conclude", headers=auth, json={}).json()
    assert done["status"] == "concluded" and done["verdicts"][0]["verdict"] == "go"
    assert done["verdicts"][0]["protocol_hash"] == live["protocol_hash"]
    assert client.post(f"{API}/sprints/{sid}/conclude", headers=auth, json={}).status_code == 409
    assert visit(client, slug, "visitor-late-0001-x").status_code == 410  # data is final
    # the concluded evaluation is a frozen snapshot, not a live recomputation
    assert client.get(f"{API}/sprints/{sid}", headers=auth).json()["evaluation"]["counts"]["visitors"] == 60


def test_stop_verdict(client, auth, live):
    fill(client, live["slug"], visitors=200, signups=1)
    assert client.get(f"{API}/sprints/{live['id']}", headers=auth).json()["evaluation"]["verdict"] == "stop"


def test_force_conclude_is_recorded_as_inconclusive(client, auth, live):
    fill(client, live["slug"], visitors=5, signups=1)
    r = client.post(f"{API}/sprints/{live['id']}/conclude", headers=auth, json={"force": True}).json()
    assert r["verdicts"][0]["verdict"] == "inconclusive" and r["verdicts"][0]["trigger"] == "forced"


def test_interview_metric_and_mixed_signals_downgrade_go(client, auth, case_id):
    p = sprint_payload()
    p["protocol"]["metrics"].append({"key": "interview_commitment", "role": "supporting", "success_rate": 0.4,
                                     "failure_rate": 0.2, "min_sample": 5})
    d = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=p).json()
    client.post(f"{API}/sprints/{d['id']}/lock", headers=auth, json=LOCK)
    fill(client, d["slug"], visitors=60, signups=24)  # primary: go
    for _ in range(40):  # 0 of 40 conversations commit: supporting metric credibly below its floor
        assert client.post(f"{API}/sprints/{d['id']}/signals", headers=auth, json={"outcome": "no"}).status_code == 201
    ev = client.get(f"{API}/sprints/{d['id']}", headers=auth).json()["evaluation"]
    by_key = {m["key"]: m for m in ev["metrics"]}
    assert by_key["waitlist_conversion"]["verdict"] == "go" and by_key["interview_commitment"]["verdict"] == "stop"
    assert ev["verdict"] == "pivot" and any("pivot, not a go" in n for n in ev["notes"])


def test_signals_require_lock_and_exclusions_are_permanent(client, auth, draft, live):
    sid = live["id"]
    sig = client.post(f"{API}/sprints/{sid}/signals", headers=auth, json={"outcome": "committed", "who": "Ravi"}).json()
    assert client.post(f"{API}/sprints/{sid}/signals", headers=auth, json={"outcome": "maybe"}).status_code == 422
    ex = client.post(f"{API}/sprints/{sid}/signals/{sig['id']}/exclude", headers=auth, json={"reason": "Logged twice"})
    assert ex.status_code == 200 and ex.json()["excluded"] is True
    assert client.post(f"{API}/sprints/{sid}/signals/{sig['id']}/exclude", headers=auth, json={"reason": "again"}).status_code == 409
    assert client.post(f"{API}/sprints/{sid}/signals/{sig['id']}/exclude", headers=auth, json={"reason": "x"}).status_code == 422


def test_cannot_log_signals_before_lock(client, auth, draft):
    assert client.post(f"{API}/sprints/{draft['id']}/signals", headers=auth, json={"outcome": "no"}).status_code == 409


def test_excluding_a_signup_changes_counts_and_is_disclosed(client, auth, live):
    slug, sid = live["slug"], live["id"]
    fill(client, slug, visitors=40, signups=3)
    row = client.get(f"{API}/sprints/{sid}/signups", headers=auth).json()[0]
    assert client.post(f"{API}/sprints/{sid}/signups/{row['id']}/exclude", headers=auth, json={"reason": "Obvious fake address"}).status_code == 200
    assert client.get(f"{API}/sprints/{sid}", headers=auth).json()["evaluation"]["counts"]["signups"] == 2
    client.post(f"{API}/sprints/{sid}/dossier", headers=auth, json={"enabled": True})
    token = client.get(f"{API}/sprints/{sid}", headers=auth).json()["links"]["dossier"].rsplit("/", 1)[1]
    page = client.get(f"/d/{token}").text
    assert "Obvious fake address" in page and "p0@example.com" not in page


# ---- dossier ----------------------------------------------------------------------------

def test_dossier_visibility_and_rotation(client, auth, live):
    sid = live["id"]
    token = None
    assert client.get(f"{API}/sprints/{sid}", headers=auth).json()["links"]["dossier"] is None
    on = client.post(f"{API}/sprints/{sid}/dossier", headers=auth, json={"enabled": True}).json()
    token = on["links"]["dossier"].rsplit("/", 1)[1]
    page = client.get(f"/d/{token}")
    assert page.status_code == 200 and live["protocol_hash"] in page.text and "svg" in page.text
    assert "script" not in page.text.lower().replace("noscript", "")
    assert page.headers["content-security-policy"].startswith("default-src 'none'")
    rot = client.post(f"{API}/sprints/{sid}/rotate-dossier-link", headers=auth).json()
    assert client.get(f"/d/{token}").status_code == 404  # old link dead
    assert client.get(rot["links"]["dossier"].replace("http://testserver", "")).status_code == 200
    client.post(f"{API}/sprints/{sid}/dossier", headers=auth, json={"enabled": False})
    assert client.get(f"/d/{token}").status_code == 404


def test_dossier_unavailable_for_drafts(client, auth, draft):
    assert client.post(f"{API}/sprints/{draft['id']}/dossier", headers=auth, json={"enabled": True}).status_code == 409


# ---- data handling ---------------------------------------------------------------------

def test_csv_export_neutralises_formula_injection(client, auth, live):
    slug = live["slug"]
    visit(client, slug, "visitor-csv-0001-x")
    signup(client, slug, "visitor-csv-0001-x", "x@example.com", answer="=HYPERLINK(\"http://evil\")")
    r = client.get(f"{API}/sprints/{live['id']}/signups.csv", headers=auth)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert "'=HYPERLINK" in r.text and "\n=HYPERLINK" not in r.text and ',=HYPERLINK' not in r.text


def test_deleting_a_sprint_removes_collected_data(client, factory, auth, live):
    from sqlalchemy import func, select
    from app.domain.models import SprintSignup, SprintVisit
    fill(client, live["slug"], visitors=5, signups=2)
    assert client.delete(f"{API}/sprints/{live['id']}", headers=auth).status_code == 204
    with factory() as s:
        assert s.scalar(select(func.count(SprintSignup.id))) == 0 and s.scalar(select(func.count(SprintVisit.id))) == 0
    assert client.get(f"/p/{live['slug']}").status_code == 404


def test_plan_preview(client, auth):
    r = client.post(f"{API}/stats/plan", headers=auth, json={"success_rate": 0.1, "confidence": 0.9})
    assert r.status_code == 200 and r.json()["suggested_min_sample"] > 30
    assert client.post(f"{API}/stats/plan", headers=auth, json={"success_rate": 0.1, "confidence": 0.77}).status_code == 400


def test_public_rate_limit_on_signup(client, live, monkeypatch):
    from app.core import ratelimit
    monkeypatch.setenv("BIZAGENT_RATE_LIMIT", "on")
    monkeypatch.setenv("BIZAGENT_SIGNUP_LIMIT", "10")
    ratelimit.reset()
    codes = [signup(client, live["slug"], f"visitor-rl-{i:04d}-x", f"r{i}@example.com").status_code for i in range(14)]
    assert codes[0] == 200 and 429 in codes
    ratelimit.reset()



def test_business_case_can_have_multiple_independent_sprints(client, auth, case_id):
    first_payload = sprint_payload()
    first_payload["content"]["headline"] = "Validate customer demand for chai"
    second_payload = sprint_payload()
    second_payload["content"]["headline"] = "Validate monthly chai pricing"
    first = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=first_payload)
    second = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=second_payload)
    assert first.status_code == 201 and second.status_code == 201
    rows = client.get(f"{API}/business-cases/{case_id}/sprints", headers=auth).json()
    assert {row["id"] for row in rows} >= {first.json()["id"], second.json()["id"]}
    assert first.json()["id"] != second.json()["id"]


def test_idea_specific_public_page_theme_is_validated_and_rendered(client, auth, case_id):
    payload = sprint_payload()
    payload["content"].update({
        "visual_theme": "fresh_green",
        "visual_style": "playful",
        "hero_kicker": "SINGLE-ESTATE CHAI",
    })
    draft = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=payload).json()
    preview = client.get(f"{API}/sprints/{draft['id']}/preview", headers=auth)
    assert preview.status_code == 200
    assert 'class="theme-fresh_green style-playful"' in preview.text
    assert "SINGLE-ESTATE CHAI" in preview.text

    payload["content"]["visual_theme"] = "remote_css_injection"
    rejected = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=payload)
    assert rejected.status_code == 422
