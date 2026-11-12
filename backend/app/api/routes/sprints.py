"""Validation sprint routes (owner side)."""

from __future__ import annotations

import csv
import io
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from ...core import config
from ...domain.models import BusinessCase, Sprint, User
from ...repositories import AssessmentRepository, EvidenceRepository, HypothesisRepository, SprintRepository
from ...services import stats
from ...services.sprints import SprintConflict, SprintService
from ...services.errors import PROVIDER_MESSAGE, looks_like_provider_error
from ...services.testkit import TestKitError, TestKitService
from ...web.pages import render_public_page
from ..deps import (
    get_assessment_repo,
    get_case_or_404,
    get_current_user,
    get_evidence_repo,
    get_hypothesis_repo,
    get_sprint_or_404,
    get_sprint_repo,
    get_sprint_service,
    get_testkit_service,
)
from ..schemas.sprints import (
    ConcludeIn,
    DossierIn,
    ExcludeIn,
    LockIn,
    PlanPreviewIn,
    SignalIn,
    SprintAiDraftIn,
    SprintCreate,
    SprintPatch,
)

router = APIRouter(tags=["sprints"])


def _conflict(exc: SprintConflict) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def _links(sprint: Sprint, request: Request) -> dict:
    base = config.public_base_url(str(request.base_url))
    return {
        "public_page": f"{base}/p/{sprint.slug}" if sprint.locked_at else None,
        "dossier": f"{base}/d/{sprint.dossier_token}" if sprint.dossier_enabled else None,
    }


def _detail(sprint: Sprint, request: Request, service: SprintService) -> dict:
    return {
        "id": sprint.id,
        "business_case_id": sprint.business_case_id,
        "hypothesis_id": sprint.hypothesis_id,
        "source": sprint.source,
        "status": sprint.status.value,
        "slug": sprint.slug,
        "content": sprint.content,
        "protocol": sprint.protocol,
        "kit": sprint.kit,
        "protocol_hash": sprint.protocol_hash,
        "locked_at": sprint.locked_at,
        "concluded_at": sprint.concluded_at,
        "dossier_enabled": sprint.dossier_enabled,
        "created_at": sprint.created_at,
        "links": _links(sprint, request),
        **service.owner_view(sprint),
    }


def _check_hypothesis(case_id: int, hypothesis_id: int | None, hypotheses: HypothesisRepository):
    if hypothesis_id is None:
        return None
    h = hypotheses.get(hypothesis_id)
    if h is None or h.business_case_id != case_id:
        raise HTTPException(status_code=404, detail=f"Hypothesis {hypothesis_id} not found in this idea.")
    return h


@router.get("/business-cases/{case_id}/sprints")
def list_sprints(
    request: Request,
    case: BusinessCase = Depends(get_case_or_404),
    sprints: SprintRepository = Depends(get_sprint_repo),
    service: SprintService = Depends(get_sprint_service),
):
    return [_detail(s, request, service) for s in sprints.list_by_case(case.id)]


@router.post("/business-cases/{case_id}/sprints", status_code=201)
def create_sprint(
    payload: SprintCreate,
    request: Request,
    case: BusinessCase = Depends(get_case_or_404),
    hypotheses: HypothesisRepository = Depends(get_hypothesis_repo),
    service: SprintService = Depends(get_sprint_service),
):
    _check_hypothesis(case.id, payload.hypothesis_id, hypotheses)
    sprint = service.create_draft(
        case.id, payload.content.model_dump(mode="json"), payload.protocol.model_dump(mode="json"),
        hypothesis_id=payload.hypothesis_id, kit=payload.kit, source="manual",
    )
    return _detail(sprint, request, service)


@router.post("/business-cases/{case_id}/sprints/ai-draft", status_code=201)
def ai_draft_sprint(
    payload: SprintAiDraftIn,
    request: Request,
    case: BusinessCase = Depends(get_case_or_404),
    user: User = Depends(get_current_user),
    hypotheses: HypothesisRepository = Depends(get_hypothesis_repo),
    assessments: AssessmentRepository = Depends(get_assessment_repo),
    evidence: EvidenceRepository = Depends(get_evidence_repo),
    service: SprintService = Depends(get_sprint_service),
    kit_service: TestKitService = Depends(get_testkit_service),
):
    hypothesis = _check_hypothesis(case.id, payload.hypothesis_id, hypotheses)
    assessment_note, evidence_notes = None, []
    if hypothesis is not None:
        latest = assessments.latest(hypothesis.id)
        if latest is not None and latest.rationale:
            assessment_note = f"Status: {latest.status.value}. {latest.rationale}"[:1200]
        for ev, _link in evidence.links_for_hypothesis(hypothesis.id)[:5]:
            if ev.finding:
                evidence_notes.append(f"- {ev.source_title[:100]}: {ev.finding[:240]}")
    try:
        content, protocol, kit = kit_service.generate(
            case, hypothesis, assessment_note=assessment_note, evidence_notes=evidence_notes,
            creator_name=user.display_name, contact_email=user.email,
        )
    except TestKitError as exc:
        raise HTTPException(status_code=502, detail=f"Couldn't generate a usable test kit: {exc}")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"The language model is unavailable: {exc}")
    except Exception as exc:  # noqa: BLE001 - provider/network failures must not surface as a bare 500
        if looks_like_provider_error(exc):
            raise HTTPException(status_code=503, detail=PROVIDER_MESSAGE)
        raise
    sprint = service.create_draft(
        case.id, content, protocol, hypothesis_id=payload.hypothesis_id, kit=kit, source="ai"
    )
    return _detail(sprint, request, service)


@router.post("/stats/plan")
def plan_preview(payload: PlanPreviewIn, user: User = Depends(get_current_user)):
    if round(payload.confidence, 2) not in stats.ALLOWED_CONFIDENCE:
        raise HTTPException(status_code=400, detail=f"confidence must be one of {list(stats.ALLOWED_CONFIDENCE)}")
    return {
        "suggested_min_sample": stats.suggested_min_sample(payload.success_rate, payload.confidence),
        "floors": stats.MIN_SAMPLE_FLOOR,
        "explanation": "Smallest sample at which a true rate 50% above your target would let the rule call a go.",
    }


@router.get("/sprints/{sprint_id}")
def get_sprint(request: Request, sprint: Sprint = Depends(get_sprint_or_404), service: SprintService = Depends(get_sprint_service)):
    return _detail(sprint, request, service)


@router.patch("/sprints/{sprint_id}")
def patch_sprint(
    payload: SprintPatch,
    request: Request,
    sprint: Sprint = Depends(get_sprint_or_404),
    case_hypotheses: HypothesisRepository = Depends(get_hypothesis_repo),
    sprints: SprintRepository = Depends(get_sprint_repo),
    service: SprintService = Depends(get_sprint_service),
):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields provided to update.")
    try:
        if "kit" in fields:
            sprints.update_kit(sprint, fields["kit"] or {})
        if {"content", "protocol", "hypothesis_id"} & fields.keys():
            if "hypothesis_id" in fields:
                _check_hypothesis(sprint.business_case_id, fields["hypothesis_id"], case_hypotheses)
            sprints.update_draft(
                sprint,
                content=payload.content.model_dump(mode="json") if payload.content else None,
                protocol=payload.protocol.model_dump(mode="json") if payload.protocol else None,
                hypothesis_id=fields["hypothesis_id"] if "hypothesis_id" in fields else ...,
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _detail(sprint, request, service)


@router.get("/sprints/{sprint_id}/preview", response_class=HTMLResponse)
def preview_sprint(sprint: Sprint = Depends(get_sprint_or_404)):
    html = render_public_page(sprint, sprint.content, nonce="", mode="preview")
    return HTMLResponse(html, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
                                       "Cache-Control": "no-store"})


@router.post("/sprints/{sprint_id}/lock")
def lock_sprint(payload: LockIn, request: Request, sprint: Sprint = Depends(get_sprint_or_404),
                service: SprintService = Depends(get_sprint_service)):
    try:
        service.lock(sprint, acknowledge_public_page=payload.acknowledge_public_page,
                     acknowledge_frozen=payload.acknowledge_frozen)
    except SprintConflict as exc:
        raise _conflict(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _detail(sprint, request, service)


@router.post("/sprints/{sprint_id}/pause")
def pause_sprint(request: Request, sprint: Sprint = Depends(get_sprint_or_404), service: SprintService = Depends(get_sprint_service)):
    try:
        service.pause(sprint)
    except SprintConflict as exc:
        raise _conflict(exc)
    return _detail(sprint, request, service)


@router.post("/sprints/{sprint_id}/resume")
def resume_sprint(request: Request, sprint: Sprint = Depends(get_sprint_or_404), service: SprintService = Depends(get_sprint_service)):
    try:
        service.resume(sprint)
    except SprintConflict as exc:
        raise _conflict(exc)
    return _detail(sprint, request, service)


@router.post("/sprints/{sprint_id}/conclude")
def conclude_sprint(payload: ConcludeIn, request: Request, sprint: Sprint = Depends(get_sprint_or_404),
                    service: SprintService = Depends(get_sprint_service)):
    try:
        service.conclude(sprint, force=payload.force)
    except SprintConflict as exc:
        raise _conflict(exc)
    return _detail(sprint, request, service)


@router.post("/sprints/{sprint_id}/dossier")
def set_dossier(payload: DossierIn, request: Request, sprint: Sprint = Depends(get_sprint_or_404),
                sprints: SprintRepository = Depends(get_sprint_repo), service: SprintService = Depends(get_sprint_service)):
    try:
        sprints.set_dossier_enabled(sprint, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _detail(sprint, request, service)


@router.post("/sprints/{sprint_id}/rotate-dossier-link")
def rotate_dossier_link(request: Request, sprint: Sprint = Depends(get_sprint_or_404), sprints: SprintRepository = Depends(get_sprint_repo),
                        service: SprintService = Depends(get_sprint_service)):
    """Invalidate a shared dossier link that went to the wrong people."""
    sprint.dossier_token = secrets.token_urlsafe(24)
    sprints._s.commit()
    return _detail(sprint, request, service)


@router.delete("/sprints/{sprint_id}", status_code=204)
def delete_sprint(sprint: Sprint = Depends(get_sprint_or_404), sprints: SprintRepository = Depends(get_sprint_repo)):
    """Deletes the sprint and every signup, visit and note collected under it."""
    sprints.delete(sprint)
    return None


# ---- collected data -------------------------------------------------------------

def _signup_dict(s) -> dict:
    return {"id": s.id, "email": s.email, "answer": s.answer, "channel": s.channel, "created_at": s.created_at,
            "excluded": s.excluded_at is not None, "excluded_reason": s.excluded_reason}


@router.get("/sprints/{sprint_id}/signups")
def list_signups(sprint: Sprint = Depends(get_sprint_or_404), sprints: SprintRepository = Depends(get_sprint_repo)):
    return [_signup_dict(s) for s in sprints.list_signups(sprint.id)]


def _csv_safe(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/sprints/{sprint_id}/signups.csv")
def export_signups(sprint: Sprint = Depends(get_sprint_or_404), sprints: SprintRepository = Depends(get_sprint_repo)):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["email", "answer", "channel", "signed_up_at_utc", "excluded", "excluded_reason"])
    for s in sprints.list_signups(sprint.id):
        writer.writerow([_csv_safe(s.email), _csv_safe(s.answer), _csv_safe(s.channel),
                         s.created_at.strftime("%Y-%m-%d %H:%M:%S"), "yes" if s.excluded_at else "no",
                         _csv_safe(s.excluded_reason)])
    return Response(out.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="signups-{sprint.slug}.csv"', "Cache-Control": "no-store"})


@router.post("/sprints/{sprint_id}/signups/{signup_id}/exclude")
def exclude_signup(signup_id: int, payload: ExcludeIn, sprint: Sprint = Depends(get_sprint_or_404),
                   sprints: SprintRepository = Depends(get_sprint_repo)):
    row = sprints.get_signup(signup_id)
    if row is None or row.sprint_id != sprint.id:
        raise HTTPException(status_code=404, detail="Signup not found.")
    try:
        return _signup_dict(sprints.exclude_signup(row, payload.reason.strip()))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


def _signal_dict(s) -> dict:
    return {"id": s.id, "outcome": s.outcome, "who": s.who, "notes": s.notes, "created_at": s.created_at,
            "excluded": s.excluded_at is not None, "excluded_reason": s.excluded_reason}


@router.get("/sprints/{sprint_id}/signals")
def list_signals(sprint: Sprint = Depends(get_sprint_or_404), sprints: SprintRepository = Depends(get_sprint_repo)):
    return [_signal_dict(s) for s in sprints.list_signals(sprint.id)]


@router.post("/sprints/{sprint_id}/signals", status_code=201)
def add_signal(payload: SignalIn, sprint: Sprint = Depends(get_sprint_or_404), sprints: SprintRepository = Depends(get_sprint_repo)):
    if sprint.locked_at is None:
        raise HTTPException(status_code=409, detail="Lock the sprint before logging conversations.")
    if sprint.status.value == "concluded":
        raise HTTPException(status_code=409, detail="This sprint is concluded; its data is final.")
    return _signal_dict(sprints.add_signal(sprint.id, payload.outcome, payload.who, payload.notes))


@router.post("/sprints/{sprint_id}/signals/{signal_id}/exclude")
def exclude_signal(signal_id: int, payload: ExcludeIn, sprint: Sprint = Depends(get_sprint_or_404),
                   sprints: SprintRepository = Depends(get_sprint_repo)):
    row = sprints.get_signal(signal_id)
    if row is None or row.sprint_id != sprint.id:
        raise HTTPException(status_code=404, detail="Entry not found.")
    try:
        return _signal_dict(sprints.exclude_signal(row, payload.reason.strip()))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
