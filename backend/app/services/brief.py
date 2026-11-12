"""Assemble the data behind the decision-brief PDF (deterministic; no LLM)."""

from __future__ import annotations

import datetime as _dt
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..domain.enums import SprintStatus
from ..domain.models import BusinessCase, User
from ..repositories import AssessmentRepository, EvidenceRepository, HypothesisRepository, SprintRepository
from .riskscan import rank_risks
from .sprints import SprintService, _aware


def _domain(url: str | None) -> str:
    if not url:
        return ""
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def build_brief(session: Session, case: BusinessCase, user: User) -> dict[str, Any]:
    hypotheses = HypothesisRepository(session).list_by_case(case.id)
    assessments = AssessmentRepository(session)
    evidence_repo = EvidenceRepository(session)
    risks = rank_risks(hypotheses, assessments, evidence_repo) if hypotheses else []

    sprints = SprintRepository(session)
    service = SprintService(sprints)
    locked = [s for s in sprints.list_by_case(case.id) if s.locked_at is not None]
    sprint_block: dict[str, Any] | None = None
    if locked:
        s = locked[0]  # newest locked sprint
        verdicts = sprints.list_verdicts(s.id)
        evaluation = verdicts[-1].evaluation if verdicts else service.evaluate(s)
        sprint_block = {
            "status": s.status.value,
            "claim": s.protocol["claim"],
            "audience": s.protocol["audience"],
            "headline": s.content["headline"],
            "deadline": s.protocol["deadline"],
            "locked_at": _aware(s.locked_at),
            "concluded": s.status == SprintStatus.CONCLUDED,
            "protocol_hash": s.protocol_hash,
            "evaluation": evaluation,
        }

    verdict = _verdict(risks, sprint_block)
    evidence_rows = [
        {
            "id": ev.id,
            "title": ev.source_title,
            "domain": _domain(ev.source_url),
            "url": ev.source_url,
            "kind": ev.evidence_kind.value,
            "verification": ev.verification_status.value,
        }
        for ev in evidence_repo.list_by_case(case.id)
    ]
    return {
        "title": case.title,
        "owner": user.display_name,
        "generated_at": _dt.datetime.now(_dt.timezone.utc),
        "idea": case.idea_description,
        "facts": [
            ("For", case.target_customer), ("Problem", case.customer_problem),
            ("Price", case.pricing_model), ("Where", case.geography),
        ],
        "verdict": verdict,
        "risks": risks,
        "sprint": sprint_block,
        "evidence": evidence_rows,
    }


def _verdict(risks: list[dict[str, Any]], sprint: dict[str, Any] | None) -> dict[str, str]:
    if sprint is not None:
        ev = sprint["evaluation"]
        labels = {"go": "GO", "pivot": "PIVOT", "stop": "STOP",
                  "keep_running": "TEST IN PROGRESS", "inconclusive": "INCONCLUSIVE"}
        return {"key": ev["verdict"], "label": labels[ev["verdict"]], "detail": ev["next_step"],
                "basis": "Customer test, decided by the pre-registered rule" if sprint["concluded"]
                else "Customer test, live reading"}
    if risks:
        serious = [r for r in risks if r["level"] in ("critical", "open")]
        return {
            "key": "untested", "label": "NOT TESTED WITH CUSTOMERS",
            "detail": (f"Desk research flagged {len(serious)} assumption{'s' if len(serious) != 1 else ''} as "
                       "critical or open. Desk research can't show that people will sign up or pay: run a customer test."),
            "basis": "Desk research only",
        }
    return {"key": "none", "label": "NOT ASSESSED", "detail": "Run the risk scan to see what is most likely to sink this idea.",
            "basis": "No analysis yet"}
