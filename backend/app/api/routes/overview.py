"""One-call workspace summary for the app: which stage is this idea in?"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...domain.enums import SprintStatus
from ...domain.models import BusinessCase
from ...repositories import HypothesisRepository, ScanRepository, SprintRepository
from ..deps import get_case_or_404, get_hypothesis_repo, get_scan_repo, get_sprint_repo

router = APIRouter(tags=["overview"])


@router.get("/business-cases/{case_id}/overview")
def overview(
    case: BusinessCase = Depends(get_case_or_404),
    jobs: ScanRepository = Depends(get_scan_repo),
    sprints: SprintRepository = Depends(get_sprint_repo),
    hypotheses: HypothesisRepository = Depends(get_hypothesis_repo),
):
    job = jobs.latest_for_case(case.id)
    sprint_rows = sprints.list_by_case(case.id)
    current = next((s for s in sprint_rows if s.status != SprintStatus.CONCLUDED), None) or (sprint_rows[0] if sprint_rows else None)

    if current is not None and current.status == SprintStatus.CONCLUDED:
        stage = "decided"
    elif current is not None and current.locked_at is not None:
        stage = "testing"
    elif current is not None:
        stage = "test_draft"
    elif job is not None and job.status.value == "completed":
        stage = "scanned"
    elif job is not None and job.status.value in ("queued", "running"):
        stage = "scanning"
    else:
        stage = "idea"
    verdict = None
    if stage == "decided":
        snaps = sprints.list_verdicts(current.id)
        verdict = snaps[-1].verdict.value if snaps else None
    return {
        "stage": stage,
        "verdict": verdict,
        "assumption_count": len(hypotheses.list_by_case(case.id)),
        "scan_status": job.status.value if job else None,
        "current_sprint_id": current.id if current else None,
        "sprint_count": len(sprint_rows),
    }
