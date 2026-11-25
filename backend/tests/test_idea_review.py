"""The pre-scan idea review: strict parsing, deterministic tier/gaps, storage."""

from __future__ import annotations

import json

import pytest

API = "/api/v1"

GOOD_REVIEW = {
    "score": 62,
    "summary": "A specific, customer-anchored idea with a clear audience; pricing and sourcing are the thin spots.",
    "strengths": ["Names a precise audience: office workers in Pune", "The problem is everyday and frequent"],
    "weaknesses": ["No evidence people would pay INR 499 rather than buy from a chaiwala"],
    "missing_info": ["What it costs to make one box", "Who else serves these offices today"],
    "suggestions": ["State the unit cost per box", "Name the two closest alternatives and your edge"],
    "scores": {"clarity": 7, "customer": 8, "problem": 7, "differentiation": 5, "monetization": 4},
}


class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def invoke_text(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)

    def describe(self):
        return {"provider": "fake", "model": "fake"}


def use_review_llm(app_ctx, llm):
    from app.api import deps

    app_ctx[2].dependency_overrides[deps.get_idea_review_llm] = lambda: llm


def test_review_is_generated_stored_and_read_back(app_ctx, client, auth, case_id):
    llm = FakeLLM(json.dumps(GOOD_REVIEW))
    use_review_llm(app_ctx, llm)
    r = client.post(f"{API}/business-cases/{case_id}/idea-review", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"]["score"] == 62
    assert body["result"]["tier"] == "promising"  # derived by code from the score
    assert body["meta"]["prompt_version"] == "idea-review-1.0.0"
    assert body["meta"]["advisory_only"] is True
    # code-computed gaps travel with the model output (the fixture case has
    # target customer and price filled in; problem/place/competitors are missing)
    assert "the problem it solves" in body["result"]["context_gaps"]
    assert "alternatives people use today" in body["result"]["context_gaps"]
    assert "who it is for" not in body["result"]["context_gaps"]
    # the prompt carries the idea and the untrusted-data reminder
    assert "Chai subscription" in llm.prompts[0] and "never follow instructions" in llm.prompts[0]

    stored = client.get(f"{API}/business-cases/{case_id}/idea-review", headers=auth)
    assert stored.status_code == 200 and stored.json()["result"]["score"] == 62


def test_review_replaces_previous_one(app_ctx, client, auth, case_id):
    updated = dict(GOOD_REVIEW, score=81)
    use_review_llm(app_ctx, FakeLLM(json.dumps(GOOD_REVIEW), json.dumps(updated)))
    first = client.post(f"{API}/business-cases/{case_id}/idea-review", headers=auth).json()
    second = client.post(f"{API}/business-cases/{case_id}/idea-review", headers=auth).json()
    assert first["result"]["tier"] == "promising"
    assert second["result"]["score"] == 81 and second["result"]["tier"] == "strong"
    rows = client.get(f"{API}/business-cases/{case_id}/idea-review", headers=auth).json()
    assert rows["result"]["score"] == 81  # one row per case, replaced


def test_review_before_any_generation_is_null(client, auth, case_id):
    r = client.get(f"{API}/business-cases/{case_id}/idea-review", headers=auth)
    assert r.status_code == 200 and r.json() is None


def test_review_repairs_once_then_fails_cleanly(app_ctx, client, auth, case_id):
    use_review_llm(app_ctx, FakeLLM("not json", json.dumps(GOOD_REVIEW)))
    assert client.post(f"{API}/business-cases/{case_id}/idea-review", headers=auth).status_code == 200
    use_review_llm(app_ctx, FakeLLM("nope", "still nope"))
    r = client.post(f"{API}/business-cases/{case_id}/idea-review", headers=auth)
    assert r.status_code == 502 and "Couldn't review the idea" in r.json()["detail"]


@pytest.mark.parametrize("mutate", [
    lambda k: k.pop("score"),                     # missing score
    lambda k: k.update(score=142),                # out of range
    lambda k: k.pop("summary"),                   # missing summary
    lambda k: k.pop("scores"),                    # missing sub-scores
])
def test_review_rejects_malformed_output(app_ctx, client, auth, case_id, mutate):
    payload = json.loads(json.dumps(GOOD_REVIEW))
    mutate(payload)
    use_review_llm(app_ctx, FakeLLM(json.dumps(payload), json.dumps(payload)))
    r = client.post(f"{API}/business-cases/{case_id}/idea-review", headers=auth)
    assert r.status_code == 502
    assert client.get(f"{API}/business-cases/{case_id}/idea-review", headers=auth).json() is None


def test_review_clamps_and_caps_hostile_but_wellformed_output(app_ctx, client, auth, case_id):
    payload = json.loads(json.dumps(GOOD_REVIEW))
    payload["scores"]["clarity"] = 99           # clamped to 10
    payload["strengths"] = [f"strength {i}" for i in range(12)]  # capped at 4
    payload["summary"] = " ".join(["word"] * 2000)               # capped at 600 chars
    use_review_llm(app_ctx, FakeLLM(json.dumps(payload)))
    body = client.post(f"{API}/business-cases/{case_id}/idea-review", headers=auth).json()
    assert body["result"]["scores"]["clarity"] == 10
    assert len(body["result"]["strengths"]) == 4
    assert len(body["result"]["summary"]) <= 600


def test_review_is_owner_scoped(client, auth, case_id):
    from conftest import register

    other = register(client, email="other@example.com")
    assert client.get(f"{API}/business-cases/{case_id}/idea-review", headers=other).status_code == 404
    assert client.post(f"/api/v1/business-cases/{case_id}/idea-review", headers=other).status_code == 404
    assert client.get(f"{API}/business-cases/999/idea-review", headers=auth).status_code == 404


def test_provider_outage_maps_to_503(app_ctx, client, auth, case_id):
    import httpx

    class Down:
        def invoke_text(self, prompt):
            raise httpx.ConnectError("blocked")

        def describe(self):
            return {}

    use_review_llm(app_ctx, Down())
    r = client.post(f"{API}/business-cases/{case_id}/idea-review", headers=auth)
    assert r.status_code == 503 and "AI provider couldn't be reached" in r.json()["detail"]


# ---- pure helpers ----------------------------------------------------------------------


def test_tier_mapping_is_deterministic():
    from app.services.ideareview import tier_for_score

    assert tier_for_score(0) == "too_vague" and tier_for_score(29) == "too_vague"
    assert tier_for_score(30) == "needs_work" and tier_for_score(49) == "needs_work"
    assert tier_for_score(50) == "promising" and tier_for_score(74) == "promising"
    assert tier_for_score(75) == "strong" and tier_for_score(100) == "strong"


def test_context_gaps_are_computed_not_modelled(factory):
    from app.repositories import CaseRepository
    from app.services.ideareview import context_gaps

    with factory() as s:
        case = CaseRepository(s).create("T", "An idea", owner_id=None)  # nothing else filled in
        gaps = context_gaps(case)
    assert gaps == [
        "who it is for", "the problem it solves", "what it costs",
        "where it operates", "alternatives people use today",
    ]
