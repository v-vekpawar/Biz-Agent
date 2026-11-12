"""FastAPI dependencies + error mapping for the /api/v1 surface."""

from __future__ import annotations

from typing import Callable, Generator

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..core import security
from ..db.session import default_engine, make_session_factory
from ..domain.models import BusinessCase, Evidence, Experiment, Hypothesis, Sprint, User
from ..integrations.fetch.base import ContentFetcher
from ..integrations.fetch.tavily_extract import get_content_fetcher
from ..integrations.llm.provider import (
    ChatLLM,
    get_extraction_llm,
    get_reasoning_llm,
    get_verifier_llm,
)
from ..integrations.search.base import SearchProvider
from ..integrations.search.tavily import get_search_provider
from ..repositories import (
    AssessmentRepository,
    CaseRepository,
    EvidenceRepository,
    ExperimentRepository,
    HypothesisRepository,
    RunRepository,
    ScanRepository,
    SprintRepository,
    UploadRepository,
    UserRepository,
)
from ..services.assessment import AssessmentService
from ..services.documents import DocumentService
from ..services.evidence import EvidenceService
from ..services.experiments import ExperimentService
from ..services.hypotheses import HypothesisService
from ..services.investigation import InvestigationService
from ..services.riskscan import ScanDeps, execute_scan
from ..services.sprints import SprintService
from ..services.testkit import TestKitService
from ..services.verification import VerificationService

_session_factory = None


def session_factory():
    """Process-wide session factory (also used by background scan jobs)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(default_engine())
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request against the configured DB."""
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_case_repo(session: Session = Depends(get_db)) -> CaseRepository:
    return CaseRepository(session)


def get_hypothesis_repo(session: Session = Depends(get_db)) -> HypothesisRepository:
    return HypothesisRepository(session)


def get_upload_repo(session: Session = Depends(get_db)) -> UploadRepository:
    return UploadRepository(session)


def get_evidence_repo(session: Session = Depends(get_db)) -> EvidenceRepository:
    return EvidenceRepository(session)


def get_run_repo(session: Session = Depends(get_db)) -> RunRepository:
    return RunRepository(session)


def get_experiment_repo(session: Session = Depends(get_db)) -> ExperimentRepository:
    return ExperimentRepository(session)


def get_extractor() -> ChatLLM:
    return get_extraction_llm()


def get_planner() -> ChatLLM:
    """Investigation planner model (reasoning temp). Overridable in tests."""
    return get_reasoning_llm()


def get_verifier() -> ChatLLM:
    """Evidence-verifier model (Gemini temp 0.0). Overridable in tests."""
    return get_verifier_llm()


def get_assessor() -> ChatLLM:
    """Hypothesis-assessor model. Deliberately a SEPARATE dependency from
    `get_verifier` (same provider wiring, different override key) so an
    assessment override can never leak into verification tests or vice versa."""
    return get_verifier_llm()


def get_experiment_designer() -> ChatLLM:
    """Experiment-designer model (reasoning temp). Overridable in tests."""
    return get_reasoning_llm()


def get_or_none_content_fetcher() -> ContentFetcher | None:
    """None = the deployment has no source-fetch integration: verification
    routes surface this as 503 (technical, discoverable — nothing is
    silently treated as verified)."""
    return get_content_fetcher()


def get_or_none_search_provider() -> SearchProvider | None:
    """None = search unavailable in this deployment (recorded as a gap)."""
    return get_search_provider()


_bearer = HTTPBearer(auto_error=False)


def get_user_repo(session: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(session)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    users: UserRepository = Depends(get_user_repo),
) -> User:
    unauthorized = HTTPException(
        status_code=401, detail="Sign in to continue.", headers={"WWW-Authenticate": "Bearer"}
    )
    if creds is None or creds.scheme.lower() != "bearer":
        raise unauthorized
    user_id = security.decode_access_token(creds.credentials)
    user = users.get(user_id) if user_id is not None else None
    if user is None:
        raise unauthorized
    return user


def _owned_case(cases: CaseRepository, case_id: int | None, user: User) -> BusinessCase | None:
    """Return the case only if it belongs to the user (404 semantics: never reveal others' ids)."""
    case = cases.get(case_id) if case_id is not None else None
    if case is None or case.owner_id != user.id:
        return None
    return case


def get_case_or_404(
    case_id: int,
    cases: CaseRepository = Depends(get_case_repo),
    user: User = Depends(get_current_user),
) -> BusinessCase:
    case = _owned_case(cases, case_id, user)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Business case {case_id} not found.")
    return case


CaseDep = BusinessCase
CaseIdDep = int


def get_hypothesis_or_404(
    hypothesis_id: int,
    hypotheses: HypothesisRepository = Depends(get_hypothesis_repo),
    cases: CaseRepository = Depends(get_case_repo),
    user: User = Depends(get_current_user),
) -> Hypothesis:
    hypothesis = hypotheses.get(hypothesis_id)
    if hypothesis is None or _owned_case(cases, hypothesis.business_case_id, user) is None:
        raise HTTPException(status_code=404, detail=f"Hypothesis {hypothesis_id} not found.")
    return hypothesis


def get_run_or_404(
    run_id: int,
    runs: RunRepository = Depends(get_run_repo),
    cases: CaseRepository = Depends(get_case_repo),
    user: User = Depends(get_current_user),
):
    run = runs.get(run_id)
    if run is None or _owned_case(cases, run.business_case_id, user) is None:
        raise HTTPException(status_code=404, detail=f"Investigation run {run_id} not found.")
    return run


def get_experiment_or_404(
    experiment_id: int,
    experiments: ExperimentRepository = Depends(get_experiment_repo),
    cases: CaseRepository = Depends(get_case_repo),
    user: User = Depends(get_current_user),
) -> Experiment:
    experiment = experiments.get(experiment_id)
    if experiment is None or _owned_case(cases, experiment.business_case_id, user) is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found.")
    return experiment


def get_evidence_or_404(
    evidence_id: int,
    evidence: EvidenceRepository = Depends(get_evidence_repo),
    cases: CaseRepository = Depends(get_case_repo),
    user: User = Depends(get_current_user),
) -> Evidence:
    row = evidence.get(evidence_id)
    if row is None or _owned_case(cases, row.business_case_id, user) is None:
        raise HTTPException(status_code=404, detail=f"Evidence {evidence_id} not found.")
    return row


def get_hypothesis_service(hypotheses: HypothesisRepository = Depends(get_hypothesis_repo)) -> HypothesisService:
    return HypothesisService(hypotheses)


def get_document_service(
    case: BusinessCase = Depends(get_case_or_404),
    uploads: UploadRepository = Depends(get_upload_repo),
) -> DocumentService:
    return DocumentService(uploads, case)


def get_evidence_service(
    evidence: EvidenceRepository = Depends(get_evidence_repo)
) -> EvidenceService:
    return EvidenceService(evidence)


def get_verification_service(
    verifier: ChatLLM = Depends(get_verifier),
    fetcher: ContentFetcher | None = Depends(get_or_none_content_fetcher),
    evidence: EvidenceRepository = Depends(get_evidence_repo),
    hypotheses: HypothesisRepository = Depends(get_hypothesis_repo),
    cases: CaseRepository = Depends(get_case_repo),
    runs: RunRepository = Depends(get_run_repo),
) -> VerificationService:
    return VerificationService(
        verifier_llm=verifier,
        fetcher=fetcher,
        evidence=evidence,
        hypotheses=hypotheses,
        cases=cases,
        runs=runs,
    )


def get_assessment_repo(session: Session = Depends(get_db)) -> AssessmentRepository:
    return AssessmentRepository(session)


def get_assessment_service(
    assessor: ChatLLM = Depends(get_assessor),
    evidence: EvidenceRepository = Depends(get_evidence_repo),
    hypotheses: HypothesisRepository = Depends(get_hypothesis_repo),
    assessments: AssessmentRepository = Depends(get_assessment_repo),
    cases: CaseRepository = Depends(get_case_repo),
    runs: RunRepository = Depends(get_run_repo),
    experiments: ExperimentRepository = Depends(get_experiment_repo),
) -> AssessmentService:
    return AssessmentService(
        assessor_llm=assessor,
        evidence=evidence,
        hypotheses=hypotheses,
        assessments=assessments,
        cases=cases,
        runs=runs,
        experiments=experiments,
    )


def get_experiment_service(
    designer: ChatLLM = Depends(get_experiment_designer),
    experiments: ExperimentRepository = Depends(get_experiment_repo),
    assessments: AssessmentRepository = Depends(get_assessment_repo),
    cases: CaseRepository = Depends(get_case_repo),
) -> ExperimentService:
    return ExperimentService(
        designer_llm=designer,
        experiments=experiments,
        assessments=assessments,
        cases=cases,
    )


def get_investigation_service(
    case: BusinessCase = Depends(get_case_or_404),
    planner: ChatLLM = Depends(get_planner),
    search_provider: SearchProvider | None = Depends(get_or_none_search_provider),
    hypotheses: HypothesisRepository = Depends(get_hypothesis_repo),
    evidence: EvidenceRepository = Depends(get_evidence_repo),
    runs: RunRepository = Depends(get_run_repo),
    uploads: UploadRepository = Depends(get_upload_repo),
) -> tuple[BusinessCase, InvestigationService]:
    return case, InvestigationService(
        planner_llm=planner,
        search_provider=search_provider,
        hypotheses=hypotheses,
        evidence=evidence,
        runs=runs,
        uploads=uploads,
    )


def value_error_status(exc: ValueError) -> tuple[int, str]:
    """Domain ValueErrors map to 404 for not-found, 400 otherwise."""
    if "not found" in str(exc).lower():
        return 404, str(exc)
    return 400, str(exc)


def domain_router_guard(action: Callable[[], object]):
    try:
        return action()
    except ValueError as exc:
        status, detail = value_error_status(exc)
        raise HTTPException(status_code=status, detail=detail)


# --- v4: sprints, scans, test kit ------------------------------------------------

def get_sprint_repo(session: Session = Depends(get_db)) -> SprintRepository:
    return SprintRepository(session)


def get_scan_repo(session: Session = Depends(get_db)) -> ScanRepository:
    return ScanRepository(session)


def get_sprint_service(sprints: SprintRepository = Depends(get_sprint_repo)) -> SprintService:
    return SprintService(sprints)


def get_sprint_or_404(
    sprint_id: int,
    sprints: SprintRepository = Depends(get_sprint_repo),
    cases: CaseRepository = Depends(get_case_repo),
    user: User = Depends(get_current_user),
) -> Sprint:
    sprint = sprints.get(sprint_id)
    if sprint is None or _owned_case(cases, sprint.business_case_id, user) is None:
        raise HTTPException(status_code=404, detail=f"Sprint {sprint_id} not found.")
    return sprint


def get_testkit_llm() -> ChatLLM:
    """Test-kit designer model. Overridable in tests."""
    return get_reasoning_llm()


def get_testkit_service(llm: ChatLLM = Depends(get_testkit_llm)) -> TestKitService:
    return TestKitService(llm)


def get_scan_executor() -> Callable[[int], None]:
    """Returns the function that runs a queued scan job to completion.

    Built per call so provider keys are read when the scan starts. Tests
    override this dependency with a stubbed executor."""

    def execute(job_id: int) -> None:
        deps = ScanDeps(
            extractor=get_extraction_llm(),
            planner=get_reasoning_llm(),
            verifier=get_verifier_llm(),
            assessor=get_verifier_llm(),
            search_provider=get_search_provider(),
            fetcher=get_content_fetcher(),
        )
        execute_scan(session_factory(), job_id, deps)

    return execute
