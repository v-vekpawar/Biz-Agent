"""Scan job repository (state machine: queued -> running -> completed|failed)."""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.enums import ScanStatus
from ..domain.models import ScanJob


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class ScanRepository:
    def __init__(self, session: Session):
        self._s = session

    def create(self, case_id: int) -> ScanJob:
        job = ScanJob(business_case_id=case_id, status=ScanStatus.QUEUED, progress=0, log=[], warnings=[])
        self._s.add(job)
        self._s.commit()
        self._s.refresh(job)
        return job

    def get(self, job_id: int) -> ScanJob | None:
        return self._s.get(ScanJob, job_id)

    def latest_for_case(self, case_id: int) -> ScanJob | None:
        return self._s.scalar(
            select(ScanJob).where(ScanJob.business_case_id == case_id).order_by(ScanJob.id.desc()).limit(1)
        )

    def active_for_case(self, case_id: int) -> ScanJob | None:
        return self._s.scalar(
            select(ScanJob)
            .where(ScanJob.business_case_id == case_id, ScanJob.status.in_([ScanStatus.QUEUED, ScanStatus.RUNNING]))
            .limit(1)
        )

    def start(self, job: ScanJob) -> None:
        job.status = ScanStatus.RUNNING
        self._s.commit()

    def progress(self, job: ScanJob, step: str, progress: int, message: str | None = None) -> None:
        job.step = step
        job.progress = max(job.progress or 0, min(100, progress))
        if message:
            job.log = [*(job.log or []), {"at": _now().isoformat(), "step": step, "message": message}]
        self._s.commit()

    def warn(self, job: ScanJob, message: str) -> None:
        job.warnings = [*(job.warnings or []), message]
        self._s.commit()

    def complete(self, job: ScanJob, result: dict) -> None:
        job.status = ScanStatus.COMPLETED
        job.progress = 100
        job.step = "done"
        job.result = result
        job.finished_at = _now()
        self._s.commit()

    def fail(self, job: ScanJob, error: str) -> None:
        job.status = ScanStatus.FAILED
        job.error = error[:2000]
        job.finished_at = _now()
        self._s.commit()

    def fail_interrupted(self) -> int:
        """Called at startup: a job that was queued/running when the process
        died can never finish, so mark it failed instead of leaving it spinning."""
        rows = list(self._s.scalars(select(ScanJob).where(ScanJob.status.in_([ScanStatus.QUEUED, ScanStatus.RUNNING]))))
        for job in rows:
            job.status = ScanStatus.FAILED
            job.error = "The server restarted while this scan was running. Start the scan again."
            job.finished_at = _now()
        if rows:
            self._s.commit()
        return len(rows)
