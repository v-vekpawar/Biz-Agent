"""InvestigationRun repository with explicit status transitions (deterministic
code, per SYSTEM_DESIGN.md §7)."""

from __future__ import annotations

from typing import Any
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.enums import RunStatus
from ..domain.models import InvestigationRun
from ._common import coerce_enum


class RunRepository:
    def __init__(self, session: Session):
        self._s = session

    def create(self, business_case_id: int, requested_scope: dict | None = None) -> InvestigationRun:
        run = InvestigationRun(
            business_case_id=business_case_id,
            requested_scope=requested_scope,
        )
        self._s.add(run)
        self._s.commit()
        self._s.refresh(run)
        return run

    def get(self, run_id: int) -> InvestigationRun | None:
        return self._s.get(InvestigationRun, run_id)

    def require(self, run_id: int) -> InvestigationRun:
        run = self.get(run_id)
        if run is None:
            raise ValueError(f"Investigation run {run_id} not found.")
        return run

    def list_by_case(self, business_case_id: int) -> list[InvestigationRun]:
        return list(
            self._s.scalars(
                select(InvestigationRun)
                .where(InvestigationRun.business_case_id == business_case_id)
                .order_by(InvestigationRun.started_at.desc())
            )
        )

    def _transition(self, run: InvestigationRun, *, allowed: frozenset[RunStatus], action: str) -> None:
        if run.status not in allowed:
            status_name = getattr(run.status, "value", run.status)
            raise ValueError(
                f"Cannot {action}: run {run.id} is in status '{status_name}'"
                f" (allowed from: {', '.join(s.value for s in sorted(allowed))})."
            )

    def start(self, run_id: int) -> InvestigationRun:
        """queued -> running."""
        run = self.require(run_id)
        self._transition(run, allowed=frozenset({RunStatus.QUEUED}), action="start")
        run.status = RunStatus.RUNNING
        run.started_at = run.started_at or datetime.now(timezone.utc)
        self._s.commit()
        self._s.refresh(run)
        return run

    def complete(
        self,
        run_id: int,
        *,
        with_gaps: bool = False,
        workflow_metadata: dict | None = None,
        error_summary: str | None = None,
    ) -> InvestigationRun:
        """running -> completed | completed_with_gaps."""
        run = self.require(run_id)
        self._transition(run, allowed=frozenset({RunStatus.RUNNING}), action="complete")
        run.status = RunStatus.COMPLETED_WITH_GAPS if with_gaps else RunStatus.COMPLETED
        run.finished_at = datetime.now(timezone.utc)
        if workflow_metadata:
            run.workflow_metadata = {**(run.workflow_metadata or {}), **workflow_metadata}
        if error_summary:
            run.error_summary = error_summary
        self._s.commit()
        self._s.refresh(run)
        return run

    def fail(self, run_id: int, error_summary: str) -> InvestigationRun:
        """queued|running -> failed. Failure carries a persisted error summary."""
        run = self.require(run_id)
        self._transition(run, allowed=frozenset({RunStatus.QUEUED, RunStatus.RUNNING}), action="fail")
        run.status = RunStatus.FAILED
        run.error_summary = error_summary
        run.finished_at = datetime.now(timezone.utc)
        self._s.commit()
        self._s.refresh(run)
        return run

    def merge_metadata(self, run_id: int, metadata: dict) -> InvestigationRun:
        """Deep-merge extra keys into workflow_metadata (any status; metadata
        is diagnostics, not lifecycle)."""
        run = self.require(run_id)
        if metadata:
            run.workflow_metadata = {**(run.workflow_metadata or {}), **metadata}
        self._s.commit()
        self._s.refresh(run)
        return run

    def set_status(self, run_id: int, status: Any) -> InvestigationRun:
        """Explicit status set for non-standard needs (still validated enum),
        bypassing transition guards. Prefer start/complete/fail."""
        run = self.require(run_id)
        run.status = coerce_enum(status, RunStatus, "status")
        self._s.commit()
        self._s.refresh(run)
        return run
