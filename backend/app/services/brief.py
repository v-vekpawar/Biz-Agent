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


def build_decisions(data: dict[str, Any]) -> list[dict[str, str]]:
    """The founder's action list, derived deterministically from the same data
    as the PDF (verdict, ranked risks, sprint evaluation). No LLM: every
    decision traces back to a count or a locked rule."""
    decisions: list[dict[str, str]] = []

    def add(priority: str, title: str, detail: str, tag: str) -> None:
        decisions.append({"priority": priority, "title": title, "detail": detail, "tag": tag})

    sprint = data["sprint"]
    risks = data["risks"]
    verdict = data["verdict"]

    if sprint is None:
        if not risks:
            add("now", "Run the risk scan", verdict["detail"], "scan")
            return decisions
        top = next((r for r in risks if r["sprint_testable"] and r["level"] != "low"), risks[0])
        add("now", "Test your riskiest assumption with real people",
            f"\u201c{top['statement']}\u201d Set up a customer test page for it — desk research can rank risks, "
            "but only real people responding can show demand.", "test")
        serious = [r for r in risks if r["level"] in ("critical", "open")][:3]
        if serious:
            add("next", "Keep these questions open as you research",
                "The scan could not settle: " + "; ".join(r["statement"] for r in serious) + ".", "research")
        add("later", "Re-run the scan when you learn something new",
            "New evidence changes the ranking. Scans are free to re-run; old assessments stay in the history.", "scan")
        return decisions

    evaluation = sprint["evaluation"]
    verdict_key = evaluation["verdict"]
    finished = evaluation["finished"]
    counts = evaluation["counts"]
    primary = next((m for m in evaluation["metrics"] if m["role"] == "primary"), None)

    if verdict_key == "keep_running":
        missing = max(0, primary["min_sample"] - primary["trials"]) if primary else 0
        if missing > 0:
            add("now", f"Drive about {missing} more {primary['trial_unit']} to your page",
                "The locked rule cannot call the test before the minimum sample. Share the page link where your "
                "audience already gathers — one channel at a time, and keep the ?s= tags so you can compare them.", "traffic")
        else:
            add("now", "Keep collecting — the range still overlaps a threshold",
                evaluation["next_step"], "wait")
        add("next", "Log every conversation you have",
            "A commitment (pre-order, paid pilot, booked follow-up) counts towards the supporting metric; "
            "polite interest does not.", "log")
        if not finished:
            add("later", f"Decision day is {sprint['deadline']} (end of day, UTC)",
                "When the window closes, the rule reads the data exactly as pre-registered.", "deadline")
    elif verdict_key == "go":
        add("now", "Raise the commitment",
            "The data clears the bar you set before the test. Don't celebrate yet: run the next test where people "
            "give money or real time — a paid pilot, a pre-order, a booked session.", "commit")
        add("next", "Talk to the people who signed up",
            f"{counts['signups']} people gave you their email (see the test tab). Ask what they would need to "
            "become paying customers today.", "interview")
    elif verdict_key == "pivot":
        add("now", "Change one thing and re-test",
            "There is pull, but below your target. Change the segment, the promise or the price — one variable — "
            "then write a new protocol and test again. Don't relax this rule after the fact.", "pivot")
        add("next", "Study who did respond",
            f"{counts['signups']} people signed up anyway. What do they share? They are the seed of the sharper "
            "version.", "learn")
    elif verdict_key == "stop":
        add("now", "Stop pursuing this version",
            "The data credibly misses your floor. Stop here, or change the idea fundamentally — re-running the "
            "same test hoping for a different answer is not a new test.", "stop")
        add("next", "Keep the evidence",
            "The brief and the dossier document why you stopped — that record makes the next idea easier to "
            "judge.", "evidence")
    else:  # inconclusive
        add("now", "Run a sharper test",
            "The window closed without a clear answer: more traffic, a narrower audience, or a clearer call to "
            "action. Same claim, new protocol.", "retest")

    if finished and verdict_key in ("go", "pivot", "stop"):
        add("later", "Share the evidence",
            "Export the decision brief (PDF) and turn on the shareable dossier for mentors, partners or "
            "investors.", "share")
    return decisions
