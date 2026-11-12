"""Sprint repository.

Append-only facts: visits, signups, signals and verdict snapshots expose no
update/delete path. Signups and signals can be EXCLUDED (with a reason); an
exclusion is permanent and is disclosed in the public dossier.
"""

from __future__ import annotations

import datetime as _dt
import secrets
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..domain.enums import SignalOutcome, SprintStatus, Verdict
from ..domain.models import Sprint, SprintSignal, SprintSignup, SprintVerdict, SprintVisit


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class SprintRepository:
    def __init__(self, session: Session):
        self._s = session

    # ---- sprint ---------------------------------------------------------
    def create(self, case_id: int, content: dict, protocol: dict, *, hypothesis_id: int | None = None,
               kit: dict | None = None, source: str = "manual") -> Sprint:
        sprint = Sprint(
            business_case_id=case_id,
            hypothesis_id=hypothesis_id,
            slug=self._unique_slug(),
            dossier_token=secrets.token_urlsafe(24),
            source=source,
            status=SprintStatus.DRAFT,
            content=content,
            protocol=protocol,
            kit=kit,
        )
        self._s.add(sprint)
        self._s.commit()
        self._s.refresh(sprint)
        return sprint

    def _unique_slug(self) -> str:
        while True:
            slug = secrets.token_urlsafe(8).replace("_", "x").replace("-", "y")[:10].lower()
            if self._s.scalar(select(Sprint.id).where(Sprint.slug == slug)) is None:
                return slug

    def get(self, sprint_id: int) -> Sprint | None:
        return self._s.get(Sprint, sprint_id)

    def get_by_slug(self, slug: str) -> Sprint | None:
        return self._s.scalar(select(Sprint).where(Sprint.slug == slug))

    def get_by_dossier_token(self, token: str) -> Sprint | None:
        return self._s.scalar(select(Sprint).where(Sprint.dossier_token == token))

    def list_by_case(self, case_id: int) -> list[Sprint]:
        return list(self._s.scalars(select(Sprint).where(Sprint.business_case_id == case_id).order_by(Sprint.id.desc())))

    def update_draft(self, sprint: Sprint, *, content: dict | None = None, protocol: dict | None = None,
                     hypothesis_id: int | None | Any = ..., ) -> Sprint:
        if sprint.status != SprintStatus.DRAFT or sprint.locked_at is not None:
            raise ValueError("This sprint is locked. Its page and decision rule can no longer be edited.")
        if content is not None:
            sprint.content = content
        if protocol is not None:
            sprint.protocol = protocol
        if hypothesis_id is not ...:
            sprint.hypothesis_id = hypothesis_id
        self._s.commit()
        self._s.refresh(sprint)
        return sprint

    def update_kit(self, sprint: Sprint, kit: dict) -> Sprint:
        sprint.kit = kit
        self._s.commit()
        self._s.refresh(sprint)
        return sprint

    def lock(self, sprint: Sprint, protocol_hash: str) -> Sprint:
        if sprint.status != SprintStatus.DRAFT:
            raise ValueError("Only a draft sprint can be locked.")
        sprint.protocol_hash = protocol_hash
        sprint.locked_at = _now()
        sprint.status = SprintStatus.RUNNING
        self._s.commit()
        self._s.refresh(sprint)
        return sprint

    def set_running_state(self, sprint: Sprint, status: SprintStatus) -> Sprint:
        allowed = {
            SprintStatus.RUNNING: {SprintStatus.PAUSED},
            SprintStatus.PAUSED: {SprintStatus.RUNNING},
        }
        if status not in allowed or sprint.status not in allowed[status]:
            raise ValueError(f"Cannot move a {sprint.status.value} sprint to {status.value}.")
        sprint.status = status
        self._s.commit()
        self._s.refresh(sprint)
        return sprint

    def set_dossier_enabled(self, sprint: Sprint, enabled: bool) -> Sprint:
        if sprint.locked_at is None:
            raise ValueError("The dossier is available once the sprint is locked.")
        sprint.dossier_enabled = enabled
        self._s.commit()
        self._s.refresh(sprint)
        return sprint

    def conclude(self, sprint: Sprint, verdict: Verdict, trigger: str, evaluation: dict) -> SprintVerdict:
        if sprint.status not in (SprintStatus.RUNNING, SprintStatus.PAUSED):
            raise ValueError("Only a running or paused sprint can be concluded.")
        snapshot = SprintVerdict(
            sprint_id=sprint.id, verdict=verdict, trigger=trigger,
            protocol_hash=sprint.protocol_hash or "", evaluation=evaluation,
        )
        sprint.status = SprintStatus.CONCLUDED
        sprint.concluded_at = _now()
        self._s.add(snapshot)
        self._s.commit()
        self._s.refresh(snapshot)
        return snapshot

    def delete(self, sprint: Sprint) -> None:
        self._s.delete(sprint)
        self._s.commit()

    # ---- visits ---------------------------------------------------------
    def record_visit(self, sprint_id: int, visitor_hash: str, channel: str | None) -> bool:
        """True if this visitor is new for the sprint."""
        exists = self._s.scalar(
            select(SprintVisit.id).where(SprintVisit.sprint_id == sprint_id, SprintVisit.visitor_hash == visitor_hash)
        )
        if exists is not None:
            return False
        self._s.add(SprintVisit(sprint_id=sprint_id, visitor_hash=visitor_hash, channel=channel))
        try:
            self._s.commit()
        except IntegrityError:
            self._s.rollback()
            return False
        return True

    # ---- signups --------------------------------------------------------
    def get_signup(self, signup_id: int) -> SprintSignup | None:
        return self._s.get(SprintSignup, signup_id)

    def record_signup(self, sprint_id: int, visitor_hash: str, email: str, answer: str | None,
                      channel: str | None) -> tuple[SprintSignup, bool]:
        existing = self._s.scalar(
            select(SprintSignup).where(SprintSignup.sprint_id == sprint_id, SprintSignup.email == email)
        )
        if existing is not None:
            return existing, False
        row = SprintSignup(sprint_id=sprint_id, visitor_hash=visitor_hash, email=email, answer=answer, channel=channel)
        self._s.add(row)
        try:
            self._s.commit()
        except IntegrityError:
            self._s.rollback()
            existing = self._s.scalar(
                select(SprintSignup).where(SprintSignup.sprint_id == sprint_id, SprintSignup.email == email)
            )
            return existing, False
        self._s.refresh(row)
        return row, True

    def list_signups(self, sprint_id: int) -> list[SprintSignup]:
        return list(self._s.scalars(select(SprintSignup).where(SprintSignup.sprint_id == sprint_id).order_by(SprintSignup.id)))

    def exclude_signup(self, signup: SprintSignup, reason: str) -> SprintSignup:
        if signup.excluded_at is not None:
            raise ValueError("This signup is already excluded.")
        signup.excluded_at = _now()
        signup.excluded_reason = reason
        self._s.commit()
        self._s.refresh(signup)
        return signup

    # ---- signals --------------------------------------------------------
    def add_signal(self, sprint_id: int, outcome: str, who: str | None, notes: str | None) -> SprintSignal:
        outcome = SignalOutcome(outcome).value
        row = SprintSignal(sprint_id=sprint_id, outcome=outcome, who=who, notes=notes)
        self._s.add(row)
        self._s.commit()
        self._s.refresh(row)
        return row

    def get_signal(self, signal_id: int) -> SprintSignal | None:
        return self._s.get(SprintSignal, signal_id)

    def list_signals(self, sprint_id: int) -> list[SprintSignal]:
        return list(self._s.scalars(select(SprintSignal).where(SprintSignal.sprint_id == sprint_id).order_by(SprintSignal.id)))

    def exclude_signal(self, signal: SprintSignal, reason: str) -> SprintSignal:
        if signal.excluded_at is not None:
            raise ValueError("This entry is already excluded.")
        signal.excluded_at = _now()
        signal.excluded_reason = reason
        self._s.commit()
        self._s.refresh(signal)
        return signal

    # ---- verdicts -------------------------------------------------------
    def list_verdicts(self, sprint_id: int) -> list[SprintVerdict]:
        return list(self._s.scalars(select(SprintVerdict).where(SprintVerdict.sprint_id == sprint_id).order_by(SprintVerdict.id)))

    # ---- aggregates -----------------------------------------------------
    def counts(self, sprint_id: int) -> dict[str, int]:
        s = self._s
        visitors = s.scalar(select(func.count(SprintVisit.id)).where(SprintVisit.sprint_id == sprint_id)) or 0
        signups = s.scalar(select(func.count(SprintSignup.id)).where(
            SprintSignup.sprint_id == sprint_id, SprintSignup.excluded_at.is_(None))) or 0
        signups_excluded = s.scalar(select(func.count(SprintSignup.id)).where(
            SprintSignup.sprint_id == sprint_id, SprintSignup.excluded_at.is_not(None))) or 0
        by_outcome = {o.value: 0 for o in SignalOutcome}
        for outcome, n in s.execute(
            select(SprintSignal.outcome, func.count(SprintSignal.id))
            .where(SprintSignal.sprint_id == sprint_id, SprintSignal.excluded_at.is_(None))
            .group_by(SprintSignal.outcome)
        ):
            by_outcome[outcome] = n
        signals_excluded = s.scalar(select(func.count(SprintSignal.id)).where(
            SprintSignal.sprint_id == sprint_id, SprintSignal.excluded_at.is_not(None))) or 0
        return {
            "visitors": visitors,
            "signups": signups,
            "signups_excluded": signups_excluded,
            "interviews": sum(by_outcome.values()),
            "committed": by_outcome[SignalOutcome.COMMITTED.value],
            "interested": by_outcome[SignalOutcome.INTERESTED.value],
            "declined": by_outcome[SignalOutcome.NO.value],
            "interviews_excluded": signals_excluded,
        }

    def daily_series(self, sprint_id: int) -> list[dict[str, Any]]:
        """Per-day visitors and (non-excluded) signups, for the dashboard chart."""
        days: dict[str, dict[str, int]] = {}
        for created_at in self._s.scalars(select(SprintVisit.created_at).where(SprintVisit.sprint_id == sprint_id)):
            days.setdefault(created_at.date().isoformat(), {"visitors": 0, "signups": 0})["visitors"] += 1
        for created_at in self._s.scalars(select(SprintSignup.created_at).where(
                SprintSignup.sprint_id == sprint_id, SprintSignup.excluded_at.is_(None))):
            days.setdefault(created_at.date().isoformat(), {"visitors": 0, "signups": 0})["signups"] += 1
        return [{"date": d, **v} for d, v in sorted(days.items())]

    def channel_breakdown(self, sprint_id: int) -> list[dict[str, Any]]:
        rows: dict[str, dict[str, int]] = {}
        for channel in self._s.scalars(select(SprintVisit.channel).where(SprintVisit.sprint_id == sprint_id)):
            rows.setdefault(channel or "direct", {"visitors": 0, "signups": 0})["visitors"] += 1
        for channel in self._s.scalars(select(SprintSignup.channel).where(
                SprintSignup.sprint_id == sprint_id, SprintSignup.excluded_at.is_(None))):
            rows.setdefault(channel or "direct", {"visitors": 0, "signups": 0})["signups"] += 1
        return [{"channel": c, **v} for c, v in sorted(rows.items(), key=lambda kv: -kv[1]["visitors"])]
