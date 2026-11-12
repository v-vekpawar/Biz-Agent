"""Evidence repository + hypothesis<->evidence link management.

Cross-scoping rule: a link can only join evidence and a hypothesis that belong
to the SAME business case (records must belong to the correct case; never leak
evidence between cases).
"""

from __future__ import annotations

from typing import Any
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.enums import EvidenceKind, EvidenceRelationship, VerificationStatus
from ..domain.models import Evidence, Hypothesis, HypothesisEvidence
from ._common import coerce_enum


class EvidenceRepository:
    def __init__(self, session: Session):
        self._s = session

    def create(
        self,
        business_case_id: int,
        source_title: str,
        *,
        source_url: str | None = None,
        source_type: str | None = None,
        publisher: str | None = None,
        author: str | None = None,
        published_at: str | None = None,
        retrieved_at: Any = None,
        excerpt: str | None = None,
        finding: str | None = None,
        evidence_kind: Any = EvidenceKind.INDIRECT,
        relevance_assessment: str | None = None,
        reliability_assessment: str | None = None,
        limitations: str | None = None,
        verification_status: Any = VerificationStatus.UNVERIFIED,
    ) -> Evidence:
        if not source_title or not source_title.strip():
            raise ValueError("source_title must not be empty.")
        evidence = Evidence(
            business_case_id=business_case_id,
            source_title=source_title,
            source_url=source_url,
            source_type=source_type,
            publisher=publisher,
            author=author,
            published_at=published_at,
            retrieved_at=retrieved_at or datetime.now(timezone.utc),
            excerpt=excerpt,
            finding=finding,
            evidence_kind=coerce_enum(evidence_kind, EvidenceKind, "evidence_kind"),
            relevance_assessment=relevance_assessment,
            reliability_assessment=reliability_assessment,
            limitations=limitations,
            verification_status=coerce_enum(verification_status, VerificationStatus, "verification_status"),
        )
        self._s.add(evidence)
        self._s.commit()
        self._s.refresh(evidence)
        return evidence

    def get(self, evidence_id: int) -> Evidence | None:
        return self._s.get(Evidence, evidence_id)

    def require(self, evidence_id: int) -> Evidence:
        evidence = self.get(evidence_id)
        if evidence is None:
            raise ValueError(f"Evidence {evidence_id} not found.")
        return evidence

    def list_by_case(self, business_case_id: int) -> list[Evidence]:
        return list(
            self._s.scalars(
                select(Evidence).where(Evidence.business_case_id == business_case_id).order_by(Evidence.created_at)
            )
        )

    def update(self, evidence_id: int, fields: dict[str, Any]) -> Evidence:
        evidence = self.require(evidence_id)
        allowed = {
            "source_title", "source_url", "source_type", "publisher", "author",
            "published_at", "excerpt", "finding", "evidence_kind",
            "relevance_assessment", "reliability_assessment", "limitations",
            "verification_status",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown evidence field(s): {sorted(unknown)}")
        if "evidence_kind" in fields:
            fields["evidence_kind"] = coerce_enum(fields["evidence_kind"], EvidenceKind, "evidence_kind")
        if "verification_status" in fields:
            fields["verification_status"] = coerce_enum(fields["verification_status"], VerificationStatus, "verification_status")
        for field, value in fields.items():
            setattr(evidence, field, value)
        self._s.commit()
        self._s.refresh(evidence)
        return evidence

    def link(
        self,
        hypothesis_id: int,
        evidence_id: int,
        relationship: Any,
        rationale: str | None = None,
    ) -> HypothesisEvidence:
        relationship = coerce_enum(relationship, EvidenceRelationship, "relationship")
        hypothesis = self._s.get(Hypothesis, hypothesis_id)
        if hypothesis is None:
            raise ValueError(f"Hypothesis {hypothesis_id} not found.")
        evidence = self.get(evidence_id)
        if evidence is None:
            raise ValueError(f"Evidence {evidence_id} not found.")
        if hypothesis.business_case_id != evidence.business_case_id:
            raise ValueError(
                "Hypothesis and evidence belong to different business cases "
                f"(hypothesis case={hypothesis.business_case_id}, evidence case={evidence.business_case_id})."
            )
        existing = self._s.scalar(
            select(HypothesisEvidence).where(
                HypothesisEvidence.hypothesis_id == hypothesis_id,
                HypothesisEvidence.evidence_id == evidence_id,
            )
        )
        if existing is not None:
            # Update relationship/rationale instead of creating a duplicate pair.
            existing.relationship = relationship
            existing.relationship_rationale = rationale
            self._s.commit()
            self._s.refresh(existing)
            return existing
        link = HypothesisEvidence(
            hypothesis_id=hypothesis_id,
            evidence_id=evidence_id,
            relationship=relationship,
            relationship_rationale=rationale,
        )
        self._s.add(link)
        self._s.commit()
        self._s.refresh(link)
        return link

    def unlink(self, hypothesis_id: int, evidence_id: int) -> bool:
        link = self._s.scalar(
            select(HypothesisEvidence).where(
                HypothesisEvidence.hypothesis_id == hypothesis_id,
                HypothesisEvidence.evidence_id == evidence_id,
            )
        )
        if link is None:
            return False
        self._s.delete(link)
        self._s.commit()
        return True

    def links_for_hypothesis(self, hypothesis_id: int) -> list[tuple[Evidence, HypothesisEvidence]]:
        """Return (evidence, link) pairs for one hypothesis."""
        pairs = self._s.execute(
            select(Evidence, HypothesisEvidence)
            .join(HypothesisEvidence, HypothesisEvidence.evidence_id == Evidence.id)
            .where(HypothesisEvidence.hypothesis_id == hypothesis_id)
            .order_by(HypothesisEvidence.created_at)
        ).all()
        return [(evidence, link) for evidence, link in pairs]

    def links_for_evidence(self, evidence_id: int) -> list[tuple[Evidence, HypothesisEvidence]]:
        """Return (evidence, link) pairs for one evidence row (each link is one
        hypothesis classification)."""
        pairs = self._s.execute(
            select(Evidence, HypothesisEvidence)
            .join(HypothesisEvidence, HypothesisEvidence.evidence_id == Evidence.id)
            .where(HypothesisEvidence.evidence_id == evidence_id)
            .order_by(HypothesisEvidence.created_at)
        ).all()
        return [(evidence, link) for evidence, link in pairs]
