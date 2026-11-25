"""Multi-question test pages: builder validation, collection, results, legacy compat."""

from __future__ import annotations

import csv
import io

from conftest import LOCK, future, sprint_payload

API = "/api/v1"

QUESTIONS_PAYLOAD = {
    "content": {
        "headline": "Fresh small-batch chai at your desk", "subheadline": "A box every month.",
        "bullets": ["Six blends", "Cancel any time"], "cta_label": "Join the waitlist",
        "questions": [
            {"id": "q1", "label": "What do you drink at work today?", "type": "single_choice",
             "options": ["Office chaiwala", "Instant coffee", "Tea bags", "Nothing"]},
            {"id": "q2", "label": "How much would you pay per month?", "type": "short_text"},
            {"id": "q3", "label": "Anything you wish existed?", "type": "long_text"},
        ],
        "creator_name": "Asha", "contact_email": "asha@example.com",
    },
    "protocol": {
        "claim": "At least 10% of Pune office workers who see this page will join the waitlist.",
        "audience": "Office workers in Pune", "confidence": 0.9, "deadline": future(),
        "metrics": [{"key": "waitlist_conversion", "role": "primary", "success_rate": 0.10,
                     "failure_rate": 0.03, "min_sample": 30}],
    },
}


def locked_multi_page(client, auth, case_id, payload=QUESTIONS_PAYLOAD):
    draft = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=payload).json()
    locked = client.post(f"{API}/sprints/{draft['id']}/lock", headers=auth, json=LOCK)
    assert locked.status_code == 200, locked.text
    return locked.json()


def test_page_with_multiple_questions_collects_structured_answers(client, auth, case_id):
    live = locked_multi_page(client, auth, case_id)
    slug = live["slug"]
    r = client.post(f"/public/p/{slug}/signup", json={
        "vid": "visitor-0001-abcdef", "email": "ravi@example.com", "consent": True,
        "answers": {"q1": "Office chaiwala", "q2": "INR 300", "q3": "Decaf options would be great"},
    })
    assert r.status_code == 200, r.text
    r = client.post(f"/public/p/{slug}/signup", json={
        "vid": "visitor-0002-abcdef", "email": "meera@example.com", "consent": True,
        "answers": {"q1": "Instant coffee", "q3": "Weekend delivery"},  # q2 skipped: optional
    })
    assert r.status_code == 200, r.text
    rows = client.get(f"{API}/sprints/{live['id']}/signups", headers=auth).json()
    by_email = {row["email"]: row for row in rows}
    assert by_email["ravi@example.com"]["answers"] == {
        "q1": "Office chaiwala", "q2": "INR 300", "q3": "Decaf options would be great"}
    assert by_email["meera@example.com"]["answers"] == {"q1": "Instant coffee", "q3": "Weekend delivery"}
    assert by_email["ravi@example.com"]["answer"] is None  # structured pages do not use the legacy column


def test_choice_answers_must_match_frozen_options(client, auth, case_id):
    live = locked_multi_page(client, auth, case_id)
    r = client.post(f"/public/p/{live['slug']}/signup", json={
        "vid": "visitor-0003-abcdef", "email": "x@example.com", "consent": True,
        "answers": {"q1": "Something the page never offered"},
    })
    assert r.status_code == 400 and "Pick one of the listed options" in r.json()["detail"]
    # unknown keys are dropped, known ones kept: nothing gained by tampering
    r = client.post(f"/public/p/{live['slug']}/signup", json={
        "vid": "visitor-0004-abcdef", "email": "y@example.com", "consent": True,
        "answers": {"q1": "Tea bags", "hacker": "<script>"},
    })
    assert r.status_code == 200
    row = [s for s in client.get(f"{API}/sprints/{live['id']}/signups", headers=auth).json()
           if s["email"] == "y@example.com"][0]
    assert row["answers"] == {"q1": "Tea bags"}


def test_public_page_renders_each_question_with_the_right_control(client, auth, case_id):
    live = locked_multi_page(client, auth, case_id)
    html = client.get(f"/p/{live['slug']}").text
    assert html.count('name="q_') == 4 + 1 + 1  # 4 radios (one question), one text input, one textarea
    assert 'role="radiogroup"' in html and "Office chaiwala" in html
    assert 'name="q_q2"' in html and 'name="q_q3"' in html
    assert "your answers to the questions above" in html  # honest disclosure
    assert "<script" in html  # the collecting script is still there, nonce-protected
    # the new design language is present
    assert "Join the waitlist" in html and 'class="choice"' in html


def test_preview_renders_questions_disabled(client, auth, case_id):
    draft = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=QUESTIONS_PAYLOAD).json()
    html = client.get(f"{API}/sprints/{draft['id']}/preview", headers=auth).text
    assert html.count("disabled") >= 3 + 4 and "Preview" in html


def test_legacy_single_question_pages_keep_working(client, auth, case_id):
    """Pages built before structured questions: old payloads validate, render
    and store answers exactly as they did."""
    draft = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=sprint_payload()).json()
    locked = client.post(f"{API}/sprints/{draft['id']}/lock", headers=auth, json=LOCK).json()
    html = client.get(f"/p/{draft['slug']}").text
    assert 'name="q_legacy"' in html and "What do you drink at work today?" in html
    r = client.post(f"/public/p/{draft['slug']}/signup", json={
        "vid": "visitor-0009-abcdef", "email": "old@example.com", "consent": True,
        "answers": {"legacy": "Mostly instant coffee"},
    })
    assert r.status_code == 200
    row = client.get(f"{API}/sprints/{draft['id']}/signups", headers=auth).json()[0]
    assert row["answer"] == "Mostly instant coffee" and row["answers"] is None


def test_question_schema_rules(client, auth, case_id):
    base = QUESTIONS_PAYLOAD

    def attempt(mutate):
        payload = {**base, "content": {**base["content"], "questions": mutate}}
        r = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=payload)
        return r.status_code

    assert attempt([{"id": "q1", "label": "Valid text question", "type": "short_text"}]) == 201
    assert attempt([{"id": "q1", "label": "Choice without options", "type": "single_choice"}]) == 422
    assert attempt([{"id": "q1", "label": "Only one option", "type": "single_choice", "options": ["A"]}]) == 422
    assert attempt([{"id": "q1", "label": "Text with options", "type": "short_text", "options": ["A"]}]) == 422
    assert attempt([{"id": "q1", "label": "A"}, {"id": "q1", "label": "Duplicate id"}]) == 422
    assert attempt([{"id": f"q{i}", "label": f"Question {i}"} for i in range(1, 5)]) == 422  # max 3
    assert attempt([{"id": "Q1", "label": "Uppercase coerces fine"}]) == 201  # id is normalized


def test_csv_export_has_one_column_per_question(client, auth, case_id):
    live = locked_multi_page(client, auth, case_id)
    client.post(f"/public/p/{live['slug']}/signup", json={
        "vid": "visitor-0005-abcdef", "email": "a@example.com", "consent": True,
        "answers": {"q1": "Tea bags", "q2": "INR 250"}})
    body = client.get(f"{API}/sprints/{live['id']}/signups.csv", headers=auth).text
    rows = list(csv.reader(io.StringIO(body)))
    assert rows[0][:4] == ["email", "answer: What do you drink at work today?",
                           "answer: How much would you pay per month?", "answer: Anything you wish existed?"]
    assert rows[1][1] == "Tea bags" and rows[1][2] == "INR 250" and rows[1][3] == ""


def test_ai_test_kit_proposes_structured_questions(app_ctx, client, auth, case_id):
    import json

    from test_scan_testkit_brief import GOOD_KIT, use_llm

    kit = json.loads(json.dumps(GOOD_KIT))
    kit["page"]["questions"] = [
        {"id": "q1", "label": "What do you drink at work today?", "type": "single_choice",
         "options": ["Chaiwala", "Coffee", "Nothing"]},
        {"id": "q2", "label": "How many days a week are you at the office?", "type": "short_text"},
    ]
    use_llm(app_ctx, __import__("test_scan_testkit_brief").FakeLLM(json.dumps(kit)))
    d = client.post(f"{API}/business-cases/{case_id}/sprints/ai-draft", headers=auth, json={}).json()
    assert d["content"]["questions"][0]["type"] == "single_choice"
    assert d["content"]["questions"][0]["options"] == ["Chaiwala", "Coffee", "Nothing"]
    assert d["content"]["questions"][1]["type"] == "short_text"

    # Legacy model output (extra_question string) still becomes a usable page.
    use_llm(app_ctx, __import__("test_scan_testkit_brief").FakeLLM(json.dumps(GOOD_KIT)))
    d2 = client.post(f"{API}/business-cases/{case_id}/sprints/ai-draft", headers=auth, json={}).json()
    assert d2["content"]["questions"] == [
        {"id": "q1", "label": "What do you drink at work today?", "type": "long_text", "options": []}]


def test_page_questions_are_frozen_into_the_protocol_hash(client, auth, case_id):
    live = locked_multi_page(client, auth, case_id)
    import hashlib, json as jsonlib

    canonical = jsonlib.dumps({"content": live["content"], "protocol": live["protocol"]},
                              sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert live["protocol_hash"] == hashlib.sha256(canonical.encode()).hexdigest()
