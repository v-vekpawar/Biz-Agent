"""Public, unauthenticated surface: the test page, its collection endpoints, and the dossier.

Deliberately minimal: no cookies, no IP storage, no third-party requests.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from ...core import config as settings
from ...core.ratelimit import limit
from ...domain.enums import SprintStatus
from ...repositories import SprintRepository, UserRepository
from ...web.pages import render_dossier, render_message_page, render_public_page
from ...services.sprints import SprintClosed, SprintService
from ..deps import get_sprint_repo, get_sprint_service, get_user_repo
from ..schemas.sprints import SignupIn, VisitIn
from ...repositories import CaseRepository
from ..deps import get_case_repo

router = APIRouter(tags=["public"])

_PAGE_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY"}


def _html(body: str, status: int = 200, csp: str = "default-src 'none'; style-src 'unsafe-inline'") -> HTMLResponse:
    return HTMLResponse(body, status_code=status, headers={**_PAGE_HEADERS, "Content-Security-Policy": csp})


@router.get("/p/{slug}", response_class=HTMLResponse)
def public_page(slug: str, sprints: SprintRepository = Depends(get_sprint_repo), service: SprintService = Depends(get_sprint_service)):
    sprint = sprints.get_by_slug(slug.lower())
    if sprint is None or sprint.status == SprintStatus.DRAFT:
        return _html(render_message_page("Page not found", "This link isn't active."), 404)
    if not service.accepting_data(sprint):
        why = "This test is paused for now." if sprint.status == SprintStatus.PAUSED else "This test has ended. Thank you for your interest."
        return _html(render_message_page("Not taking responses", why), 200)
    nonce = secrets.token_urlsafe(16)
    csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; "
           "connect-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'")
    return _html(render_public_page(sprint, sprint.content, nonce=nonce), 200, csp)


def _live_sprint(slug: str, sprints: SprintRepository):
    sprint = sprints.get_by_slug(slug.lower())
    if sprint is None or sprint.status == SprintStatus.DRAFT:
        raise HTTPException(status_code=404, detail="Not found.")
    return sprint


@router.post("/public/p/{slug}/visit", dependencies=[Depends(limit("visit", settings.visit_limit, 60))])
def record_visit(slug: str, payload: VisitIn, sprints: SprintRepository = Depends(get_sprint_repo),
                 service: SprintService = Depends(get_sprint_service)):
    sprint = _live_sprint(slug, sprints)
    try:
        service.record_visit(sprint, payload.vid, payload.channel)
    except SprintClosed as exc:
        raise HTTPException(status_code=410, detail=str(exc))
    return {"ok": True}


@router.post("/public/p/{slug}/signup", dependencies=[Depends(limit("signup", settings.signup_limit, 600))])
def record_signup(slug: str, payload: SignupIn, sprints: SprintRepository = Depends(get_sprint_repo),
                  service: SprintService = Depends(get_sprint_service)):
    sprint = _live_sprint(slug, sprints)
    try:
        service.record_signup(sprint, vid=payload.vid, email=payload.email, answer=payload.answer,
                              consent=payload.consent, channel=payload.channel, honeypot=payload.website)
    except SprintClosed as exc:
        raise HTTPException(status_code=410, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Same response whether the signup is new, a duplicate, or a honeypot hit.
    return {"ok": True}


@router.get("/d/{token}", response_class=HTMLResponse)
def dossier(token: str, sprints: SprintRepository = Depends(get_sprint_repo), service: SprintService = Depends(get_sprint_service),
            cases: CaseRepository = Depends(get_case_repo), users: UserRepository = Depends(get_user_repo)):
    sprint = sprints.get_by_dossier_token(token)
    if sprint is None or not sprint.dossier_enabled or sprint.locked_at is None:
        return _html(render_message_page("Dossier not available", "This link isn't active or has been turned off by its owner."), 404)
    case = cases.get(sprint.business_case_id)
    owner = users.get(case.owner_id) if case and case.owner_id else None
    return _html(render_dossier(service.dossier_view(sprint, owner.display_name if owner else "the owner")))
