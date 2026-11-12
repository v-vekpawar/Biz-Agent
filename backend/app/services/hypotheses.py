"""Hypothesis use cases: user CRUD (candidates, never verified facts)."""

from __future__ import annotations

from typing import Any

from ..domain.enums import HypothesisOrigin
from ..domain.models import BusinessCase, Hypothesis
from ..repositories import HypothesisRepository


class HypothesisService:
    def __init__(self, hypothesis_repository: HypothesisRepository):
        self._hypotheses = hypothesis_repository

    def add_user_hypothesis(self, case: BusinessCase, data: dict[str, Any]) -> Hypothesis:
        return self._hypotheses.create(
            case.id,
            data["statement"],
            category=data.get("category"),
            rationale=data.get("rationale"),
            customer_segment=data.get("customer_segment"),
            geography=data.get("geography"),
            priority=data.get("priority"),
            testability_notes=data.get("testability_notes"),
            origin=HypothesisOrigin.USER,
        )

    def update(self, hypothesis_id: int, fields: dict[str, Any]) -> Hypothesis:
        return self._hypotheses.update(hypothesis_id, fields)

    def delete(self, hypothesis_id: int) -> bool:
        return self._hypotheses.delete(hypothesis_id)

    def list_for_case(self, case_id: int) -> list[Hypothesis]:
        return self._hypotheses.list_by_case(case_id)
