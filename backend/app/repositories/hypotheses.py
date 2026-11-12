"""Hypothesis repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.enums import HypothesisCategory, HypothesisOrigin, HypothesisStatus
from ..domain.models import Hypothesis
from ._common import coerce_enum

_FIELDS = (
    "statement",
    "category",
    "rationale",
    "customer_segment",
    "geography",
    "priority",
    "testability_notes",
    "current_status",
)


class HypothesisRepository:
    def __init__(self, session: Session):
        self._s = session

    def create(
        self,
        business_case_id: int,
        statement: str,
        *,
        category: Any = HypothesisCategory.OTHER,
        rationale: str | None = None,
        customer_segment: str | None = None,
        geography: str | None = None,
        priority: str | None = None,
        testability_notes: str | None = None,
        current_status: Any = HypothesisStatus.UNKNOWN,
        origin: Any = HypothesisOrigin.USER,
    ) -> Hypothesis:
        if not statement or not statement.strip():
            raise ValueError("statement must not be empty.")
        hypothesis = Hypothesis(
            business_case_id=business_case_id,
            statement=statement,
            category=coerce_enum(category, HypothesisCategory, "category"),
            rationale=rationale,
            customer_segment=customer_segment,
            geography=geography,
            priority=priority,
            testability_notes=testability_notes,
            current_status=coerce_enum(current_status, HypothesisStatus, "current_status"),
            origin=coerce_enum(origin, HypothesisOrigin, "origin"),
        )
        self._s.add(hypothesis)
        try:
            self._s.commit()
        except Exception:
            self._s.rollback()
            raise
        self._s.refresh(hypothesis)
        return hypothesis

    def get(self, hypothesis_id: int) -> Hypothesis | None:
        return self._s.get(Hypothesis, hypothesis_id)

    def require(self, hypothesis_id: int) -> Hypothesis:
        hypothesis = self.get(hypothesis_id)
        if hypothesis is None:
            raise ValueError(f"Hypothesis {hypothesis_id} not found.")
        return hypothesis

    def list_by_case(self, business_case_id: int, ordered: bool = True) -> list[Hypothesis]:
        query = select(Hypothesis).where(Hypothesis.business_case_id == business_case_id)
        if ordered:
            query = query.order_by(Hypothesis.created_at)
        return list(self._s.scalars(query))

    def update(self, hypothesis_id: int, fields: dict[str, Any]) -> Hypothesis:
        hypothesis = self.require(hypothesis_id)
        unknown = set(fields) - set(_FIELDS)
        if unknown:
            raise ValueError(f"Unknown hypothesis field(s): {sorted(unknown)}")
        if "statement" in fields and (not fields["statement"] or not str(fields["statement"]).strip()):
            raise ValueError("statement must not be empty.")
        if "category" in fields:
            fields["category"] = coerce_enum(fields["category"], HypothesisCategory, "category")
        if "current_status" in fields:
            fields["current_status"] = coerce_enum(fields["current_status"], HypothesisStatus, "current_status")
        for field, value in fields.items():
            setattr(hypothesis, field, value)
        self._s.commit()
        self._s.refresh(hypothesis)
        return hypothesis

    def delete(self, hypothesis_id: int) -> bool:
        hypothesis = self.get(hypothesis_id)
        if hypothesis is None:
            return False
        self._s.delete(hypothesis)
        self._s.commit()
        return True
