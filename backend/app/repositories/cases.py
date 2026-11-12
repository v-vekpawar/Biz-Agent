"""BusinessCase repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.models import BusinessCase

_TEXT_FIELDS = (
    "geography",
    "target_customer",
    "customer_problem",
    "proposed_solution",
    "business_stage",
    "pricing_model",
    "budget_constraints",
    "known_competitors",
    "user_questions",
)


class CaseRepository:
    def __init__(self, session: Session):
        self._s = session

    def create(self, title: str, idea_description: str, owner_id: int | None = None, **optional: Any) -> BusinessCase:
        if not title or not title.strip():
            raise ValueError("title must not be empty.")
        if not idea_description or not idea_description.strip():
            raise ValueError("idea_description must not be empty.")
        case = BusinessCase(title=title.strip(), idea_description=idea_description.strip(), owner_id=owner_id)
        unknown = set(optional) - set(_TEXT_FIELDS)
        if unknown:
            raise ValueError(f"Unknown business-case field(s): {sorted(unknown)}")
        for field in _TEXT_FIELDS:
            setattr(case, field, optional.get(field))
        self._s.add(case)
        self._s.commit()
        self._s.refresh(case)
        return case

    def get(self, case_id: int) -> BusinessCase | None:
        return self._s.get(BusinessCase, case_id)

    def require(self, case_id: int) -> BusinessCase:
        case = self.get(case_id)
        if case is None:
            raise ValueError(f"Business case {case_id} not found.")
        return case

    def list(self, owner_id: int | None = None) -> list[BusinessCase]:
        query = select(BusinessCase).order_by(BusinessCase.created_at.desc(), BusinessCase.id.desc())
        if owner_id is not None:
            query = query.where(BusinessCase.owner_id == owner_id)
        return list(self._s.scalars(query))

    def update(self, case_id: int, fields: dict[str, Any], clear_fields: frozenset[str] | frozenset = frozenset()) -> BusinessCase:
        case = self.require(case_id)
        allowed = {"title", "idea_description", *_TEXT_FIELDS}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown business-case field(s): {sorted(unknown)}")
        for field, value in fields.items():
            if field == "title" and (not value or not str(value).strip()):
                raise ValueError("title must not be empty.")
            if field == "idea_description" and (not value or not str(value).strip()):
                raise ValueError("idea_description must not be empty.")
            setattr(case, field, value)
        for field in clear_fields:
            if field not in allowed:
                raise ValueError(f"Unknown business-case field: {field}")
            setattr(case, field, None)
        self._s.commit()
        self._s.refresh(case)
        return case

    def delete(self, case_id: int) -> bool:
        case = self.get(case_id)
        if case is None:
            return False
        self._s.delete(case)
        self._s.commit()
        return True
