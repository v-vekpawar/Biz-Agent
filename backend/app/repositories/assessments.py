"""Assessment repository — APPEND-ONLY by design.

There is intentionally no update() or delete() here: assessments are versioned
history rows. New evidence or an experiment outcome means a NEW version; prior
rationale and status are preserved forever (PRODUCT_SPEC.md §7 principle 7).
Newest version per hypothesis is also reflected on Hypothesis.current_status.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain.enums import HypothesisStatus
from ..domain.models import Hypothesis, HypothesisAssessment
from ._common import coerce_enum


class AssessmentRepository:
    def __init__(self, session: Session):
        self._s = session

    def add(
        self,
        hypothesis_id: int,
        status: Any,
        rationale: str,
        *,
        investigation_run_id: int | None = None,
        supporting_evidence_ids: list[int] | None = None,
        contradicting_evidence_ids: list[int] | None = None,
        evidence_gaps: str | None = None,
        limitations: str | None = None,
        recommended_next_step: str | None = None,
    ) -> HypothesisAssessment:
        hypothesis = self._s.get(Hypothesis, hypothesis_id)
        if hypothesis is None:
            raise ValueError(f"Hypothesis {hypothesis_id} not found.")
        if not rationale or not rationale.strip():
            raise ValueError("rationale must not be empty.")
        version = 1 + (self._s.scalar(
            select(func.max(HypothesisAssessment.version)).where(HypothesisAssessment.hypothesis_id == hypothesis_id)
        ) or 0)

        assessment = HypothesisAssessment(
            hypothesis_id=hypothesis_id,
            investigation_run_id=investigation_run_id,
            version=version,
            status=coerce_enum(status, HypothesisStatus, "status"),
            rationale=rationale,
            supporting_evidence_ids=list(supporting_evidence_ids or []),
            contradicting_evidence_ids=list(contradicting_evidence_ids or []),
            evidence_gaps=evidence_gaps,
            limitations=limitations,
            recommended_next_step=recommended_next_step,
        )
        self._s.add(assessment)
        # Denormalized current status on the hypothesis (history stays intact).
        hypothesis.current_status = assessment.status
        self._s.commit()
        self._s.refresh(assessment)
        return assessment

    def history(self, hypothesis_id: int) -> list[HypothesisAssessment]:
        return list(
            self._s.scalars(
                select(HypothesisAssessment)
                .where(HypothesisAssessment.hypothesis_id == hypothesis_id)
                .order_by(HypothesisAssessment.version)
            )
        )

    def latest(self, hypothesis_id: int) -> HypothesisAssessment | None:
        return self._s.scalar(
            select(HypothesisAssessment)
            .where(HypothesisAssessment.hypothesis_id == hypothesis_id)
            .order_by(HypothesisAssessment.version.desc())
            .limit(1)
        )
