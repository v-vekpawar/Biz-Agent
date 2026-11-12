"""User-entered evidence use cases (Phase 3): manual records + linking.

The USER decides the relationship of their own input piece to the
hypothesis — the system never guesses for user-provided facts.
AI-collected results are linked `neutral` (the collector never classifies;
classification/verification is Phase 4's EvidenceVerifier's job).
"""

from __future__ import annotations

from typing import Any

from ..domain.enums import EvidenceKind, VerificationStatus
from ..domain.models import Evidence, Hypothesis
from ..repositories import EvidenceRepository


class EvidenceService:
    def __init__(self, evidence_repository: EvidenceRepository):
        self._evidence = evidence_repository

    def add_manual(
        self,
        case_id: int,
        hypothesis: Hypothesis,
        data: dict[str, Any],
    ) -> Evidence:
        """Create a user-entered evidence row (kind user_observation by
        default) and link it with the user-declared relationship."""
        row = self._evidence.create(
            case_id,
            source_title=data["source_title"],
            source_url=data.get("source_url"),
            source_type=data.get("source_type") or "manual",
            excerpt=data.get("excerpt") or None,
            finding=data.get("finding"),
            evidence_kind=data.get("evidence_kind") or EvidenceKind.USER_OBSERVATION,
            limitations=data.get("limitations"),
            verification_status=VerificationStatus.UNVERIFIED,
        )
        self._evidence.link(
            hypothesis.id,
            row.id,
            data.get("relationship"),
            data.get("relationship_rationale"),
        )
        return row

    def links_for_hypothesis(self, hypothesis_id: int):
        return self._evidence.links_for_hypothesis(hypothesis_id)

    def unlink(self, hypothesis_id: int, evidence_id: int) -> bool:
        """Remove the link between a hypothesis and an evidence row.
        The evidence row itself is preserved in the register (never deleted)."""
        return self._evidence.unlink(hypothesis_id, evidence_id)
