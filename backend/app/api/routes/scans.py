"""Risk scan routes: start a background scan, poll it, read the live risk ranking."""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ...domain.models import BusinessCase
from ...repositories import AssessmentRepository, EvidenceRepository, HypothesisRepository, ScanRepository
from ...services.riskscan import rank_risks, recommended_hypothesis_id
from ..deps import (
    get_assessment_repo,
    get_case_or_404,
    get_evidence_repo,
    get_hypothesis_repo,
    get_scan_executor,
    get_scan_repo,
)

router = APIRouter(tags=["scan"])


def _job_dict(job) -> dict:
    return {
        "id": job.id,
        "business_case_id": job.business_case_id,
        "status": job.status.value,
        "step": job.step,
        "progress": job.progress,
        "log": job.log or [],
        "warnings": job.warnings or [],
        "error": job.error,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


@router.post("/business-cases/{case_id}/scan", status_code=202)
def start_scan(
    background: BackgroundTasks,
    case: BusinessCase = Depends(get_case_or_404),
    jobs: ScanRepository = Depends(get_scan_repo),
    executor: Callable[[int], None] = Depends(get_scan_executor),
):
    if jobs.active_for_case(case.id) is not None:
        raise HTTPException(status_code=409, detail="A scan is already running for this idea.")
    job = jobs.create(case.id)
    background.add_task(executor, job.id)
    return _job_dict(job)


@router.get("/business-cases/{case_id}/scan")
def latest_scan(case: BusinessCase = Depends(get_case_or_404), jobs: ScanRepository = Depends(get_scan_repo)):
    job = jobs.latest_for_case(case.id)
    return {"job": _job_dict(job) if job else None}


@router.get("/business-cases/{case_id}/risks")
def live_risks(
    case: BusinessCase = Depends(get_case_or_404),
    hypotheses: HypothesisRepository = Depends(get_hypothesis_repo),
    assessments: AssessmentRepository = Depends(get_assessment_repo),
    evidence: EvidenceRepository = Depends(get_evidence_repo),
):
    """Ranking recomputed from current rows (reflects edits made after the scan)."""
    risks = rank_risks(hypotheses.list_by_case(case.id), assessments, evidence)
    return {"risks": risks, "recommended_hypothesis_id": recommended_hypothesis_id(risks)}
