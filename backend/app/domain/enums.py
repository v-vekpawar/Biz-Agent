"""Central enums for Biz-Agent 2.0 domain (SYSTEM_DESIGN.md §4-5).

Spec status semantics (§5):
- supported: multiple relevant, sufficiently credible evidence items support the
  claim, without unresolved material contradiction.
- partially_supported: some aspects supported but meaningful qualifications remain.
- weakly_supported: limited, indirect, low-quality, or insufficient evidence in favor.
- contradicted: credible evidence materially conflicts with the claim.
- unknown: evidence is absent, inconclusive, or not fit to assess.
"""

from enum import Enum


class StrEnum(str, Enum):
    """String-based enum so values are stored as plain strings in JSON/DB."""


class HypothesisStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    WEAKLY_SUPPORTED = "weakly_supported"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


class HypothesisOrigin(StrEnum):
    """Who introduced the hypothesis. SYSTEM_DESIGN §11 requires the UI (and
    reports) to distinguish AI-generated hypotheses from user-added ones."""

    AI_GENERATED = "ai_generated"
    USER = "user"


class HypothesisCategory(StrEnum):
    CUSTOMER_PROBLEM = "customer_problem"
    MARKET_DEMAND = "market_demand"
    COMPETITION_ALTERNATIVES = "competition_alternatives"
    WILLINGNESS_TO_PAY = "willingness_to_pay"
    PRICING = "pricing"
    DISTRIBUTION_ACQUISITION = "distribution_acquisition"
    UNIT_ECONOMICS = "unit_economics"
    OPERATIONS = "operations"
    TECHNOLOGY_FEASIBILITY = "technology_feasibility"
    LEGAL_REGULATORY = "legal_regulatory"
    OTHER = "other"


class EvidenceRelationship(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"


class EvidenceKind(StrEnum):
    """Direct evidence vs indirect evidence vs inference (never fabricate; a
    search snippet is a lead, not proof). See PRODUCT_SPEC.md §8."""

    DIRECT = "direct"
    INDIRECT = "indirect"
    INFERENCE = "inference"
    USER_OBSERVATION = "user_observation"


class VerificationStatus(StrEnum):
    """Evidence verification states (Phase 4 requires explicit failure and
    indeterminate states — verification failure is NOT insufficient evidence)."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"


class RunStatus(StrEnum):
    """A run that finished with insufficient evidence is completed_with_gaps,
    not a technical failure (SYSTEM_DESIGN.md §4 InvestigationRun)."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_GAPS = "completed_with_gaps"
    FAILED = "failed"


class ExperimentStatus(StrEnum):
    PROPOSED = "proposed"
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CriteriaResult(StrEnum):
    """Outcome verdict against the experiment's success/failure criteria."""

    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class DocumentProcessingStatus(StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"


class SprintStatus(StrEnum):
    """Lifecycle of a validation sprint. `draft` is editable; locking
    pre-registers the protocol and moves the sprint to `running`."""

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    CONCLUDED = "concluded"


class Verdict(StrEnum):
    """Outcome of the pre-registered decision rule (computed by code)."""

    GO = "go"
    PIVOT = "pivot"
    STOP = "stop"
    KEEP_RUNNING = "keep_running"
    INCONCLUSIVE = "inconclusive"


class MetricKey(StrEnum):
    WAITLIST_CONVERSION = "waitlist_conversion"  # signups / unique visitors
    INTERVIEW_COMMITMENT = "interview_commitment"  # committed / interviews


class SignalOutcome(StrEnum):
    COMMITTED = "committed"  # concrete commitment: pre-order, payment promise, intro, booked follow-up
    INTERESTED = "interested"  # polite interest, no commitment
    NO = "no"


class ScanStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
