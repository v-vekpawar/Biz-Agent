"""Assembles the /api/v1 surface (mounted by app.main:app).

Everything except /auth/register and /auth/login requires a signed-in user;
every case-scoped dependency additionally checks ownership (see api/deps.py).
The unauthenticated public surface (test pages, dossier) lives in `public`.
"""

from fastapi import APIRouter

from . import (
    assessments,
    auth,
    ai,
    briefs,
    cases,
    evidence,
    experiments,
    hypotheses,
    investigations,
    overview,
    scans,
    sprints,
    verification,
)

v2_router = APIRouter(prefix="/api/v1")
v2_router.include_router(auth.router)
v2_router.include_router(ai.router)
v2_router.include_router(cases.router, prefix="/business-cases")
v2_router.include_router(overview.router)
v2_router.include_router(scans.router)
v2_router.include_router(sprints.router)
v2_router.include_router(briefs.router)
# Research engine (advanced / API use; the app drives it through the scan).
v2_router.include_router(hypotheses.router)
v2_router.include_router(investigations.router)
v2_router.include_router(evidence.router)
v2_router.include_router(verification.router)
v2_router.include_router(assessments.router)
v2_router.include_router(experiments.router)
