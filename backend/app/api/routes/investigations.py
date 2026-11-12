"""Investigation routes (SYSTEM_DESIGN §10): start runs, inspect runs/events."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import (
    get_case_or_404,
    get_run_or_404,
    get_investigation_service,
    value_error_status,
)
from ..schemas import (
    InvestigationCreate,
    InvestigationResponse,
    InvestigationRunRead,
    RunEventsRead,
)
from ...services.investigation import InvestigationError

router = APIRouter(tags=["investigations"])


@router.post(
    "/business-cases/{case_id}/investigations",
    status_code=201,
    response_model=InvestigationResponse,
)
def start_investigation(
    payload: InvestigationCreate | None = None,
    pair=Depends(get_investigation_service),  # (case, InvestigationService)
):
    case, service = pair
    hypothesis_ids = (payload.hypothesis_ids if payload else None) or None
    try:
        result = service.investigate_case(case, hypothesis_ids)
    except InvestigationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        status, detail = value_error_status(exc)
        raise HTTPException(status_code=status, detail=detail)
    except RuntimeError as exc:
        # Planner/search provider misconfiguration (e.g. missing API key).
        raise HTTPException(status_code=503, detail=str(exc))

    run = result["run"]
    return InvestigationResponse(
        run=run,
        plans=[plan.to_dict() for plan in result["plans"]],
        evidence_created=len(result["created"]),
        evidence_reused=len(result["reused"]),
        links_created=result["links"],
        gaps=result["gaps"],
    )


@router.get("/investigations/{run_id}", response_model=InvestigationRunRead)
def get_investigation(run=Depends(get_run_or_404)):
    return run


@router.get("/investigations/{run_id}/events", response_model=RunEventsRead)
def get_investigation_events(run=Depends(get_run_or_404)):
    metadata = run.workflow_metadata or {}
    return RunEventsRead(
        run_id=run.id,
        status=run.status,
        search_provider=metadata.get("search_provider"),
        events=metadata.get("events", []),
        gaps=metadata.get("gaps", []),
    )
