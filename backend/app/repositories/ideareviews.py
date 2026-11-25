"""Idea review repository: one advisory AI review per business case.

Re-running the review replaces the stored row (the review reflects the idea
as currently written; it is not an audit log — that is what assessments are).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.models import BusinessCase, IdeaReview


class IdeaReviewRepository:
    def __init__(self, session: Session):
        self._s = session

    def get_for_case(self, business_case_id: int) -> IdeaReview | None:
        return self._s.scalar(
            select(IdeaReview).where(IdeaReview.business_case_id == business_case_id)
        )

    def upsert(self, case: BusinessCase, result: dict, meta: dict | None) -> IdeaReview:
        row = self.get_for_case(case.id)
        if row is None:
            row = IdeaReview(business_case_id=case.id, result=result, meta=meta)
            self._s.add(row)
        else:
            row.result = result
            row.meta = meta
        self._s.commit()
        self._s.refresh(row)
        return row
