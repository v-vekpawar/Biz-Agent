"""Speed work: bounded parallel LLM calls keep byte-identical results, and
provider rate-limit retries fail fast instead of sleeping through backoff."""

from __future__ import annotations

import json
import re
import threading
import time

import pytest
from conftest import register

API = "/api/v1"


# ---- map_bounded (the shared parallel helper) -------------------------------------------


def test_map_bounded_preserves_order_and_returns_errors_in_place():
    from app.services.parallel import map_bounded

    def fn(n):
        if n == 3:
            raise ValueError("boom")
        return n * 10

    out = map_bounded([0, 1, 2, 3, 4], fn)
    assert out[0] == 0 and out[1] == 10 and out[2] == 20 and out[4] == 40
    assert isinstance(out[3], ValueError) and str(out[3]) == "boom"
    assert map_bounded([], fn) == []


def test_map_bounded_actually_runs_in_parallel(monkeypatch):
    from app.services.parallel import map_bounded

    monkeypatch.setenv("BIZAGENT_LLM_CONCURRENCY", "4")
    lock = threading.Lock()
    state = {"active": 0, "max_active": 0}

    def fn(_):
        with lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        time.sleep(0.15)
        with lock:
            state["active"] -= 1
        return "ok"

    started = time.monotonic()
    out = map_bounded(list(range(6)), fn)
    elapsed = time.monotonic() - started
    assert out == ["ok"] * 6
    assert state["max_active"] >= 2  # genuinely concurrent, not sequential
    assert elapsed < 0.9  # 6 * 0.15s sequential would be ~0.9s


def test_map_bounded_runs_inline_when_concurrency_is_one(monkeypatch):
    from app.services.parallel import map_bounded

    monkeypatch.setenv("BIZAGENT_LLM_CONCURRENCY", "1")
    main_thread = threading.current_thread()
    threads = []

    def fn(_):
        threads.append(threading.current_thread())
        return 1

    assert map_bounded([1, 2, 3], fn) == [1, 1, 1]
    assert all(t is main_thread for t in threads)  # exact previous behaviour


def test_concurrency_and_timeout_env_contract(monkeypatch):
    from app.integrations.llm import provider

    monkeypatch.delenv("BIZAGENT_LLM_CONCURRENCY", raising=False)
    monkeypatch.delenv("BIZAGENT_LLM_TIMEOUT_SECONDS", raising=False)
    assert provider.llm_concurrency() == 3
    assert provider.llm_timeout_seconds() == 60.0
    monkeypatch.setenv("BIZAGENT_LLM_CONCURRENCY", "99")
    monkeypatch.setenv("BIZAGENT_LLM_TIMEOUT_SECONDS", "0.1")
    assert provider.llm_concurrency() == 8  # capped
    assert provider.llm_timeout_seconds() == 5.0  # floored
    monkeypatch.setenv("BIZAGENT_LLM_CONCURRENCY", "not-a-number")
    monkeypatch.setenv("BIZAGENT_LLM_TIMEOUT_SECONDS", "not-a-number")
    assert provider.llm_concurrency() == 3
    assert provider.llm_timeout_seconds() == 60.0


# ---- provider invoke_text: fast rate-limit retry ----------------------------------------


class _Reply:
    def __init__(self, content):
        self.content = content


class FlakyModel:
    """Raises the given error N times, then returns a plain reply."""

    def __init__(self, error, times, content="done"):
        self.error, self.times, self.content = error, times, content

    def invoke(self, _messages):
        if self.times > 0:
            self.times -= 1
            raise self.error
        return _Reply(self.content)


def _base_with(model):
    from app.integrations.llm.provider import _BaseChatLLM

    class Stub(_BaseChatLLM):
        provider_name = "stub"
        def _build(self):
            return model

    llm = Stub("stub-model")
    llm._llm = model
    return llm


def test_rate_limit_gets_one_short_retry_then_succeeds(monkeypatch):
    from app.integrations.llm import provider

    sleeps = []
    monkeypatch.setattr(provider.time, "sleep", lambda s: sleeps.append(s))
    model = FlakyModel(RuntimeError("429 quota exceeded - try again in 1.2s"), times=1)
    assert _base_with(model).invoke_text("hello") == "done"
    assert sleeps == [1.2]  # provider-stated wait honoured, single retry


def test_rate_limit_retry_wait_is_capped(monkeypatch):
    from app.integrations.llm import provider

    sleeps = []
    monkeypatch.setattr(provider.time, "sleep", lambda s: sleeps.append(s))
    model = FlakyModel(RuntimeError("429 - please retry after 30 seconds"), times=5)
    with pytest.raises(RuntimeError, match="retry after 30"):
        _base_with(model).invoke_text("hello")
    assert sleeps == [5.0]  # capped: never a 30s stall; chain rotates instead


def test_non_rate_limit_errors_raise_without_retry(monkeypatch):
    from app.integrations.llm import provider

    sleeps = []
    monkeypatch.setattr(provider.time, "sleep", lambda s: sleeps.append(s))
    model = FlakyModel(ValueError("malformed"), times=1)
    with pytest.raises(ValueError, match="malformed"):
        _base_with(model).invoke_text("hello")
    assert sleeps == []


# ---- parallel planning / assessment / verification keep identical results ----------------


PLAN_JSON = json.dumps({
    "evidence_needs": ["prices"], "research_questions": ["what do they pay"],
    "search_queries": ["Q"], "counter_evidence_queries": ["C"],
    "disconfirmation_questions": ["D"],
})

ASSESS_JSON = json.dumps({
    "status": "supported", "rationale": "E1 supports it.",
    "evidence_gaps": None, "limitations": None, "recommended_next_step": "test it",
})

VERDICT_JSON = json.dumps({
    "relationship": "supports", "verification": "verified",
    "relationship_rationale": "page says so", "relevance_assessment": "high",
    "reliability_assessment": "ok", "conflict": {"detected": False, "description": ""},
})


def _seed_case(factory):
    """case + 3 hypotheses; returns (case_id, [(hyp, linked)]) with h3 unlinked."""
    from app.domain.enums import HypothesisCategory
    from app.repositories import CaseRepository, EvidenceRepository, HypothesisRepository

    with factory() as s:
        cases = CaseRepository(s)
        case = cases.create("Speed case", "Idea for tests.", owner_id=None)
        hyps = HypothesisRepository(s)
        h1 = hyps.create(case.id, "People will pay INR 499 per month", category=HypothesisCategory.WILLINGNESS_TO_PAY.value)
        h2 = hyps.create(case.id, "Office workers drink chai daily", category=HypothesisCategory.CUSTOMER_PROBLEM.value)
        h3 = hyps.create(case.id, "An unlinked assumption", category=HypothesisCategory.OTHER.value)
        ev = EvidenceRepository(s)
        e1 = ev.create(case.id, source_title="Pricing survey", source_url="https://a.example.com", excerpt="under 200")
        e2 = ev.create(case.id, source_title="Chai habits", source_url="https://b.example.com", excerpt="daily")
        ev.link(h1.id, e1.id, "neutral", None)
        ev.link(h2.id, e2.id, "neutral", None)
        s.expunge_all()
        return case.id, [(h1.id, e1.id), (h2.id, e2.id), (h3.id, None)]


def test_parallel_planning_keeps_order_and_determinism(factory):
    from app.repositories import EvidenceRepository, HypothesisRepository, RunRepository, UploadRepository
    from app.services.investigation import InvestigationService

    case_id, pairs = _seed_case(factory)
    lock = threading.Lock()
    seen = {"max_active": 0, "active": 0}

    class SlowPlanner:
        def describe(self):
            return {"provider": "stub", "model": "stub"}

        def invoke_text(self, prompt):
            with lock:
                seen["active"] += 1
                seen["max_active"] = max(seen["max_active"], seen["active"])
            time.sleep(0.1)
            with lock:
                seen["active"] -= 1
            statement = re.search(r"HYPOTHESIS \([a-z_]+\): (.+)", prompt).group(1)
            payload = json.loads(PLAN_JSON)
            payload["search_queries"] = [f"query for: {statement[:30]}"]
            return json.dumps(payload)

    with factory() as s:
        service = InvestigationService(
            planner_llm=SlowPlanner(), search_provider=None,
            hypotheses=HypothesisRepository(s), evidence=EvidenceRepository(s),
            runs=RunRepository(s), uploads=UploadRepository(s),
        )
        from app.repositories import CaseRepository
        case = CaseRepository(s).get(case_id)
        result = service.investigate_case(case, [h for h, _e in pairs])

    assert [p.hypothesis_id for p in result["plans"]] == [h for h, _e in pairs]
    # Each plan carries its own hypothesis's query, in order (no cross-talk).
    assert [p.search_queries[0] for p in result["plans"]] == [
        "query for: People will pay INR 499 per mo",
        "query for: Office workers drink chai dail",
        "query for: An unlinked assumption",
    ]
    assert seen["max_active"] >= 2  # planning really ran concurrently
    assert result["gaps"], "no search provider is an explicit gap, never silent"


def test_parallel_assessment_writes_identical_versions(factory):
    from app.repositories import AssessmentRepository, CaseRepository, EvidenceRepository, ExperimentRepository, HypothesisRepository, RunRepository
    from app.services.assessment import AssessmentService

    case_id, pairs = _seed_case(factory)

    class StubAssessor:
        def __init__(self):
            self.calls = 0

        def describe(self):
            return {"provider": "stub", "model": "stub"}

        def invoke_text(self, prompt):
            self.calls += 1
            payload = json.loads(ASSESS_JSON)
            if "Office workers drink chai" in prompt:
                payload["status"] = "contradicted"
            return json.dumps(payload)

    stub = StubAssessor()
    with factory() as s:
        service = AssessmentService(
            assessor_llm=stub, evidence=EvidenceRepository(s), hypotheses=HypothesisRepository(s),
            assessments=AssessmentRepository(s), cases=CaseRepository(s), runs=None,
            experiments=ExperimentRepository(s),
        )
        out = service.assess_case(CaseRepository(s).get(case_id))

    # Two hypotheses had linked evidence (LLM called); the unlinked one got the
    # deterministic unknown WITHOUT any LLM call.
    assert stub.calls == 2
    by_hyp = {r["hypothesis_id"]: r for r in out["results"]}
    assert by_hyp[pairs[0][0]]["assessment"].status.value == "supported"
    assert by_hyp[pairs[1][0]]["assessment"].status.value == "contradicted"
    assert by_hyp[pairs[2][0]]["assessment"].status.value == "unknown"
    assert "No linked evidence" in by_hyp[pairs[2][0]]["assessment"].rationale
    assert out["summary"]["supported"] == 1 and out["summary"]["contradicted"] == 1


def test_parallel_verification_verifies_every_row_in_order(factory):
    from app.domain.enums import VerificationStatus
    from app.repositories import AssessmentRepository, CaseRepository, EvidenceRepository, HypothesisRepository, RunRepository
    from app.services.verification import VerificationService

    case_id, pairs = _seed_case(factory)

    class StubFetcher:
        provider_name = "stub-fetch"

        def fetch(self, url):
            return f"content of {url}"

    class StubVerifier:
        def describe(self):
            return {"provider": "stub", "model": "stub"}

        def invoke_text(self, prompt):
            return VERDICT_JSON

    with factory() as s:
        # Mark the first row already verified: it must be skipped, not re-spent.
        evidence = EvidenceRepository(s)
        first_row = evidence.get(pairs[0][1])
        evidence.update(first_row.id, {"verification_status": VerificationStatus.VERIFIED.value})
        service = VerificationService(
            verifier_llm=StubVerifier(), fetcher=StubFetcher(), evidence=evidence,
            hypotheses=HypothesisRepository(s), cases=CaseRepository(s), runs=None,
        )
        out = service.verify_case(CaseRepository(s).get(case_id))

    assert out["summary"]["verified"] == 1  # only the second row needed a pass
    assert {s["reason"] for s in out["skipped"] if s["evidence_id"] == pairs[0][1]} == {
        "already verified — retained prior successful check"
    }
    with factory() as s:
        evidence = EvidenceRepository(s)
        row = evidence.get(pairs[1][1])
        assert row.verification_status.value == "verified"
        link = evidence.links_for_evidence(row.id)[0][1]
        assert link.relationship.value == "supports"  # classification applied
