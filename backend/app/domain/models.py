"""
SQLAlchemy persistence models for Biz-Agent 5.0.

Layers:
- Research engine (cases, hypotheses, evidence, assessments, experiments):
  durable relational records. Assessment history is append-only.
- Validation sprints (v4): a pre-registered, hosted experiment. The protocol
  and page content are frozen at lock time (sha256 protocol hash); visits,
  signups and interview signals are append-only facts; verdict snapshots are
  immutable.
- Foreign keys + explicit indexes + timestamps. SQLite runs with
  PRAGMA foreign_keys=ON (db/session.py), so ON DELETE CASCADE is enforced.
"""

import datetime as _dt

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship as orm_relationship

from .enums import (
    CriteriaResult,
    DocumentProcessingStatus,
    EvidenceKind,
    EvidenceRelationship,
    ExperimentStatus,
    HypothesisCategory,
    HypothesisStatus,
    HypothesisOrigin,
    RunStatus,
    ScanStatus,
    SprintStatus,
    Verdict,
    VerificationStatus,
)


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class Base(DeclarativeBase):
    pass


def _sa_enum(enum_cls, **kwargs):
    # native_enum=False -> VARCHAR + CHECK constraint (SQLite-friendly);
    # values_domain makes ALTER-validate phases explicit in migrations.
    return SAEnum(enum_cls, native_enum=False, values_callable=lambda e: [m.value for m in e], **kwargs)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class BusinessCase(Base):
    __tablename__ = "business_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Owner (v4 auth). Nullable only so pre-v4 rows survive migration; such rows
    # are unreachable through the API because every query is owner-scoped.
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    idea_description: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional intake fields: missing data is an explicit gap, never invented.
    geography: Mapped[str | None] = mapped_column(String(200))
    target_customer: Mapped[str | None] = mapped_column(String(200))
    customer_problem: Mapped[str | None] = mapped_column(Text)
    proposed_solution: Mapped[str | None] = mapped_column(Text)
    business_stage: Mapped[str | None] = mapped_column(String(100))
    pricing_model: Mapped[str | None] = mapped_column(String(200))
    budget_constraints: Mapped[str | None] = mapped_column(Text)
    known_competitors: Mapped[str | None] = mapped_column(Text)
    user_questions: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    hypotheses: Mapped[list["Hypothesis"]] = orm_relationship(back_populates="case", cascade="all, delete-orphan")


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    __table_args__ = (
        UniqueConstraint("business_case_id", "statement", name="uq_hypothesis_case_statement"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_case_id: Mapped[int] = mapped_column(
        ForeignKey("business_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )

    statement: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[HypothesisCategory] = mapped_column(
        _sa_enum(HypothesisCategory), default=HypothesisCategory.OTHER, nullable=False
    )
    rationale: Mapped[str | None] = mapped_column(Text)
    customer_segment: Mapped[str | None] = mapped_column(String(200))
    geography: Mapped[str | None] = mapped_column(String(200))
    # User-facing priority (high/medium/low or 1-3) — kept free-form for MVP.
    priority: Mapped[str | None] = mapped_column(String(50))
    testability_notes: Mapped[str | None] = mapped_column(Text)

    # Denormalized current status; authoritative history lives in
    # hypothesis_assessments (append-only).
    current_status: Mapped[HypothesisStatus] = mapped_column(
        _sa_enum(HypothesisStatus), default=HypothesisStatus.UNKNOWN, nullable=False
    )

    # Who introduced it (D-14): ai_generated hypotheses are candidates to
    # review, never verified facts.
    origin: Mapped[HypothesisOrigin] = mapped_column(
        _sa_enum(HypothesisOrigin), default=HypothesisOrigin.USER, nullable=False
    )

    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    case: Mapped[BusinessCase] = orm_relationship(back_populates="hypotheses")
    assessment_history: Mapped[list["HypothesisAssessment"]] = orm_relationship(
        back_populates="hypothesis",
        order_by="HypothesisAssessment.version",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_case_id: Mapped[int] = mapped_column(
        ForeignKey("business_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Source metadata: missing metadata stays missing (never invented).
    source_title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    source_type: Mapped[str | None] = mapped_column(String(100))  # e.g. news, vendor page, forum, report
    publisher: Mapped[str | None] = mapped_column(String(200))
    author: Mapped[str | None] = mapped_column(String(200))
    published_at: Mapped[str | None] = mapped_column(String(50))  # free-form date until normalized
    retrieved_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    excerpt: Mapped[str | None] = mapped_column(Text)
    finding: Mapped[str | None] = mapped_column(Text)

    evidence_kind: Mapped[EvidenceKind] = mapped_column(_sa_enum(EvidenceKind), default=EvidenceKind.INDIRECT, nullable=False)
    relevance_assessment: Mapped[str | None] = mapped_column(Text)
    reliability_assessment: Mapped[str | None] = mapped_column(Text)
    limitations: Mapped[str | None] = mapped_column(Text)

    verification_status: Mapped[VerificationStatus] = mapped_column(
        _sa_enum(VerificationStatus), default=VerificationStatus.UNVERIFIED, nullable=False
    )

    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    hypothesis_links: Mapped[list["HypothesisEvidence"]] = orm_relationship(
        back_populates="evidence", cascade="all, delete-orphan", passive_deletes=True
    )


class HypothesisEvidence(Base):
    """Many-to-many link: which hypothesis a piece of evidence speaks to, and
    how. Enforces same-business-case integrity at the repository layer."""

    __tablename__ = "hypothesis_evidence"
    __table_args__ = (
        UniqueConstraint("hypothesis_id", "evidence_id", name="uq_hypothesis_evidence_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("evidence.id", ondelete="CASCADE"), index=True, nullable=False
    )

    relationship: Mapped[EvidenceRelationship] = mapped_column(_sa_enum(EvidenceRelationship), nullable=False)
    relationship_rationale: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    hypothesis: Mapped[Hypothesis] = orm_relationship()
    evidence: Mapped[Evidence] = orm_relationship(back_populates="hypothesis_links")

class InvestigationRun(Base):
    __tablename__ = "investigation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_case_id: Mapped[int] = mapped_column(
        ForeignKey("business_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )

    status: Mapped[RunStatus] = mapped_column(_sa_enum(RunStatus), default=RunStatus.QUEUED, nullable=False, index=True)
    started_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True))

    # Which hypotheses this run was asked to investigate (JSON list of ids),
    # or null/{} for a whole-case investigation.
    requested_scope: Mapped[dict | None] = mapped_column(JSON)

    error_summary: Mapped[str | None] = mapped_column(Text)
    # Structured runtime info: warnings, step events, token/call counts.
    workflow_metadata: Mapped[dict | None] = mapped_column(JSON)


class HypothesisAssessment(Base):
    """Append-only assessment versions. The repository layer must never update
    or delete rows here — new evidence means a NEW version row."""

    __tablename__ = "hypothesis_assessments"
    __table_args__ = (
        UniqueConstraint("hypothesis_id", "version", name="uq_assessment_hypothesis_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    investigation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigation_runs.id", ondelete="SET NULL"), index=True
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[HypothesisStatus] = mapped_column(_sa_enum(HypothesisStatus), nullable=False)

    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    # Evidence references frozen at assessment time (JSON list of evidence ids).
    supporting_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    contradicting_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)

    evidence_gaps: Mapped[str | None] = mapped_column(Text)
    limitations: Mapped[str | None] = mapped_column(Text)
    recommended_next_step: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    hypothesis: Mapped[Hypothesis] = orm_relationship(back_populates="assessment_history")


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_case_id: Mapped[int] = mapped_column(
        ForeignKey("business_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    hypothesis_id: Mapped[int | None] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="SET NULL"), index=True
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    objective: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(Text)
    target_participants: Mapped[str | None] = mapped_column(Text)
    recruitment_approach: Mapped[str | None] = mapped_column(Text)
    resources: Mapped[str | None] = mapped_column(Text)

    estimated_duration: Mapped[str | None] = mapped_column(String(100))
    estimated_cost: Mapped[str | None] = mapped_column(String(100))
    # Model-suggested numeric thresholds must be labeled as suggested starting
    # assumptions, not sourced benchmarks (PRODUCT_SPEC.md §11).
    cost_assumptions: Mapped[str | None] = mapped_column(Text)

    success_criteria: Mapped[str | None] = mapped_column(Text)
    failure_criteria: Mapped[str | None] = mapped_column(Text)
    data_to_collect: Mapped[str | None] = mapped_column(Text)
    risks: Mapped[str | None] = mapped_column(Text)

    status: Mapped[ExperimentStatus] = mapped_column(
        _sa_enum(ExperimentStatus), default=ExperimentStatus.PROPOSED, nullable=False, index=True
    )

    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class ExperimentOutcome(Base):
    """Real-world result of an experiment. Outcomes are append-only observations;
    the system may propose (never silently overwrite) an updated assessment."""

    __tablename__ = "experiment_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), index=True, nullable=False
    )

    recorded_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    actual_dates: Mapped[str | None] = mapped_column(String(200))
    participant_count: Mapped[int | None] = mapped_column(Integer)
    participant_type: Mapped[str | None] = mapped_column(String(200))

    observations: Mapped[str | None] = mapped_column(Text)
    measurements: Mapped[str | None] = mapped_column(Text)
    notes_quotes: Mapped[str | None] = mapped_column(Text)

    criteria_result: Mapped[CriteriaResult | None] = mapped_column(_sa_enum(CriteriaResult))
    user_interpretation: Mapped[str | None] = mapped_column(Text)
    attachment_references: Mapped[list | None] = mapped_column(JSON, default=list)

    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_case_id: Mapped[int] = mapped_column(
        ForeignKey("business_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )

    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_reference: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(150))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    uploaded_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    processing_status: Mapped[DocumentProcessingStatus] = mapped_column(
        _sa_enum(DocumentProcessingStatus), default=DocumentProcessingStatus.PENDING, nullable=False
    )


class ExperimentCriteriaRevision(Base):
    """Immutable, reasoned history of success/failure criteria changes."""
    __tablename__ = "experiment_criteria_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    success_criteria: Mapped[str | None] = mapped_column(Text)
    failure_criteria: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("experiment_id", "version", name="uq_experiment_criteria_version"),)


class ScanJob(Base):
    """One run of the risk scan (extract -> research -> verify -> assess -> rank).

    State lives in the database, not in process memory, so the UI can poll it
    and a restart marks interrupted jobs as failed instead of hanging forever.
    """

    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_case_id: Mapped[int] = mapped_column(
        ForeignKey("business_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[ScanStatus] = mapped_column(_sa_enum(ScanStatus), default=ScanStatus.QUEUED, nullable=False, index=True)
    step: Mapped[str | None] = mapped_column(String(100))
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    log: Mapped[list | None] = mapped_column(JSON, default=list)
    warnings: Mapped[list | None] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Sprint(Base):
    """A validation sprint: one claim, one pre-registered decision rule, one
    public test page. `content` and `protocol` are frozen once `locked_at` is set."""

    __tablename__ = "sprints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_case_id: Mapped[int] = mapped_column(
        ForeignKey("business_cases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    hypothesis_id: Mapped[int | None] = mapped_column(ForeignKey("hypotheses.id", ondelete="SET NULL"), index=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    dossier_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)  # manual | ai
    status: Mapped[SprintStatus] = mapped_column(_sa_enum(SprintStatus), default=SprintStatus.DRAFT, nullable=False, index=True)

    content: Mapped[dict] = mapped_column(JSON, nullable=False)   # public page copy (frozen at lock)
    protocol: Mapped[dict] = mapped_column(JSON, nullable=False)  # claim + decision rule (frozen at lock)
    kit: Mapped[dict | None] = mapped_column(JSON)                # interview script, outreach drafts (not frozen)

    protocol_hash: Mapped[str | None] = mapped_column(String(64))
    locked_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True))
    concluded_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True))
    dossier_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class SprintVisit(Base):
    """One unique visitor (salted hash of a browser-generated id; no IP, no UA)."""

    __tablename__ = "sprint_visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sprint_id: Mapped[int] = mapped_column(ForeignKey("sprints.id", ondelete="CASCADE"), index=True, nullable=False)
    visitor_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("sprint_id", "visitor_hash", name="uq_sprint_visit_visitor"),)


class SprintSignup(Base):
    __tablename__ = "sprint_signups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sprint_id: Mapped[int] = mapped_column(ForeignKey("sprints.id", ondelete="CASCADE"), index=True, nullable=False)
    visitor_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(50))
    excluded_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True))
    excluded_reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("sprint_id", "email", name="uq_sprint_signup_email"),)


class SprintSignal(Base):
    """A manually logged interview / conversation result (append-only; mistakes
    are excluded with a reason, never edited or deleted)."""

    __tablename__ = "sprint_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sprint_id: Mapped[int] = mapped_column(ForeignKey("sprints.id", ondelete="CASCADE"), index=True, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # SignalOutcome value
    who: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    excluded_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True))
    excluded_reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SprintVerdict(Base):
    """Immutable snapshot of the decision rule's output at a point in time."""

    __tablename__ = "sprint_verdicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sprint_id: Mapped[int] = mapped_column(ForeignKey("sprints.id", ondelete="CASCADE"), index=True, nullable=False)
    verdict: Mapped[Verdict] = mapped_column(_sa_enum(Verdict), nullable=False)
    trigger: Mapped[str] = mapped_column(String(30), nullable=False)  # conclude | forced
    protocol_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
