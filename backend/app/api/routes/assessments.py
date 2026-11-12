"""Assessment routes (Phase 5, SYSTEM_DESIGN §5/§10 HypothesisAssessor).

Assessment is user-initiated (routes), never auto-run by collection.
History is immutable: POST creates a NEW append-only version; GET returns
the full version list with prior rationale preserved.

HTTP semantics:
- 502: the assessor produced unusable output after its repair retry (or was
  unavailable) — NOTHING is written, history stays intact (fail-closed).
- 404/400: unknown hypothesis/case, or scope references a hypothesis that is
  not in the case (input validation happens BEFORE any version is written).
- 200: a new version always has a justified qualitative status; the zero-
  evidence case yields a deterministic `unknown` version (no LLM call).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import (
    get_assessment_service,
    get_case_or_404,
    get_hypothesis_or_404,
    value_error_status,
)
from ..schemas import (
    AssessOneResponse,
    AssessmentRead,
    CaseAssessRequest,
    CaseAssessResponse,
    CaseAssessResult,
)
from ...domain.models import BusinessCase, Hypothesis
from ...services.assessment import AssessmentService, AssessmentError

router = APIRouter(tags=["assessments"])


def _read(row) -> AssessmentRead:
    return AssessmentRead.model_validate(row)


@router.post("/hypotheses/{hypothesis_id}/assess", response_model=AssessOneResponse)
def assess_hypothesis(
    hypothesis: Hypothesis = Depends(get_hypothesis_or_404),
    service: AssessmentService = Depends(get_assessment_service),
):
    try:
        outcome = service.assess_hypothesis(hypothesis)
    except AssessmentError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return AssessOneResponse(
        assessment=_read(outcome["assessment"]),
        facts=outcome["facts"],
    )


@router.post("/business-cases/{case_id}/assess", response_model=CaseAssessResponse)
def assess_case(
    payload: CaseAssessRequest | None = None,
    case: BusinessCase = Depends(get_case_or_404),
    service: AssessmentService = Depends(get_assessment_service),
):
    try:
        data = service.assess_case(
            case,
            payload.hypothesis_ids if payload else None,
        )
    except ValueError as exc:
        status, detail = value_error_status(exc)
        raise HTTPException(status_code=status, detail=detail)
    except AssessmentError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return CaseAssessResponse(
        results=[
            CaseAssessResult(
                hypothesis_id=item["hypothesis_id"],
                assessment=_read(item["assessment"]),
                facts=item["facts"],
            )
            for item in data["results"]
        ],
        summary=data["summary"],
    )


@router.get("/hypotheses/{hypothesis_id}/assessments", response_model=list[AssessmentRead])
def list_assessments(
    hypothesis: Hypothesis = Depends(get_hypothesis_or_404),
    service: AssessmentService = Depends(get_assessment_service),
):
    """Full append-only history: every version, oldest first — prior
    rationale is preserved by design and never overwritten."""
    return [_read(row) for row in service.history(hypothesis.id)]
