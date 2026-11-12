"""Schemas for auth, validation sprints, scans and the public test page."""

from __future__ import annotations

import datetime as _dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...core.security import is_valid_email, normalize_email
from ...domain.enums import MetricKey
from ...services import stats

# --- auth -----------------------------------------------------------------------


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    display_name: str = Field(min_length=1, max_length=100)


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    display_name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


# --- sprint definition --------------------------------------------------------------


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split()) if "\n" not in value else value.strip()
    return value or None


class SprintContent(BaseModel):
    """What the public test page says. Frozen at lock."""

    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=5, max_length=120)
    subheadline: Optional[str] = Field(default=None, max_length=240)
    bullets: list[str] = Field(min_length=1, max_length=5)
    cta_label: str = Field(default="Join the waitlist", min_length=2, max_length=30)
    extra_question: Optional[str] = Field(default=None, max_length=140)
    price_hint: Optional[str] = Field(default=None, max_length=80)
    # Safe, predefined design tokens selected for this idea. These affect only
    # public-page presentation; they never affect the locked decision rule.
    visual_theme: Literal[
        "fresh_green", "midnight_blue", "warm_citrus", "violet_tech",
        "earth_clay", "rose_editorial", "paper_brass"
    ] = "paper_brass"
    visual_style: Literal["editorial", "bold", "minimal", "playful"] = "editorial"
    hero_kicker: Optional[str] = Field(default=None, max_length=70)
    creator_name: str = Field(min_length=1, max_length=80)
    contact_email: str = Field(max_length=254)

    @field_validator("headline", "cta_label", "creator_name")
    @classmethod
    def _req(cls, v: str) -> str:
        v = _clean(v)
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("hero_kicker")
    @classmethod
    def _kicker(cls, v):
        return _clean(v)

    @field_validator("subheadline", "extra_question", "price_hint")
    @classmethod
    def _opt(cls, v):
        return _clean(v)

    @field_validator("bullets")
    @classmethod
    def _bullets(cls, v: list[str]) -> list[str]:
        out = []
        for item in v:
            item = _clean(item)
            if not item:
                raise ValueError("bullets must not be blank")
            if len(item) > 140:
                raise ValueError("each bullet must be 140 characters or fewer")
            out.append(item)
        return out

    @field_validator("contact_email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = normalize_email(v)
        if not is_valid_email(v):
            raise ValueError("enter a valid contact email")
        return v


class MetricSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: MetricKey
    role: Literal["primary", "supporting"]
    success_rate: float = Field(gt=0.0, lt=1.0)
    failure_rate: float = Field(gt=0.0, lt=1.0)
    min_sample: int = Field(ge=1, le=100000)

    @model_validator(mode="after")
    def _check(self):
        if self.failure_rate >= self.success_rate:
            raise ValueError("failure_rate must be lower than success_rate")
        floor = stats.MIN_SAMPLE_FLOOR[self.key.value]
        if self.min_sample < floor:
            raise ValueError(f"min_sample for {self.key.value} must be at least {floor}")
        return self


class SprintProtocol(BaseModel):
    """The pre-registered claim and decision rule. Frozen at lock."""

    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=10, max_length=300)
    audience: str = Field(min_length=3, max_length=200)
    traffic_plan: Optional[str] = Field(default=None, max_length=300)
    confidence: float = 0.90
    deadline: _dt.date
    metrics: list[MetricSpec] = Field(min_length=1, max_length=2)

    @field_validator("claim", "audience")
    @classmethod
    def _req(cls, v: str) -> str:
        v = _clean(v)
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("traffic_plan")
    @classmethod
    def _opt(cls, v):
        return _clean(v)

    @field_validator("confidence")
    @classmethod
    def _conf(cls, v: float) -> float:
        v = round(v, 2)
        if v not in stats.ALLOWED_CONFIDENCE:
            raise ValueError(f"confidence must be one of {list(stats.ALLOWED_CONFIDENCE)}")
        return v

    @model_validator(mode="after")
    def _metrics(self):
        keys = [m.key for m in self.metrics]
        if len(set(keys)) != len(keys):
            raise ValueError("each metric may appear once")
        if sum(1 for m in self.metrics if m.role == "primary") != 1:
            raise ValueError("exactly one metric must be primary")
        return self


class SprintCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypothesis_id: Optional[int] = None
    content: SprintContent
    protocol: SprintProtocol
    kit: Optional[dict[str, Any]] = None


class SprintPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypothesis_id: Optional[int] = None
    content: Optional[SprintContent] = None
    protocol: Optional[SprintProtocol] = None
    kit: Optional[dict[str, Any]] = None


class SprintAiDraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypothesis_id: Optional[int] = None


class LockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledge_public_page: bool = False
    acknowledge_frozen: bool = False


class ConcludeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    force: bool = False


class SignalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["committed", "interested", "no"]
    who: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("who", "notes")
    @classmethod
    def _opt(cls, v):
        return _clean(v)


class ExcludeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=300)


class DossierIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class PlanPreviewIn(BaseModel):
    """Planning helper: what sample size does this target need?"""
    model_config = ConfigDict(extra="forbid")
    success_rate: float = Field(gt=0.0, lt=1.0)
    confidence: float = 0.90


# --- public page --------------------------------------------------------------------


class VisitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vid: str = Field(min_length=8, max_length=64)
    channel: Optional[str] = Field(default=None, max_length=50)


class SignupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vid: str = Field(min_length=8, max_length=64)
    email: str = Field(max_length=254)
    answer: Optional[str] = Field(default=None, max_length=1000)
    consent: bool = False
    channel: Optional[str] = Field(default=None, max_length=50)
    website: Optional[str] = Field(default=None, max_length=200)  # honeypot: humans leave it empty
