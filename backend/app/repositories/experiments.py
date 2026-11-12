"""Experiment + ExperimentOutcome repository. Outcomes are append-only
records; nothing here overwrites prior outcomes."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.enums import CriteriaResult, ExperimentStatus
from ..domain.models import Experiment, ExperimentOutcome
from ._common import coerce_enum

_FIELDS = (
    "title",
    "objective",
    "method",
    "target_participants",
    "recruitment_approach",
    "resources",
    "estimated_duration",
    "estimated_cost",
    "cost_assumptions",
    "success_criteria",
    "failure_criteria",
    "data_to_collect",
    "risks",
    "status",
)

_OUTCOME_FIELDS = (
    "recorded_at",
    "actual_dates",
    "participant_count",
    "participant_type",
    "observations",
    "measurements",
    "notes_quotes",
    "criteria_result",
    "user_interpretation",
    "attachment_references",
)


class ExperimentRepository:
    def __init__(self, session: Session):
        self._s = session

    def create(
        self,
        business_case_id: int,
        title: str,
        hypothesis_id: int | None = None,
        **fields: Any,
    ) -> Experiment:
        if not title or not title.strip():
            raise ValueError("title must not be empty.")
        unknown = set(fields) - set(_FIELDS)
        if unknown:
            raise ValueError(f"Unknown experiment field(s): {sorted(unknown)}")
        experiment = Experiment(
            business_case_id=business_case_id,
            title=title,
            hypothesis_id=hypothesis_id,
            status=coerce_enum(fields.pop("status", ExperimentStatus.PROPOSED), ExperimentStatus, "status"),
        )
        for field, value in fields.items():
            setattr(experiment, field, value)
        self._s.add(experiment)
        self._s.commit()
        self._s.refresh(experiment)
        return experiment

    def get(self, experiment_id: int) -> Experiment | None:
        return self._s.get(Experiment, experiment_id)

    def require(self, experiment_id: int) -> Experiment:
        experiment = self.get(experiment_id)
        if experiment is None:
            raise ValueError(f"Experiment {experiment_id} not found.")
        return experiment

    def list_by_case(self, business_case_id: int) -> list[Experiment]:
        return list(
            self._s.scalars(
                select(Experiment).where(Experiment.business_case_id == business_case_id).order_by(Experiment.created_at)
            )
        )

    def list_by_hypothesis(self, hypothesis_id: int) -> list[Experiment]:
        return list(
            self._s.scalars(
                select(Experiment).where(Experiment.hypothesis_id == hypothesis_id).order_by(Experiment.created_at)
            )
        )

    def update(self, experiment_id: int, fields: dict[str, Any]) -> Experiment:
        experiment = self.require(experiment_id)
        unknown = set(fields) - set(_FIELDS)
        if unknown:
            raise ValueError(f"Unknown experiment field(s): {sorted(unknown)}")
        if "title" in fields and (not fields["title"] or not str(fields["title"]).strip()):
            raise ValueError("title must not be empty.")
        if "status" in fields:
            fields["status"] = coerce_enum(fields["status"], ExperimentStatus, "status")
        for field, value in fields.items():
            setattr(experiment, field, value)
        self._s.commit()
        self._s.refresh(experiment)
        return experiment

    def delete(self, experiment_id: int) -> bool:
        experiment = self.get(experiment_id)
        if experiment is None:
            return False
        self._s.delete(experiment)
        self._s.commit()
        return True

    # --- outcomes -----------------------------------------------------------

    def add_outcome(self, experiment_id: int, **fields: Any) -> ExperimentOutcome:
        experiment = self.require(experiment_id)
        outcome = ExperimentOutcome(experiment_id=experiment_id)
        unknown = set(fields) - set(_OUTCOME_FIELDS)
        if unknown:
            raise ValueError(f"Unknown experiment-outcome field(s): {sorted(unknown)}")
        for field, value in fields.items():
            if field == "criteria_result" and value is not None:
                value = coerce_enum(value, CriteriaResult, "criteria_result")
            setattr(outcome, field, value)
        # Record against the experiment's hypothesis tie-in (kept immutable via FK).
        if experiment.hypothesis_id is None:
            raise ValueError(f"Experiment {experiment_id} has no linked hypothesis; outcomes need the hypothesis context.")
        self._s.add(outcome)
        self._s.commit()
        self._s.refresh(outcome)
        return outcome

    def list_outcomes(self, experiment_id: int) -> list[ExperimentOutcome]:
        return list(
            self._s.scalars(
                select(ExperimentOutcome)
                .where(ExperimentOutcome.experiment_id == experiment_id)
                .order_by(ExperimentOutcome.recorded_at)
            )
        )
