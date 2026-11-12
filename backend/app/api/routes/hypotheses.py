"""Hypothesis routes: user CRUD + LLM extraction (PRODUCT_SPEC §7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import (
    ChatLLM,
    HypothesisRepository,
    get_case_or_404,
    get_extractor,
    get_hypothesis_or_404,
    get_hypothesis_repo,
    get_hypothesis_service,
    value_error_status,
)
from ..schemas import (
    ExtractionResponse,
    HypothesisCreate,
    HypothesisPatch,
    HypothesisRead,
)
from ...domain.enums import HypothesisOrigin
from ...domain.models import BusinessCase, Hypothesis
from ...services.extraction import ExtractionError, HypothesisExtractionService
from ...services.hypotheses import HypothesisService

router = APIRouter(tags=["hypotheses"])


@router.post("/business-cases/{case_id}/hypotheses", status_code=201, response_model=HypothesisRead)
def add_hypothesis(
    payload: HypothesisCreate,
    case: BusinessCase = Depends(get_case_or_404),
    service: HypothesisService = Depends(get_hypothesis_service),
):
    try:
        return service.add_user_hypothesis(case, payload.model_dump())
    except ValueError as exc:
        status, detail = value_error_status(exc)
        raise HTTPException(status_code=status, detail=detail)


@router.get("/business-cases/{case_id}/hypotheses", response_model=list[HypothesisRead])
def list_hypotheses(
    case: BusinessCase = Depends(get_case_or_404),
    hypotheses: HypothesisRepository = Depends(get_hypothesis_repo),
):
    return hypotheses.list_by_case(case.id)


@router.post("/business-cases/{case_id}/hypotheses/extract", response_model=ExtractionResponse)
def extract_hypotheses(
    case: BusinessCase = Depends(get_case_or_404),
    hypotheses: HypothesisRepository = Depends(get_hypothesis_repo),
    extractor: ChatLLM = Depends(get_extractor),
):
    """LLM-backed extraction: candidates are stored with status=unknown,
    origin=ai_generated (review required; never verified facts). Malformed
    model output that survives the bound repair retry yields a 502, never an
    invented success."""
    existing = [h.statement for h in hypotheses.list_by_case(case.id)]
    try:
        result, meta = HypothesisExtractionService(llm=extractor).extract(case, existing)
    except ExtractionError as exc:
        # Malformed model output that survived the bounded repair retry: explicit
        # failure, never a fabricated success.
        raise HTTPException(status_code=502, detail=str(exc))
    except RuntimeError as exc:
        # Provider misconfigured/unavailable (e.g. missing API key) — caught
        # after ExtractionError; both are RuntimeErrors.
        raise HTTPException(status_code=503, detail=str(exc))

    created = []
    for candidate in result.hypotheses:
        created.append(
            hypotheses.create(
                case.id,
                candidate["statement"],
                category=candidate["category"],
                rationale=candidate["rationale"],
                customer_segment=candidate["customer_segment"],
                geography=candidate["geography"],
                priority=candidate["priority"],
                testability_notes=candidate["testability_notes"],
                origin=HypothesisOrigin.AI_GENERATED,
            )
        )

    return ExtractionResponse(
        hypotheses=created,
        meta={
            "provider": meta["provider"],
            "model": meta["model"],
            "prompt_version": meta["prompt_version"],
            "raw_candidates": result.raw_candidates,
            "kept_candidates": len(created),
            "dropped_invalid": result.dropped_invalid,
            "deduplicated": result.deduplicated,
            "context_gaps": result.context_gaps,
        },
    )


@router.patch("/hypotheses/{hypothesis_id}", response_model=HypothesisRead)
def patch_hypothesis(
    payload: HypothesisPatch,
    hypothesis: Hypothesis = Depends(get_hypothesis_or_404),
    service: HypothesisService = Depends(get_hypothesis_service),
):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields provided to update.")
    try:
        return service.update(hypothesis.id, fields)
    except ValueError as exc:
        status, detail = value_error_status(exc)
        raise HTTPException(status_code=status, detail=detail)


@router.delete("/hypotheses/{hypothesis_id}", status_code=204)
def delete_hypothesis(
    hypothesis: Hypothesis = Depends(get_hypothesis_or_404),
    service: HypothesisService = Depends(get_hypothesis_service),
):
    service.delete(hypothesis.id)
    return None
