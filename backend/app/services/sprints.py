"""
Validation sprint use cases.

A sprint pre-registers ONE claim and ONE decision rule, hosts a public test
page, collects real signals, and computes the verdict with code (services/stats).

Integrity rules enforced here:
- Locking freezes page copy + protocol and stores a sha256 of both.
- After the deadline (or once concluded/paused) the public page stops
  collecting data, so the sample cannot be extended past the registered window.
- Verdicts are computed, never written by an LLM; each conclusion stores an
  immutable snapshot of its inputs.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from typing import Any

from ..core.security import is_valid_email, normalize_email, visitor_hash
from ..domain.enums import MetricKey, SprintStatus, Verdict
from ..domain.models import Sprint
from ..repositories import SprintRepository
from . import stats

MAX_SPRINT_DAYS = 90


class SprintConflict(ValueError):
    """The action is not allowed in the sprint's current state (HTTP 409)."""


class SprintClosed(ValueError):
    """The public test page is not accepting data (HTTP 410/404)."""


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def protocol_hash(content: dict, protocol: dict) -> str:
    return hashlib.sha256(canonical_json({"content": content, "protocol": protocol}).encode("utf-8")).hexdigest()


def deadline_at(protocol: dict) -> _dt.datetime:
    """End of the deadline day, UTC."""
    day = _dt.date.fromisoformat(protocol["deadline"])
    return _dt.datetime.combine(day, _dt.time(23, 59, 59), tzinfo=_dt.timezone.utc)


def _aware(value: _dt.datetime | None) -> _dt.datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=_dt.timezone.utc)
    return value


def clean_channel(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"[^a-z0-9_-]", "", value.lower())[:50]
    return value or None


NEXT_STEP = {
    Verdict.GO: (
        "The data clears the bar you set before the test. Don't celebrate yet: raise the commitment. "
        "Run a test where people give money or real time (paid pilot, pre-order, booked session)."
    ),
    Verdict.PIVOT: (
        "There is some pull, but below your target. Change one thing (segment, price or promise), write a new "
        "protocol, and test again. Don't relax this one after the fact."
    ),
    Verdict.STOP: (
        "The data credibly misses your floor. Stop, or change the idea fundamentally. Re-running the same test "
        "hoping for a different answer is not a new test."
    ),
    Verdict.INCONCLUSIVE: (
        "The test ended without a clear answer. Start a new sprint on the same claim with more traffic or a "
        "sharper audience, or reconsider whether the claim is testable this way."
    ),
}


class SprintService:
    def __init__(self, sprints: SprintRepository):
        self._r = sprints

    # ---- definition ---------------------------------------------------
    def create_draft(self, case_id: int, content: dict, protocol: dict, *, hypothesis_id: int | None = None,
                     kit: dict | None = None, source: str = "manual") -> Sprint:
        return self._r.create(case_id, content, protocol, hypothesis_id=hypothesis_id, kit=kit, source=source)

    def lock(self, sprint: Sprint, *, acknowledge_public_page: bool, acknowledge_frozen: bool) -> Sprint:
        if sprint.status != SprintStatus.DRAFT:
            raise SprintConflict("This sprint is already locked.")
        if not (acknowledge_public_page and acknowledge_frozen):
            raise ValueError(
                "Confirm both statements before locking: the page will be public with your name and contact "
                "email, and the page and decision rule can't be changed afterwards."
            )
        today = _utcnow().date()
        deadline = _dt.date.fromisoformat(sprint.protocol["deadline"])
        if deadline <= today:
            raise ValueError("The deadline must be a future date.")
        if (deadline - today).days > MAX_SPRINT_DAYS:
            raise ValueError(f"The deadline can be at most {MAX_SPRINT_DAYS} days away.")
        return self._r.lock(sprint, protocol_hash(sprint.content, sprint.protocol))

    def pause(self, sprint: Sprint) -> Sprint:
        return self._guard(lambda: self._r.set_running_state(sprint, SprintStatus.PAUSED))

    def resume(self, sprint: Sprint) -> Sprint:
        if self.is_past_deadline(sprint):
            raise SprintConflict("The deadline has passed; the sprint can't collect more data.")
        return self._guard(lambda: self._r.set_running_state(sprint, SprintStatus.RUNNING))

    @staticmethod
    def _guard(action):
        try:
            return action()
        except ValueError as exc:
            raise SprintConflict(str(exc)) from exc

    # ---- state helpers --------------------------------------------------
    @staticmethod
    def is_past_deadline(sprint: Sprint, now: _dt.datetime | None = None) -> bool:
        return (now or _utcnow()) > deadline_at(sprint.protocol)

    def accepting_data(self, sprint: Sprint, now: _dt.datetime | None = None) -> bool:
        return sprint.status == SprintStatus.RUNNING and not self.is_past_deadline(sprint, now)

    # ---- public collection ----------------------------------------------
    def record_visit(self, sprint: Sprint, vid: str, channel: str | None) -> bool:
        if not self.accepting_data(sprint):
            raise SprintClosed("This test is not collecting responses.")
        return self._r.record_visit(sprint.id, visitor_hash(sprint.slug, vid), clean_channel(channel))

    def record_signup(self, sprint: Sprint, *, vid: str, email: str, answer: str | None, consent: bool,
                      channel: str | None, honeypot: str | None) -> bool:
        """True if a new signup was stored. Honeypot hits return False silently."""
        if not self.accepting_data(sprint):
            raise SprintClosed("This test is not collecting responses.")
        if honeypot:
            return False
        if not consent:
            raise ValueError("Please confirm you agree to be contacted about this test.")
        email = normalize_email(email)
        if not is_valid_email(email):
            raise ValueError("Enter a valid email address.")
        answer = (answer or "").strip()[:1000] or None
        vhash = visitor_hash(sprint.slug, vid)
        channel = clean_channel(channel)
        self._r.record_visit(sprint.id, vhash, channel)  # a signup is always a visit
        _, created = self._r.record_signup(sprint.id, vhash, email, answer, channel)
        return created

    # ---- evaluation -------------------------------------------------------
    def evaluate(self, sprint: Sprint, *, finished: bool | None = None) -> dict[str, Any]:
        if sprint.locked_at is None:
            raise SprintConflict("Lock the sprint first: there is no decision rule until it is pre-registered.")
        protocol = sprint.protocol
        counts = self._r.counts(sprint.id)
        if finished is None:
            finished = sprint.status == SprintStatus.CONCLUDED or self.is_past_deadline(sprint)

        metrics: list[dict[str, Any]] = []
        for spec in protocol["metrics"]:
            key = spec["key"]
            label, success_unit, trial_unit = stats.METRIC_LABELS[key]
            if key == MetricKey.WAITLIST_CONVERSION.value:
                k = counts["signups"]
                n = max(counts["visitors"], k)
            else:
                k, n = counts["committed"], counts["interviews"]
            row = stats.evaluate_metric(
                k, n,
                success_rate=spec["success_rate"], failure_rate=spec["failure_rate"],
                min_sample=spec["min_sample"], confidence=protocol["confidence"],
                finished=finished, unit=trial_unit,
            )
            row.update({"key": key, "label": label, "role": spec["role"],
                        "success_unit": success_unit, "trial_unit": trial_unit})
            metrics.append(row)

        primary = next(m for m in metrics if m["role"] == "primary")
        supporting = [m for m in metrics if m["role"] != "primary"]
        verdict, notes = stats.combine(primary, supporting)

        decisive = verdict in (Verdict.GO, Verdict.PIVOT, Verdict.STOP)
        if decisive and not finished:
            notes.append(
                "This reading is before your deadline. Stopping at the first favourable look raises the chance of "
                "a false positive, so treat an early call with care."
            )
        if not finished:
            counts_missing = max(0, primary["min_sample"] - primary["trials"])
        else:
            counts_missing = 0

        deadline = _dt.date.fromisoformat(protocol["deadline"])
        days_left = None if finished else max(0, (deadline - _utcnow().date()).days)
        return {
            "verdict": verdict.value,
            "finished": finished,
            "notes": notes,
            "next_step": self.next_step(verdict, primary, counts_missing),
            "metrics": metrics,
            "counts": counts,
            "deadline": protocol["deadline"],
            "days_left": days_left,
            "evaluated_at": _utcnow().isoformat(),
        }

    @staticmethod
    def next_step(verdict: Verdict, primary: dict[str, Any], missing: int) -> str:
        if verdict == Verdict.KEEP_RUNNING:
            if missing > 0:
                return (f"Keep the test running. You need about {missing} more {primary['trial_unit']} "
                        f"before the rule can call it. Drive traffic to the page; don't change anything.")
            return ("The range still overlaps one of your thresholds. Keep collecting data until the deadline; "
                    "don't change the page or the rule.")
        return NEXT_STEP[verdict]

    def conclude(self, sprint: Sprint, *, force: bool = False):
        if sprint.locked_at is None:
            raise SprintConflict("Lock the sprint before concluding it.")
        if sprint.status not in (SprintStatus.RUNNING, SprintStatus.PAUSED):
            raise SprintConflict("This sprint is already concluded.")
        past_deadline = self.is_past_deadline(sprint)
        live = self.evaluate(sprint, finished=past_deadline)
        if live["verdict"] == Verdict.KEEP_RUNNING.value and not force:
            raise SprintConflict(
                "There isn't enough data for the rule to call this yet. Keep running, or end the test early "
                "(it will be recorded as inconclusive)."
            )
        final = self.evaluate(sprint, finished=True)
        trigger = "forced" if (force and live["verdict"] == Verdict.KEEP_RUNNING.value) else "conclude"
        snapshot = self._r.conclude(sprint, Verdict(final["verdict"]), trigger, final)
        return snapshot, final

    # ---- views -----------------------------------------------------------
    def owner_view(self, sprint: Sprint) -> dict[str, Any]:
        view: dict[str, Any] = {
            "accepting_data": self.accepting_data(sprint),
            "past_deadline": self.is_past_deadline(sprint),
            "evaluation": None,
            "series": [],
            "channels": [],
            "verdicts": [],
        }
        if sprint.locked_at is not None:
            verdicts = self._r.list_verdicts(sprint.id)
            view["verdicts"] = [
                {"id": v.id, "verdict": v.verdict.value, "trigger": v.trigger, "created_at": v.created_at,
                 "protocol_hash": v.protocol_hash}
                for v in verdicts
            ]
            view["evaluation"] = verdicts[-1].evaluation if verdicts else self.evaluate(sprint)
            view["series"] = self._r.daily_series(sprint.id)
            view["channels"] = self._r.channel_breakdown(sprint.id)
        return view

    def dossier_view(self, sprint: Sprint, owner_name: str) -> dict[str, Any]:
        verdicts = self._r.list_verdicts(sprint.id)
        evaluation = verdicts[-1].evaluation if verdicts else self.evaluate(sprint)
        excluded_signups = [s for s in self._r.list_signups(sprint.id) if s.excluded_at is not None]
        excluded_signals = [s for s in self._r.list_signals(sprint.id) if s.excluded_at is not None]
        return {
            "owner_name": owner_name,
            "status": sprint.status.value,
            "claim": sprint.protocol["claim"],
            "audience": sprint.protocol["audience"],
            "traffic_plan": sprint.protocol.get("traffic_plan"),
            "headline": sprint.content["headline"],
            "locked_at": _aware(sprint.locked_at),
            "concluded_at": _aware(sprint.concluded_at),
            "protocol_hash": sprint.protocol_hash,
            "confidence": sprint.protocol["confidence"],
            "deadline": sprint.protocol["deadline"],
            "evaluation": evaluation,
            "final": bool(verdicts),
            "exclusions": [
                *({"kind": "signup", "reason": s.excluded_reason} for s in excluded_signups),
                *({"kind": "conversation", "reason": s.excluded_reason} for s in excluded_signals),
            ],
            "series": self._r.daily_series(sprint.id),
        }
