"""Evidence routes (SYSTEM_DESIGN §10): inspect collected evidence, add user
observations, read single records. Evidence is durable relational data."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import (
    get_evidence_or_404,
    get_evidence_service,
    get_hypothesis_or_404,
    value_error_status,
)
from ..schemas import EvidenceLinkRead, EvidenceRead, EvidenceUnlinkRequest, ManualEvidenceCreate
from ...domain.models import Evidence, Hypothesis

router = APIRouter(tags=["evidence"])


@router.post("/hypotheses/{hypothesis_id}/evidence", status_code=201, response_model=EvidenceLinkRead)
def add_manual_evidence(
    payload: ManualEvidenceCreate,
    hypothesis: Hypothesis = Depends(get_hypothesis_or_404),
    service: object = Depends(get_evidence_service),
):
    try:
        row = service.add_manual(hypothesis.business_case_id, hypothesis, payload.model_dump())
    except ValueError as exc:
        status, detail = value_error_status(exc)
        raise HTTPException(status_code=status, detail=detail)

    # Rebuild the (evidence, link) pair for the just-created row.
    pairs = service.links_for_hypothesis(hypothesis.id)
    evidence, link = next((e, l) for e, l in pairs if e.id == row.id)
    return EvidenceLinkRead(
        hypothesis_id=hypothesis.id,
        evidence_id=evidence.id,
        relationship=link.relationship,
        relationship_rationale=link.relationship_rationale,
        created_at=link.created_at,
        evidence=evidence,
    )


@router.get("/hypotheses/{hypothesis_id}/evidence", response_model=list[EvidenceLinkRead])
def list_hypothesis_evidence(
    hypothesis=Depends(get_hypothesis_or_404),
    service: object = Depends(get_evidence_service),
):
    pairs = service.links_for_hypothesis(hypothesis.id)
    return [
        EvidenceLinkRead(
            hypothesis_id=hypothesis.id,
            evidence_id=evidence.id,
            relationship=link.relationship,
            relationship_rationale=link.relationship_rationale,
            created_at=link.created_at,
            evidence=evidence,
        )
        for evidence, link in pairs
    ]


@router.get("/evidence/{evidence_id}", response_model=EvidenceRead)
def get_evidence(evidence: Evidence = Depends(get_evidence_or_404)):
    return evidence


@router.delete("/hypotheses/{hypothesis_id}/evidence", status_code=200)
def unlink_evidence(
    payload: EvidenceUnlinkRequest,
    hypothesis=Depends(get_hypothesis_or_404),
    service: object = Depends(get_evidence_service),
):
    """Remove the link between a hypothesis and an evidence row.
    The evidence row itself is preserved in the case's evidence register.
    Returns 404 if the link does not exist."""
    removed = service.unlink(hypothesis.id, payload.evidence_id)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"No link found between H{hypothesis.id} and E{payload.evidence_id}.",
        )
    return {"removed": True, "hypothesis_id": hypothesis.id, "evidence_id": payload.evidence_id}
