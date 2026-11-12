"""
Risk scan: the one-click on-ramp.

    extract assumptions -> research both sides -> check sources -> weigh evidence -> rank risks

The scan reuses the research engine (extraction, investigation, verification,
assessment) and adds a deterministic ranking on top. It runs as a background
job whose state is persisted in `scan_jobs`, so the UI can poll it.

Failure policy:
- Fatal (job fails, nothing invented): the extractor or the assessor is
  unavailable or returns unusable output; the planner cannot plan.
- Non-fatal (recorded as a warning, scan continues): no search key, no source
  fetcher, individual verification problems. Missing evidence becomes "no
  usable evidence found", which the ranking treats as an OPEN risk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session, sessionmaker

from ..domain.enums import HypothesisCategory, HypothesisOrigin, HypothesisStatus
from ..domain.models import BusinessCase, Hypothesis
from ..integrations.fetch.base import ContentFetcher
from ..integrations.llm.provider import ChatLLM
from ..integrations.search.base import SearchProvider
from ..repositories import (
    AssessmentRepository,
    CaseRepository,
    EvidenceRepository,
    ExperimentRepository,
    HypothesisRepository,
    RunRepository,
    ScanRepository,
    UploadRepository,
)
from .assessment import AssessmentError, AssessmentService, evidence_facts
from .errors import PROVIDER_MESSAGE, looks_like_provider_error
from .extraction import ExtractionError, HypothesisExtractionService
from .investigation import InvestigationError, InvestigationService
from .verification import VerificationService, VerifierUnavailableError

log = logging.getLogger("bizagent.scan")

# Can a landing page / short interview round actually test this kind of assumption?
SPRINT_TESTABLE = {
    HypothesisCategory.CUSTOMER_PROBLEM,
    HypothesisCategory.MARKET_DEMAND,
    HypothesisCategory.WILLINGNESS_TO_PAY,
    HypothesisCategory.PRICING,
    HypothesisCategory.COMPETITION_ALTERNATIVES,
    HypothesisCategory.DISTRIBUTION_ACQUISITION,
}

STATUS_WEIGHT = {
    HypothesisStatus.CONTRADICTED: 4,
    HypothesisStatus.UNKNOWN: 3,
    HypothesisStatus.WEAKLY_SUPPORTED: 2,
    HypothesisStatus.PARTIALLY_SUPPORTED: 1,
    HypothesisStatus.SUPPORTED: 0,
}
LEVEL = {
    HypothesisStatus.CONTRADICTED: "critical",
    HypothesisStatus.UNKNOWN: "open",
    HypothesisStatus.WEAKLY_SUPPORTED: "thin",
    HypothesisStatus.PARTIALLY_SUPPORTED: "partial",
    HypothesisStatus.SUPPORTED: "low",
}
CATEGORY_WEIGHT = {
    HypothesisCategory.WILLINGNESS_TO_PAY: 3,
    HypothesisCategory.CUSTOMER_PROBLEM: 3,
    HypothesisCategory.MARKET_DEMAND: 2,
    HypothesisCategory.COMPETITION_ALTERNATIVES: 2,
    HypothesisCategory.UNIT_ECONOMICS: 2,
    HypothesisCategory.DISTRIBUTION_ACQUISITION: 2,
    HypothesisCategory.PRICING: 1,
}
PRIORITY_WEIGHT = {"high": 2, "medium": 1, "low": 0}


@dataclass
class ScanDeps:
    extractor: ChatLLM
    planner: ChatLLM
    verifier: ChatLLM
    assessor: ChatLLM
    search_provider: SearchProvider | None
    fetcher: ContentFetcher | None


class ScanFailure(RuntimeError):
    """Fatal scan failure with a user-facing message."""


def _headline(status: HypothesisStatus, facts: dict) -> str:
    sup, con = facts["supports"], facts["contradicts"]
    n_sup = sum(len(v) for v in sup.values())
    n_con = sum(len(v) for v in con.values())
    if status == HypothesisStatus.CONTRADICTED:
        return f"Evidence points against this ({n_con} source{'s' if n_con != 1 else ''} against, {n_sup} for)."
    if status == HypothesisStatus.UNKNOWN:
        if n_sup + n_con == 0:
            return "No usable evidence found. Only a real-world test can answer this."
        return "The evidence is inconclusive. A real-world test would settle it."
    if status == HypothesisStatus.WEAKLY_SUPPORTED:
        return "Thin or indirect support only. Don't rely on it yet."
    if status == HypothesisStatus.PARTIALLY_SUPPORTED:
        return "Partly supported, with real qualifications."
    return "Supported by the evidence found. Still worth confirming with customers."


def rank_risks(
    hypotheses: list[Hypothesis],
    assessments: AssessmentRepository,
    evidence: EvidenceRepository,
) -> list[dict[str, Any]]:
    """Deterministic ranking of assumptions by how likely they are to kill the idea."""
    rows: list[dict[str, Any]] = []
    for h in hypotheses:
        latest = assessments.latest(h.id)
        status = latest.status if latest is not None else h.current_status
        facts = evidence_facts(evidence.links_for_hypothesis(h.id))
        verified = len(facts["supports"]["verified"]) + len(facts["contradicts"]["verified"])
        score = (
            STATUS_WEIGHT[status] * 100
            + PRIORITY_WEIGHT.get((h.priority or "").lower(), 0) * 10
            + CATEGORY_WEIGHT.get(h.category, 0)
        )
        rows.append({
            "hypothesis_id": h.id,
            "statement": h.statement,
            "category": h.category.value,
            "origin": h.origin.value if isinstance(h.origin, HypothesisOrigin) else h.origin,
            "priority": h.priority,
            "status": status.value,
            "level": LEVEL[status],
            "headline": _headline(status, facts),
            "rationale": latest.rationale if latest is not None else None,
            "next_step": latest.recommended_next_step if latest is not None else None,
            "evidence": {
                "supports": sum(len(v) for v in facts["supports"].values()),
                "contradicts": sum(len(v) for v in facts["contradicts"].values()),
                "neutral": len(facts["neutral"]),
                "verified": verified,
            },
            "sprint_testable": h.category in SPRINT_TESTABLE,
            "_score": score,
        })
    rows.sort(key=lambda r: (-r["_score"], r["hypothesis_id"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        row.pop("_score")
    return rows


def recommended_hypothesis_id(risks: list[dict[str, Any]]) -> int | None:
    """The riskiest assumption a landing page / interview round can actually test."""
    for r in risks:
        if r["sprint_testable"] and r["level"] != "low":
            return r["hypothesis_id"]
    return risks[0]["hypothesis_id"] if risks else None


def build_result(risks: list[dict[str, Any]], warnings: list[str], evidence_total: int) -> dict[str, Any]:
    return {
        "risks": risks,
        "top_risk_ids": [r["hypothesis_id"] for r in risks[:3]],
        "recommended_hypothesis_id": recommended_hypothesis_id(risks),
        "evidence_total": evidence_total,
        "warnings": warnings,
    }


def execute_scan(session_factory: sessionmaker[Session], job_id: int, deps: ScanDeps) -> None:
    """Run a queued scan job to completion. Never raises: failures are stored on the job."""
    session = session_factory()
    jobs = ScanRepository(session)
    job = jobs.get(job_id)
    if job is None:
        session.close()
        return
    try:
        _run(session, jobs, job, deps)
    except ScanFailure as exc:
        jobs.fail(job, str(exc))
    except ModuleNotFoundError as exc:
        log.exception("scan %s: missing package", job_id)
        jobs.fail(job, f"A package this feature needs isn't installed on the server ({exc.name}). Install requirements.txt and restart.")
    except Exception as exc:  # noqa: BLE001 - last-resort guard; details to logs, summary to the user
        log.exception("scan %s crashed", job_id)
        if looks_like_provider_error(exc):
            jobs.fail(job, PROVIDER_MESSAGE)
        else:
            jobs.fail(job, f"The scan stopped unexpectedly ({type(exc).__name__}). Try again; if it repeats, check the server log.")
    finally:
        session.close()


def _run(session: Session, jobs: ScanRepository, job, deps: ScanDeps) -> None:
    cases = CaseRepository(session)
    hypotheses = HypothesisRepository(session)
    evidence = EvidenceRepository(session)
    runs = RunRepository(session)
    assessments = AssessmentRepository(session)
    experiments = ExperimentRepository(session)
    uploads = UploadRepository(session)
    case: BusinessCase = cases.require(job.business_case_id)

    jobs.start(job)

    # 1. What must be true
    jobs.progress(job, "assumptions", 5, "Working out what has to be true for this idea to work.")
    existing = hypotheses.list_by_case(case.id)
    if existing:
        jobs.progress(job, "assumptions", 15, f"Using your {len(existing)} existing assumptions.")
    else:
        try:
            result, _meta = HypothesisExtractionService(llm=deps.extractor).extract(case, [])
        except ExtractionError as exc:
            raise ScanFailure(f"Couldn't extract assumptions from the idea: {exc}") from exc
        except RuntimeError as exc:
            raise ScanFailure(f"The language model is unavailable: {exc}") from exc
        for c in result.hypotheses:
            hypotheses.create(
                case.id, c["statement"], category=c["category"], rationale=c["rationale"],
                customer_segment=c["customer_segment"], geography=c["geography"], priority=c["priority"],
                testability_notes=c["testability_notes"], origin=HypothesisOrigin.AI_GENERATED,
            )
        jobs.progress(job, "assumptions", 15, f"Found {len(result.hypotheses)} assumptions to check.")

    # 2. Research both sides
    jobs.progress(job, "research", 20, "Searching for evidence for and against each assumption.")
    if deps.search_provider is None:
        jobs.warn(job, "Web search isn't configured, so no sources were collected. Risks below rest on your own documents only.")
    try:
        inv = InvestigationService(
            planner_llm=deps.planner, search_provider=deps.search_provider,
            hypotheses=hypotheses, evidence=evidence, runs=runs, uploads=uploads,
        ).investigate_case(case, None)
    except InvestigationError as exc:
        raise ScanFailure(f"Couldn't plan the research: {exc}") from exc
    except RuntimeError as exc:
        raise ScanFailure(f"The language model is unavailable: {exc}") from exc
    for gap in inv.get("gaps", [])[:3]:
        jobs.warn(job, str(gap))
    jobs.progress(
        job, "research", 55,
        f"Collected {len(inv['created'])} new sources ({len(inv['reused'])} already known).",
    )

    # 3. Check the sources
    jobs.progress(job, "verify", 58, "Opening the sources to check they say what the search snippets claim.")
    if deps.fetcher is None:
        jobs.warn(job, "Source fetching isn't configured, so sources stay unverified.")
    else:
        try:
            ver = VerificationService(
                verifier_llm=deps.verifier, fetcher=deps.fetcher, evidence=evidence,
                hypotheses=hypotheses, cases=cases, runs=runs,
            ).verify_case(case, None, run_id=inv["run"].id)
            jobs.progress(job, "verify", 78, f"Verified {ver['summary']['verified']} sources.")
        except VerifierUnavailableError as exc:
            jobs.warn(job, str(exc))
        except RuntimeError as exc:
            jobs.warn(job, f"Source checking was skipped: {exc}")

    # 4. Weigh the evidence
    jobs.progress(job, "assess", 80, "Weighing the evidence for each assumption.")
    try:
        AssessmentService(
            assessor_llm=deps.assessor, evidence=evidence, hypotheses=hypotheses, assessments=assessments,
            cases=cases, runs=runs, experiments=experiments,
        ).assess_case(case, None, run_id=inv["run"].id)
    except AssessmentError as exc:
        raise ScanFailure(f"Couldn't weigh the evidence: {exc}") from exc
    except RuntimeError as exc:
        raise ScanFailure(f"The language model is unavailable: {exc}") from exc

    # 5. Rank
    jobs.progress(job, "rank", 95, "Ranking what is most likely to sink the idea.")
    risks = rank_risks(hypotheses.list_by_case(case.id), assessments, evidence)
    jobs.complete(job, build_result(risks, list(job.warnings or []), len(evidence.list_by_case(case.id))))
