"""Experiment routes (Phase 6, SYSTEM_DESIGN §10).

- Generation is user-initiated: the designer proposes up to 3 concrete
  validation experiments (status=proposed) for one hypothesis; validation
  happens BEFORE any write — malformed design ⇒ 502 with nothing stored.
- PATCH manages user-owned fields/status. After outcomes exist the judged
  content is frozen (400 otherwise) — iterate with a NEW experiment.
- Outcomes are append-only timestamped records; the create-outcome response
  PROPOSES re-assessment (core loop) without overwriting history.
- GET experiment outcomes is an ADDITION over §10: durable outcomes must be
  visible without case-wide list scanning (documented decision).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import (
    get_case_or_404,
    get_db,
    get_experiment_or_404,
    get_experiment_service,
    get_hypothesis_or_404,
    value_error_status,
)
from ..schemas import (
    ExperimentGenerateRequest,
    ExperimentListResponse,
    ExperimentPatch,
    ExperimentRead,
    OutcomeCreate,
    OutcomeCreateResponse,
    OutcomeRead,
    CriteriaRevisionRequest,
)
from ...domain.models import BusinessCase, Experiment, Hypothesis, ExperimentCriteriaRevision
from ...services.experiments import ExperimentService, ExperimentDesignError

router = APIRouter(tags=["experiments"])


def _read(row: Experiment, service: ExperimentService) -> ExperimentRead:
    model = ExperimentRead.model_validate(row)
    model.outcomes = [OutcomeRead.model_validate(outcome) for outcome in service.outcomes(row.id)]
    return model


@router.post("/hypotheses/{hypothesis_id}/experiments", status_code=201, response_model=ExperimentListResponse)
def generate_experiments(
    payload: ExperimentGenerateRequest | None = None,
    hypothesis: Hypothesis = Depends(get_hypothesis_or_404),
    service: ExperimentService = Depends(get_experiment_service),
):
    try:
        rows = service.generate(hypothesis, payload.guidance if payload else None)
    except ExperimentDesignError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return ExperimentListResponse(experiments=[_read(row, service) for row in rows])


@router.get("/business-cases/{case_id}/experiments", response_model=list[ExperimentRead])
def list_case_experiments(
    case: BusinessCase = Depends(get_case_or_404),
    service: ExperimentService = Depends(get_experiment_service),
):
    return [_read(row, service) for row in service.list_case(case.id)]


@router.patch("/experiments/{experiment_id}", response_model=ExperimentRead)
def patch_experiment(
    payload: ExperimentPatch,
    experiment: Experiment = Depends(get_experiment_or_404),
    service: ExperimentService = Depends(get_experiment_service),
):
    try:
        row = service.update(experiment, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        status, detail = value_error_status(exc)
        raise HTTPException(status_code=status, detail=detail)
    return _read(row, service)


@router.post("/experiments/{experiment_id}/outcomes", status_code=201, response_model=OutcomeCreateResponse)
def record_outcome(
    payload: OutcomeCreate,
    experiment: Experiment = Depends(get_experiment_or_404),
    service: ExperimentService = Depends(get_experiment_service),
):
    try:
        outcome, suggestion = service.add_outcome(experiment, payload.model_dump())
    except ValueError as exc:
        status, detail = value_error_status(exc)
        raise HTTPException(status_code=status, detail=detail)
    return OutcomeCreateResponse(
        outcome=OutcomeRead.model_validate(outcome),
        assessment_suggestion=suggestion["assessment_suggestion"],
    )


@router.get("/experiments/{experiment_id}/outcomes", response_model=list[OutcomeRead])
def list_experiment_outcomes(
    experiment: Experiment = Depends(get_experiment_or_404),
    service: ExperimentService = Depends(get_experiment_service),
):
    return [OutcomeRead.model_validate(row) for row in service.outcomes(experiment.id)]


@router.post("/experiments/{experiment_id}/criteria-revisions", status_code=201)
def revise_experiment_criteria(
    payload: CriteriaRevisionRequest,
    experiment: Experiment = Depends(get_experiment_or_404),
    service: ExperimentService = Depends(get_experiment_service),
    db: Session = Depends(get_db),
):
    """Version criteria changes with a reason; never rewrite a judged test."""
    if not payload.success_criteria and not payload.failure_criteria:
        raise HTTPException(status_code=400, detail="Provide new success and/or failure criteria.")
    if service.outcomes(experiment.id):
        raise HTTPException(status_code=409, detail="Criteria are locked after the first outcome. Create a new experiment instead.")
    latest = db.scalar(select(ExperimentCriteriaRevision).where(ExperimentCriteriaRevision.experiment_id == experiment.id).order_by(ExperimentCriteriaRevision.version.desc()))
    version = (latest.version if latest else 0) + 1
    if payload.success_criteria is not None:
        experiment.success_criteria = payload.success_criteria
    if payload.failure_criteria is not None:
        experiment.failure_criteria = payload.failure_criteria
    revision = ExperimentCriteriaRevision(
        experiment_id=experiment.id, version=version,
        success_criteria=experiment.success_criteria, failure_criteria=experiment.failure_criteria,
        reason=payload.reason.strip(),
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)
    return {"id": revision.id, "experiment_id": revision.experiment_id, "version": revision.version,
            "success_criteria": revision.success_criteria, "failure_criteria": revision.failure_criteria,
            "reason": revision.reason, "created_at": revision.created_at}
