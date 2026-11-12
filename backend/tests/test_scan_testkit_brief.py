"""Scan job orchestration, AI test-kit generation, and the decision-brief PDF."""

import json
from types import SimpleNamespace

import pytest
from conftest import LOCK, future, register, sprint_payload

API = "/api/v1"


# ---- fakes for the research engine -----------------------------------------------------

def install_fakes(monkeypatch, *, search=True, fetch=True, fail_assess=False, fail_extract=False):
    """Replace the four heavy services with fakes that write real rows through the repos."""
    from app.repositories import AssessmentRepository, EvidenceRepository
    from app.services import riskscan
    from app.services.assessment import AssessmentError
    from app.services.extraction import ExtractionError

    STATEMENTS = [
        ("People will pay INR 499 per month", "willingness_to_pay", "high", "contradicted"),
        ("Office workers drink chai daily at their desk", "customer_problem", "high", "unknown"),
        ("We can source small-batch chai at 40% margin", "unit_economics", "medium", "weakly_supported"),
        ("Couriers can deliver within 3 days in Pune", "operations", "low", "supported"),
    ]

    class FakeExtraction:
        def __init__(self, llm): ...
        def extract(self, case, existing):
            if fail_extract:
                raise ExtractionError("model returned garbage")
            cands = [dict(statement=s, category=c, rationale="r", customer_segment=None, geography=None,
                          priority=p, testability_notes="t") for s, c, p, _ in STATEMENTS]
            return SimpleNamespace(hypotheses=cands), {"provider": "fake", "model": "fake", "prompt_version": "x"}

    class FakeInvestigation:
        def __init__(self, *, hypotheses, evidence, runs, **kw):
            self.h, self.e, self.runs = hypotheses, evidence, runs
        def investigate_case(self, case, ids):
            run = self.runs.create(case.id)
            self.runs.start(run.id)
            created = []
            for h in self.h.list_by_case(case.id):
                if h.statement.startswith("People will pay"):
                    ev = self.e.create(case.id, "Survey: Pune chai prices", source_url="https://example.com/s",
                                       finding="Most respondents want it under INR 200")
                    self.e.link(h.id, ev.id, "contradicts", "price too high")
                    created.append(ev)
            self.runs.complete(run.id) if hasattr(self.runs, "complete") else None
            return {"run": run, "plans": [], "created": created, "reused": [], "links": len(created),
                    "gaps": [] if search else ["Web search isn't configured"]}

    class FakeVerification:
        def __init__(self, **kw): ...
        def verify_case(self, case, ids, *, run_id=None):
            return {"results": [], "skipped": [], "summary": {"verified": 0, "indeterminate": 0, "failed": 0, "conflicts": 0}}

    class FakeAssessment:
        def __init__(self, *, hypotheses, assessments, **kw):
            self.h, self.a = hypotheses, assessments
        def assess_case(self, case, ids, *, run_id=None):
            if fail_assess:
                raise AssessmentError("assessor output unusable")
            by_stmt = {s: st for s, _, _, st in STATEMENTS}
            for h in self.h.list_by_case(case.id):
                self.a.add(h.id, by_stmt[h.statement], "Because of the evidence.", investigation_run_id=run_id,
                           recommended_next_step="Test with customers")
            return {"results": [], "summary": {}}

    monkeypatch.setattr(riskscan, "HypothesisExtractionService", FakeExtraction)
    monkeypatch.setattr(riskscan, "InvestigationService", FakeInvestigation)
    monkeypatch.setattr(riskscan, "VerificationService", FakeVerification)
    monkeypatch.setattr(riskscan, "AssessmentService", FakeAssessment)
    return riskscan.ScanDeps(extractor=None, planner=None, verifier=None, assessor=None,
                             search_provider=object() if search else None, fetcher=object() if fetch else None)


@pytest.fixture()
def scan_client(app_ctx, monkeypatch):
    """Client whose scan executor runs against the fakes (set per test via `holder`)."""
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


def test_scan_completes_and_ranks_risks(scan_client, monkeypatch, auth, case_id):
    job = run_scan(scan_client, monkeypatch, auth, case_id)
    assert job["status"] == "completed" and job["progress"] == 100 and job["error"] is None
    client = scan_client[0]
    risks = client.get(f"{API}/business-cases/{case_id}/risks", headers=auth).json()
    order = [r["status"] for r in risks["risks"]]
    assert order == ["contradicted", "unknown", "weakly_supported", "supported"]
    assert [r["level"] for r in risks["risks"]] == ["critical", "open", "thin", "low"]
    top = risks["risks"][0]
    assert top["evidence"]["contradicts"] == 1 and "points against" in top["headline"] and top["rank"] == 1
    assert risks["recommended_hypothesis_id"] == top["hypothesis_id"]  # willingness_to_pay is sprint-testable
    ov = client.get(f"{API}/business-cases/{case_id}/overview", headers=auth).json()
    assert ov["stage"] == "scanned" and ov["assumption_count"] == 4


def test_recommendation_skips_untestable_categories(scan_client, monkeypatch, auth, case_id):
    from app.services.riskscan import recommended_hypothesis_id
    risks = [{"hypothesis_id": 1, "sprint_testable": False, "level": "critical"},
             {"hypothesis_id": 2, "sprint_testable": True, "level": "open"},
             {"hypothesis_id": 3, "sprint_testable": True, "level": "low"}]
    assert recommended_hypothesis_id(risks) == 2
    assert recommended_hypothesis_id([{"hypothesis_id": 9, "sprint_testable": True, "level": "low"}]) == 9
    assert recommended_hypothesis_id([]) is None


def test_missing_search_and_fetch_are_warnings_not_failures(scan_client, monkeypatch, auth, case_id):
    job = run_scan(scan_client, monkeypatch, auth, case_id, search=False, fetch=False)
    assert job["status"] == "completed"
    joined = " ".join(job["warnings"])
    assert "Web search isn't configured" in joined and "Source fetching isn't configured" in joined


@pytest.mark.parametrize("kw,expected", [({"fail_extract": True}, "Couldn't extract"), ({"fail_assess": True}, "Couldn't weigh")])
def test_fatal_failures_fail_the_job_with_a_clear_message(scan_client, monkeypatch, auth, case_id, kw, expected):
    job = run_scan(scan_client, monkeypatch, auth, case_id, **kw)
    assert job["status"] == "failed" and expected in job["error"]
    assert scan_client[0].get(f"{API}/business-cases/{case_id}/overview", headers=auth).json()["stage"] == "idea"


def test_unexpected_crash_is_contained(scan_client, monkeypatch, auth, case_id):
    client, holder = scan_client
    holder["deps"] = install_fakes(monkeypatch)
    from app.services import riskscan

    class Boom:
        def __init__(self, **kw): ...
        def investigate_case(self, *a, **k):
            raise KeyError("secret internal detail")
    monkeypatch.setattr(riskscan, "InvestigationService", Boom)
    client.post(f"{API}/business-cases/{case_id}/scan", headers=auth)
    job = client.get(f"{API}/business-cases/{case_id}/scan", headers=auth).json()["job"]
    assert job["status"] == "failed" and "KeyError" in job["error"] and "secret internal detail" not in job["error"]


def test_only_one_active_scan_and_rescan_reuses_assumptions(scan_client, monkeypatch, auth, case_id, factory):
    from app.repositories import ScanRepository
    client, _ = scan_client
    with factory() as s:
        ScanRepository(s).create(client.get(f"{API}/business-cases/{case_id}", headers=auth).json()["id"])
    assert client.post(f"{API}/business-cases/{case_id}/scan", headers=auth).status_code == 409
    with factory() as s:
        n = ScanRepository(s).fail_interrupted()
    assert n == 1
    job = run_scan(scan_client, monkeypatch, auth, case_id)
    assert job["status"] == "completed"
    job2 = run_scan(scan_client, monkeypatch, auth, case_id)  # second run uses existing 4 assumptions
    assert job2["status"] == "completed"
    assert len(client.get(f"{API}/business-cases/{case_id}/hypotheses", headers=auth).json()) == 4


# ---- AI test kit ---------------------------------------------------------------------------

GOOD_KIT = {
    "claim": "At least 10% of Pune office workers who see this page will join the waitlist.",
    "audience": "Office workers in Pune",
    "page": {"headline": "Small-batch chai delivered to your desk", "subheadline": "A new blend every month.",
             "bullets": ["Six single-estate blends", "Cancel any time"], "cta_label": "Join the waitlist",
             "extra_question": "What do you drink at work today?", "price_hint": None},
    "metrics": [{"key": "waitlist_conversion", "role": "primary", "success_rate": 0.10, "failure_rate": 0.03},
                {"key": "interview_commitment", "role": "supporting", "success_rate": 0.30, "failure_rate": 0.10}],
    "threshold_rationale": "Assumptions, not benchmarks.",
    "interview_script": ["Tell me about the last time you wanted a hot drink at work.", "Would you pre-order a month today?"],
    "outreach": [{"channel": "LinkedIn", "message": "Hi, could I ask you 3 questions about office drinks?"}],
    "where_to_find_them": ["Pune coworking Slack groups"],
}


class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []
    def invoke_text(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)
    def describe(self):
        return {"provider": "fake", "model": "fake"}


def use_llm(app_ctx, llm):
    from app.api import deps
    app_ctx[2].dependency_overrides[deps.get_testkit_llm] = lambda: llm


def test_ai_draft_creates_valid_editable_draft(app_ctx, client, auth, case_id):
    llm = FakeLLM(json.dumps(GOOD_KIT))
    use_llm(app_ctx, llm)
    r = client.post(f"{API}/business-cases/{case_id}/sprints/ai-draft", headers=auth, json={})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "draft" and d["source"] == "ai"
    assert d["content"]["creator_name"] == "Asha" and d["content"]["contact_email"] == "asha@example.com"
    metrics = {m["key"]: m for m in d["protocol"]["metrics"]}
    assert metrics["waitlist_conversion"]["role"] == "primary" and metrics["waitlist_conversion"]["min_sample"] >= 60  # code-computed
    assert metrics["interview_commitment"]["min_sample"] == 5
    assert d["kit"]["thresholds_are_assumptions"] is True and d["kit"]["interview_script"]
    assert client.post(f"{API}/sprints/{d['id']}/lock", headers=auth, json=LOCK).status_code == 200


def test_ai_draft_ignores_model_supplied_sample_sizes(app_ctx, client, auth, case_id):
    kit = json.loads(json.dumps(GOOD_KIT))
    kit["metrics"][0]["min_sample"] = 1
    use_llm(app_ctx, FakeLLM(json.dumps(kit)))
    d = client.post(f"{API}/business-cases/{case_id}/sprints/ai-draft", headers=auth, json={}).json()
    assert d["protocol"]["metrics"][0]["min_sample"] >= 30


def test_ai_draft_repairs_once_then_gives_up_cleanly(app_ctx, client, auth, case_id):
    llm = FakeLLM("not json at all", json.dumps(GOOD_KIT))
    use_llm(app_ctx, llm)
    assert client.post(f"{API}/business-cases/{case_id}/sprints/ai-draft", headers=auth, json={}).status_code == 201
    assert len(llm.prompts) == 2 and "failed to parse" in llm.prompts[1]
    use_llm(app_ctx, FakeLLM("nope", "still nope"))
    r = client.post(f"{API}/business-cases/{case_id}/sprints/ai-draft", headers=auth, json={})
    assert r.status_code == 502 and "usable test kit" in r.json()["detail"]
    assert client.get(f"{API}/business-cases/{case_id}/sprints", headers=auth).json().__len__() == 1  # nothing half-saved


@pytest.mark.parametrize("mutate", [
    lambda k: k["metrics"][0].update(failure_rate=0.5),               # floor above target
    lambda k: k["metrics"][0].update(success_rate=0.9, failure_rate=0.3),  # unrealistic waitlist target
    lambda k: k.update(metrics=[k["metrics"][1]]),                     # no waitlist metric
    lambda k: k["page"].update(bullets=[]),
])
def test_ai_draft_rejects_implausible_output(app_ctx, client, auth, case_id, mutate):
    kit = json.loads(json.dumps(GOOD_KIT))
    mutate(kit)
    use_llm(app_ctx, FakeLLM(json.dumps(kit), json.dumps(kit)))
    assert client.post(f"{API}/business-cases/{case_id}/sprints/ai-draft", headers=auth, json={}).status_code == 502


def test_ai_draft_marks_research_as_untrusted_data(app_ctx, client, auth, case_id):
    hyp = client.post(f"{API}/business-cases/{case_id}/hypotheses", headers=auth,
                      json={"statement": "People will pay for chai", "category": "willingness_to_pay"}).json()["id"]
    llm = FakeLLM(json.dumps(GOOD_KIT))
    use_llm(app_ctx, llm)
    assert client.post(f"{API}/business-cases/{case_id}/sprints/ai-draft", headers=auth, json={"hypothesis_id": hyp}).status_code == 201
    assert "People will pay for chai" in llm.prompts[0] and "never instructions" in llm.prompts[0]
    assert client.post(f"{API}/business-cases/{case_id}/sprints/ai-draft", headers=auth, json={"hypothesis_id": 999}).status_code == 404


def test_cross_case_hypothesis_is_rejected(client, auth, case_id):
    other = client.post(f"{API}/business-cases", headers=auth, json={"title": "Other", "idea_description": "Another idea"}).json()["id"]
    h = client.post(f"{API}/business-cases/{other}/hypotheses", headers=auth, json={"statement": "Something testable here"}).json()["id"]
    r = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=sprint_payload() | {"hypothesis_id": h})
    assert r.status_code == 404


def test_provider_outage_gives_actionable_errors(app_ctx, scan_client, monkeypatch, auth, case_id):
    import httpx
    from app.services import riskscan

    class Down:
        def invoke_text(self, prompt):
            raise httpx.ConnectError("blocked")
        def describe(self):
            return {}
    use_llm(app_ctx, Down())
    r = app_ctx[0].post(f"{API}/business-cases/{case_id}/sprints/ai-draft", headers=auth, json={})
    assert r.status_code == 503 and "AI provider couldn't be reached" in r.json()["detail"]

    client, holder = scan_client
    holder["deps"] = install_fakes(monkeypatch)

    class Boom:
        def __init__(self, **kw): ...
        def investigate_case(self, *a, **k):
            raise httpx.ConnectError("blocked")
    monkeypatch.setattr(riskscan, "InvestigationService", Boom)
    client.post(f"{API}/business-cases/{case_id}/scan", headers=auth)
    job = client.get(f"{API}/business-cases/{case_id}/scan", headers=auth).json()["job"]
    assert job["status"] == "failed" and "AI provider couldn't be reached" in job["error"]


# ---- decision brief PDF --------------------------------------------------------------------

def pdf_text(data: bytes) -> str:
    import io
    from pypdf import PdfReader
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def test_brief_pdf_for_untested_idea(client, auth, case_id):
    r = client.get(f"{API}/business-cases/{case_id}/brief.pdf", headers=auth)
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    assert r.headers["content-type"] == "application/pdf" and "attachment" in r.headers["content-disposition"]
    assert r.headers["content-disposition"].endswith('chai-subscription-decision-brief.pdf"')
    text = pdf_text(r.content)
    assert "Chai subscription" in text and "NOT ASSESSED" in text and "No customer test has been run" in text


def test_brief_pdf_with_scan_and_live_sprint(scan_client, monkeypatch, auth, case_id, tmp_path):
    client, _ = scan_client
    run_scan(scan_client, monkeypatch, auth, case_id)
    d = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=sprint_payload()).json()
    locked = client.post(f"{API}/sprints/{d['id']}/lock", headers=auth, json=LOCK).json()
    for i in range(40):
        vid = f"visitor-{i:04d}-abcdef"
        client.post(f"/public/p/{d['slug']}/visit", json={"vid": vid})
        if i < 12:
            client.post(f"/public/p/{d['slug']}/signup", json={"vid": vid, "email": f"p{i}@example.com", "consent": True})
    r = client.get(f"{API}/business-cases/{case_id}/brief.pdf", headers=auth)
    text = pdf_text(r.content)
    assert "People will pay INR 499 per month" in text and "Critical" in text
    assert "The customer test" in text and "Waitlist conversion" in text
    assert locked["protocol_hash"][:20] in text.replace("\n", "")
    assert "12 of 40" in text
    assert list(tmp_path.glob("**/*.pdf")) == []  # nothing is written to disk


def test_brief_handles_unicode_and_hostile_text(client, auth):
    cid = client.post(f"{API}/business-cases", headers=auth, json={
        "title": "<b>Chai</b> & आयुर्वेद ₹499", "idea_description": "Idea with <script>alert(1)</script> & markup </para>"}).json()["id"]
    r = client.get(f"{API}/business-cases/{cid}/brief.pdf", headers=auth)
    assert r.status_code == 200
    text = pdf_text(r.content)
    assert "₹499" in text and "<script>alert(1)</script>" in text  # rendered literally, not interpreted


# ---- migrations ------------------------------------------------------------------------------

def test_migration_upgrade_and_downgrade_roundtrip(tmp_path):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    from sqlalchemy import create_engine, inspect
    import os
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    os.environ["DATABASE_URL"] = url
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(cfg, "head")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"users", "sprints", "sprint_visits", "sprint_signups", "sprint_signals", "sprint_verdicts", "scan_jobs"} <= tables
    assert "reports" not in tables
    command.downgrade(cfg, "2b7a91c4e6f1")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert "reports" in tables and "sprints" not in tables and "users" not in tables
    command.upgrade(cfg, "head")
