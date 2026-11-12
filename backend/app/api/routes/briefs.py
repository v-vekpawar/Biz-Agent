"""Decision-brief PDF: generated on request, streamed to the browser, never stored."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ...domain.models import BusinessCase, User
from ...reports import render_brief_pdf
from ...services.brief import build_brief
from ..deps import get_case_or_404, get_current_user, get_db

router = APIRouter(tags=["brief"])


def _safe_filename(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()[:50] or "idea"
    return f"{slug}-decision-brief.pdf"


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
