"""Decision routes: the in-app decision view and the brief PDF.

Both are generated from the same deterministic data (services.brief): the
PDF streams and is never stored; the decision endpoint returns JSON for the
workspace's Decision tab — verdict, prioritized actions, risks, test
results and evidence counts. No LLM runs at view time.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ...domain.models import BusinessCase, User
from ...reports import render_brief_pdf
from ...services.brief import build_brief, build_decisions
from ..deps import get_case_or_404, get_current_user, get_db

router = APIRouter(tags=["brief"])


def _safe_filename(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()[:50] or "idea"
    return f"{slug}-decision-brief.pdf"


def _sprint_json(sprint: dict | None) -> dict | None:
    if sprint is None:
        return None
    out = dict(sprint)
    out["locked_at"] = sprint["locked_at"].isoformat() if sprint.get("locked_at") else None
    return out


@router.get("/business-cases/{case_id}/decision")
def read_decision(
    case: BusinessCase = Depends(get_case_or_404),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Everything the Decision tab shows: verdict, the prioritized decisions
    the founder should take (deterministic — derived from the same data as
    the PDF), the ranked risks, the customer-test results and evidence counts."""
    data = build_brief(session, case, user)
    by_status: dict[str, int] = {}
    for row in data["evidence"]:
        by_status[row["verification"]] = by_status.get(row["verification"], 0) + 1
    return {
        "verdict": data["verdict"],
        "decisions": build_decisions(data),
        "risks": data["risks"],
        "sprint": _sprint_json(data["sprint"]),
        "evidence": {
            "total": len(data["evidence"]),
            "verified": by_status.get("verified", 0),
            "indeterminate": by_status.get("indeterminate", 0),
            "unverified": by_status.get("unverified", 0),
            "failed": by_status.get("failed", 0),
        },
        "generated_at": data["generated_at"].isoformat(),
    }


@router.get("/business-cases/{case_id}/brief.pdf")
def download_brief(
    case: BusinessCase = Depends(get_case_or_404),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    pdf = render_brief_pdf(build_brief(session, case, user))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{_safe_filename(case.title)}"',
            "Cache-Control": "no-store",
        },
    )
