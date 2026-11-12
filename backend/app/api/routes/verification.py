"""Verification routes (Phase 4, SYSTEM_DESIGN §10): user-initiated evidence
verification — never auto-run by collection; explicit indeterminate/failed
states; conflicts surfaced.

HTTP semantics:
- 503: no content fetcher configured in this deployment (technical,
  discoverable; nothing is silently treated as verified).
- 400: evidence has no source URL (nothing fetchable via this route).
- 200 with row_status: even a FAILED verification pass is a normal,
  inspectable outcome — the row persists the failure (fail-closed), so it
  is returned as data rather than as an HTTP error.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import (
    get_case_or_404,
    get_evidence_or_404,
    get_run_repo,
    get_verification_service,
    value_error_status,
)
from ..schemas import (
    CaseVerifyResponse,
    EvidenceVerifyResponse,
    EvidenceVerifyResult,
    VerifyRequest,
)
from ...domain.models import BusinessCase, Evidence
from ...services.verification import VerificationService, VerifierUnavailableError

router = APIRouter(tags=["verification"])


def _latest_run_id(runs, case_id: int) -> int | None:
    """Attach diagnostic verify events to the case's most recent
    investigation run, if any (pure diagnostics in workflow_metadata)."""
    existing = runs.list_by_case(case_id)
    return existing[0].id if existing else None


def _result_model(outcome) -> EvidenceVerifyResult:
    return EvidenceVerifyResult(**outcome.to_dict())


@router.post("/evidence/{evidence_id}/verify", response_model=EvidenceVerifyResponse)
def verify_single_evidence(
    evidence: Evidence = Depends(get_evidence_or_404),
    service: VerificationService = Depends(get_verification_service),
    runs=Depends(get_run_repo),
):
    if not (evidence.source_url or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Evidence has no source URL — nothing to fetch; verify its origin manually.",
        )
    try:
        outcome = service.verify_evidence(evidence, run_id=_latest_run_id(runs, evidence.business_case_id))
    except VerifierUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return EvidenceVerifyResponse(result=_result_model(outcome))


@router.post("/business-cases/{case_id}/verify", response_model=CaseVerifyResponse)
def verify_case_evidence(
    payload: VerifyRequest | None = None,
    case: BusinessCase = Depends(get_case_or_404),
    service: VerificationService = Depends(get_verification_service),
    runs=Depends(get_run_repo),
):
    try:
        data = service.verify_case(
            case,
            payload.evidence_ids if payload else None,
            run_id=_latest_run_id(runs, case.id),
        )
    except VerifierUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        status, detail = value_error_status(exc)
        raise HTTPException(status_code=status, detail=detail)
    return CaseVerifyResponse(
        results=[_result_model(outcome) for outcome in data["results"]],
        skipped=data["skipped"],
        summary=data["summary"],
    )
