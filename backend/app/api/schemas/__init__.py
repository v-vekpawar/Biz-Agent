"""Pydantic v2 schemas for the /api/v1 surface (SYSTEM_DESIGN §10).

Validation notes:
- Required-field blanks are rejected after strip (422), matching repository
  checks ("gaps" only exist for optional fields).
- String lengths mirror the DB columns so schema failures happen before the ORM.
- `current_status` and `origin` are absent from create/patch schemas: statuses
  are earned through assessments (Phase 5) and origins are set by the system.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...domain.enums import (
    CriteriaResult,
    DocumentProcessingStatus,
    EvidenceKind,
    EvidenceRelationship,
    ExperimentStatus,
    HypothesisCategory,
    HypothesisOrigin,
    HypothesisStatus,
    RunStatus,
    VerificationStatus,
)


def _strip_nonempty(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


# --- business cases ----------------------------------------------------------

class BusinessCaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    idea_description: str = Field(min_length=1)
    geography: Optional[str] = Field(default=None, max_length=200)
    target_customer: Optional[str] = Field(default=None, max_length=200)
    customer_problem: Optional[str] = None
    proposed_solution: Optional[str] = None
    business_stage: Optional[str] = Field(default=None, max_length=100)
    pricing_model: Optional[str] = Field(default=None, max_length=200)
    budget_constraints: Optional[str] = None
    known_competitors: Optional[str] = None
    user_questions: Optional[str] = None

    @field_validator("title", "idea_description")
    @classmethod
    def _requiredNotBlank(cls, v: str) -> str:
        value = _strip_nonempty(v)
        assert value is not None
        return value

    @field_validator(
        "geography", "target_customer", "customer_problem", "proposed_solution",
        "business_stage", "pricing_model", "budget_constraints",
        "known_competitors", "user_questions",
    )
    @classmethod
    def _optional_strip(cls, v: str | None) -> str | None:
        return _strip_nonempty(v)


class BusinessCasePatch(BaseModel):
    """Partial update: provided fields are set; to clear an optional field pass
    null (explicit gaps, never invented context)."""
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    idea_description: Optional[str] = Field(default=None, min_length=1)
    geography: Optional[str] = Field(default=None, max_length=200)
    target_customer: Optional[str] = Field(default=None, max_length=200)
    customer_problem: Optional[str] = None
    proposed_solution: Optional[str] = None
    business_stage: Optional[str] = Field(default=None, max_length=100)
    pricing_model: Optional[str] = Field(default=None, max_length=200)
    budget_constraints: Optional[str] = None
    known_competitors: Optional[str] = None
    user_questions: Optional[str] = None

    @field_validator("title", "idea_description")
    @classmethod
    def _requiredNotBlank(cls, v: str | None) -> str | None:
        return _strip_nonempty(v)

    @field_validator(
        "geography", "target_customer", "customer_problem", "proposed_solution",
        "business_stage", "pricing_model", "budget_constraints",
        "known_competitors", "user_questions",
    )
    @classmethod
    def _optional_strip(cls, v: str | None) -> str | None:
        return _strip_nonempty(v)


class BusinessCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    idea_description: str
    geography: Optional[str]
    target_customer: Optional[str]
    customer_problem: Optional[str]
    proposed_solution: Optional[str]
    business_stage: Optional[str]
    pricing_model: Optional[str]
    budget_constraints: Optional[str]
    known_competitors: Optional[str]
    user_questions: Optional[str]
    created_at: datetime
    updated_at: datetime


# --- hypotheses --------------------------------------------------------------

class HypothesisCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    category: HypothesisCategory = HypothesisCategory.OTHER
    rationale: Optional[str] = None
    customer_segment: Optional[str] = Field(default=None, max_length=200)
    geography: Optional[str] = Field(default=None, max_length=200)
    priority: Optional[str] = Field(default=None, max_length=50)
    testability_notes: Optional[str] = None

    @field_validator("statement")
    @classmethod
    def _statementNotBlank(cls, v: str) -> str:
        value = _strip_nonempty(v)
        assert value is not None
        return value

    @field_validator("customer_segment", "geography", "priority")
    @classmethod
    def _optional_strip(cls, v: str | None) -> str | None:
        return _strip_nonempty(v)


class HypothesisPatch(BaseModel):
    """User review/edit of a hypothesis. `current_status` is intentionally not
    patchable — statuses come from assessments; `origin` is system-set."""
    model_config = ConfigDict(extra="forbid")

    statement: Optional[str] = Field(default=None, min_length=1)
    category: Optional[HypothesisCategory] = None
    rationale: Optional[str] = None
    customer_segment: Optional[str] = Field(default=None, max_length=200)
    geography: Optional[str] = Field(default=None, max_length=200)
    priority: Optional[str] = Field(default=None, max_length=50)
    testability_notes: Optional[str] = None

    @field_validator("statement")
    @classmethod
    def _statementNotBlank(cls, v: str | None) -> str | None:
        return _strip_nonempty(v)

    @field_validator("customer_segment", "geography", "priority")
    @classmethod
    def _optional_strip(cls, v: str | None) -> str | None:
        return _strip_nonempty(v)


class HypothesisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_case_id: int
    statement: str
    category: HypothesisCategory
    rationale: Optional[str]
    customer_segment: Optional[str]
    geography: Optional[str]
    priority: Optional[str]
    testability_notes: Optional[str]
    current_status: HypothesisStatus
    origin: HypothesisOrigin
    created_at: datetime
    updated_at: datetime


# --- hypothesis extraction -----------------------------------------------------

class HypothesisExtracted(BaseModel):
    """One candidate produced by extraction. Category arrives as a raw string
    from the model; unknown values are coerced to OTHER downstream."""
    statement: str
    category: str
    rationale: Optional[str] = None
    customer_segment: Optional[str] = None
    geography: Optional[str] = None
    priority: Optional[str] = None
    testability_notes: Optional[str] = None


class ExtractionMeta(BaseModel):
    provider: str
    model: str
    prompt_version: str
    raw_candidates: int
    kept_candidates: int
    dropped_invalid: int
    deduplicated: int
    context_gaps: list[str]


class ExtractionResponse(BaseModel):
    hypotheses: list[HypothesisRead]
    meta: ExtractionMeta


# --- phase 3: evidence + investigations --------------------------------------

class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_case_id: int
    source_title: str
    source_url: Optional[str]
    source_type: Optional[str]
    publisher: Optional[str]
    author: Optional[str]
    published_at: Optional[str]
    retrieved_at: datetime
    excerpt: Optional[str]
    finding: Optional[str]
    evidence_kind: EvidenceKind
    relevance_assessment: Optional[str]
    reliability_assessment: Optional[str]
    limitations: Optional[str]
    verification_status: VerificationStatus
    created_at: datetime


class EvidenceLinkRead(BaseModel):
    hypothesis_id: int
    evidence_id: int
    relationship: EvidenceRelationship
    relationship_rationale: Optional[str]
    created_at: datetime
    evidence: EvidenceRead


class EvidenceUnlinkRequest(BaseModel):
    """Remove a hypothesis↔evidence link (evidence row is kept in the register)."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: int


class ManualEvidenceCreate(BaseModel):
    """User-entered evidence. The user declares how it relates to the
    hypothesis (required — never guessed); metadata stays sparse/honest."""

    model_config = ConfigDict(extra="forbid")

    source_title: str = Field(min_length=1, max_length=300)
    source_url: Optional[str] = Field(default=None, max_length=1000)
    source_type: Optional[str] = Field(default=None, max_length=100)
    excerpt: Optional[str] = None
    finding: Optional[str] = None
    evidence_kind: EvidenceKind = EvidenceKind.USER_OBSERVATION
    limitations: Optional[str] = None
    relationship: EvidenceRelationship
    relationship_rationale: Optional[str] = None

    @field_validator("source_title")
    @classmethod
    def _titleNotBlank(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("source_title must not be blank")
        return value


class InvestigationCreate(BaseModel):
    """Optional scope: omit to investigate all hypotheses in the case."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_ids: Optional[list[int]] = None


class InvestigationPlanRead(BaseModel):
    hypothesis_id: int
    evidence_needs: list[str]
    research_questions: list[str]
    search_queries: list[str]
    counter_evidence_queries: list[str]
    disconfirmation_questions: list[str]


class InvestigationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_case_id: int
    status: RunStatus
    started_at: datetime
    finished_at: Optional[datetime]
    requested_scope: Optional[dict]
    error_summary: Optional[str]
    workflow_metadata: Optional[dict]


class InvestigationResponse(BaseModel):
    run: InvestigationRunRead
    plans: list[InvestigationPlanRead]
    evidence_created: int
    evidence_reused: int
    links_created: int
    gaps: list[str]


class RunEventsRead(BaseModel):
    run_id: int
    status: RunStatus
    search_provider: Optional[str] = None
    events: list[dict]
    gaps: list[str]


# --- phase 4: verification ----------------------------------------------------

class PairVerdictRead(BaseModel):
    """One (evidence, hypothesis) classification produced by the verifier.

    verification='verified' means the fetched source content substantiated
    the evidence's claim; 'indeterminate' means it could not be confirmed
    from the content. Unparsable output can never produce either value."""

    hypothesis_id: int
    relationship: EvidenceRelationship
    verification: str
    relationship_rationale: Optional[str] = None
    relevance_assessment: Optional[str] = None
    reliability_assessment: Optional[str] = None
    conflict: Optional[dict] = None


class EvidenceVerifyResult(BaseModel):
    evidence_id: int
    row_status: VerificationStatus
    fetched: bool
    fetcher: Optional[str] = None
    verdicts: list[PairVerdictRead]
    conflicts: list[dict]
    failures: list[str]


class VerifyRequest(BaseModel):
    """Case-level verification scope: omit to verify every URL-bearing
    evidence row of the case; URL-less rows are always SKIPPED (reported,
    never treated as verified)."""

    model_config = ConfigDict(extra="forbid")

    evidence_ids: Optional[list[int]] = None


class EvidenceVerifyResponse(BaseModel):
    result: EvidenceVerifyResult


class CaseVerifyResponse(BaseModel):
    results: list[EvidenceVerifyResult]
    skipped: list[dict]
    summary: dict[str, int]


# --- documents --------------------------------------------------------------

class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_case_id: int
    original_filename: str
    mime_type: Optional[str]
    size_bytes: Optional[int]
    uploaded_at: datetime
    processing_status: DocumentProcessingStatus


# --- phase 5: assessment ------------------------------------------------------

class AssessmentRead(BaseModel):
    """One immutable assessment version (append-only history row).

    `status` is qualitative — never an opaque score (PRODUCT_SPEC §10);
    `rationale` is required and cites evidence ids; references freeze the
    directional claims the assessment relied on."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    hypothesis_id: int
    investigation_run_id: Optional[int] = None
    version: int
    status: HypothesisStatus
    rationale: str
    supporting_evidence_ids: list[int]
    contradicting_evidence_ids: list[int]
    evidence_gaps: Optional[str] = None
    limitations: Optional[str] = None
    recommended_next_step: Optional[str] = None
    created_at: datetime


class AssessOneResponse(BaseModel):
    """POST /hypotheses/{id}/assess: the new version + the deterministic
    evidence facts snapshot it was judged against (transparency, not scores)."""

    assessment: AssessmentRead
    facts: dict


class CaseAssessRequest(BaseModel):
    """Case-level scope: omit to assess every hypothesis of the case."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_ids: Optional[list[int]] = None


class CaseAssessResult(BaseModel):
    hypothesis_id: int
    assessment: AssessmentRead
    facts: dict


class CaseAssessResponse(BaseModel):
    results: list[CaseAssessResult]
    summary: dict[str, int]


# --- phase 6: experiments -------------------------------------------------

class OutcomeRead(BaseModel):
    """One append-only, timestamped experiment outcome."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    experiment_id: int
    recorded_at: datetime
    actual_dates: Optional[str] = None
    participant_count: Optional[int] = None
    participant_type: Optional[str] = None
    observations: Optional[str] = None
    measurements: Optional[str] = None
    notes_quotes: Optional[str] = None
    criteria_result: Optional[CriteriaResult] = None
    user_interpretation: Optional[str] = None
    attachment_references: Optional[list[str]] = None
    created_at: datetime


class ExperimentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_case_id: int
    hypothesis_id: Optional[int] = None
    title: str
    objective: Optional[str] = None
    method: Optional[str] = None
    target_participants: Optional[str] = None
    recruitment_approach: Optional[str] = None
    resources: Optional[str] = None
    estimated_duration: Optional[str] = None
    estimated_cost: Optional[str] = None
    cost_assumptions: Optional[str] = None
    success_criteria: Optional[str] = None
    failure_criteria: Optional[str] = None
    data_to_collect: Optional[str] = None
    risks: Optional[str] = None
    status: ExperimentStatus
    created_at: datetime
    updated_at: datetime
    outcomes: list[OutcomeRead] = []


class ExperimentGenerateRequest(BaseModel):
    """Optional steer for the designer; REQUIRED experiment fields cannot be
    overridden away by the user."""

    model_config = ConfigDict(extra="forbid")

    guidance: Optional[str] = None


class ExperimentListResponse(BaseModel):
    experiments: list[ExperimentRead]


class ExperimentPatch(BaseModel):
    """User edit/manage. Once outcomes exist the service freezes the judged
    content (criteria/method/...) and only allows status completed/cancelled."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    objective: Optional[str] = None
    method: Optional[str] = None
    target_participants: Optional[str] = None
    recruitment_approach: Optional[str] = None
    resources: Optional[str] = None
    estimated_duration: Optional[str] = None
    estimated_cost: Optional[str] = None
    cost_assumptions: Optional[str] = None
    success_criteria: Optional[str] = None
    failure_criteria: Optional[str] = None
    data_to_collect: Optional[str] = None
    risks: Optional[str] = None
    status: Optional[ExperimentStatus] = None


class OutcomeCreate(BaseModel):
    """criteria_result + at least one content field are required (service
    rejects empty outcomes: 'what actually happened' must be recorded)."""

    model_config = ConfigDict(extra="forbid")

    criteria_result: CriteriaResult
    actual_dates: Optional[str] = None
    participant_count: Optional[int] = None
    participant_type: Optional[str] = None
    observations: Optional[str] = None
    measurements: Optional[str] = None
    notes_quotes: Optional[str] = None
    user_interpretation: Optional[str] = None
    attachment_references: Optional[list[str]] = None


class OutcomeCreateResponse(BaseModel):
    outcome: OutcomeRead
    # The system PROPOSES re-assessment (append-only walkthrough of the core
    # loop); it never silently overwrites an assessment.
    assessment_suggestion: dict


class CriteriaRevisionRequest(BaseModel):
    success_criteria: Optional[str] = None
    failure_criteria: Optional[str] = None
    reason: str = Field(min_length=8, max_length=2000)
