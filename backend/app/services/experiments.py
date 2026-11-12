"""Experiment designer service (Phase 6, SYSTEM_DESIGN §5 ExperimentDesigner).

Division of labor:
- Deterministic code: strict parsing/validation of proposals, atomic writes
  (validation happens BEFORE any row exists), status/consistency guards for
  PATCH and outcome entry.
- LLM (`deps.get_experiment_designer`, reasoning model): proposes concrete
  validation experiments for ONE hypothesis (unresolved or high-priority
  assumptions — PRODUCT_SPEC principle 9/§11). Numeric thresholds inside
  proposals are labeled suggested ASSUMPTIONS, never benchmarks
  (models.py/PRODUCT_SPEC.md §11).

Fail-closed semantics:
- Generation with unusable output after the bounded repair retry raises
  ExperimentDesignError (HTTP 502 semantics) and writes NOTHING.
- Recording an outcome needs criteria_result plus at least one content field
  (what actually happened) — durable timestamped outcomes, never empty verbs.
- Once outcomes exist, an experiment's text fields are FROZEN (they are what
  the outcome was judged against); status may only move to completed/
  cancelled. Iterating means generating a NEW experiment, not rewriting the
  judged one.

Core loop (PRODUCT_SPEC §12): recording an outcome RECOMMENDS re-assessment
(a new append-only assessment version); it never silently overwrites history
— assessment remains a separate user action that now considers recorded
outcomes.
"""

from __future__ import annotations

import json
from typing import Any

from ..common import LLMParseError, ask_json_with_repair, strip_code_fence
from ..domain.enums import ExperimentStatus
from ..domain.models import BusinessCase, Experiment, Hypothesis, HypothesisAssessment
from ..integrations.llm.provider import ChatLLM
from ..repositories import (
    AssessmentRepository,
    CaseRepository,
    ExperimentRepository,
)

DESIGN_PROMPT_VERSION = "design-6.0.0"

DESIGN_SYSTEM_PROMPT = """You are the ExperimentDesigner for an evidence-first due diligence system.

You design 1-3 CONCRETE validation experiments for ONE business hypothesis,
choosing from these types (PRODUCT_SPEC §11): customer interviews,
landing-page/waitlist tests, pricing tests, paid pilots, pre-orders,
concierge/manual pilots, competitor-switching interviews, prototype tests.

Rules:
- Experiments must TEST the hypothesis's specific assumption — prefer minimal
  effort that resolves the current uncertainty (look at the latest assessment
  status, its gaps and recommended next step when given).
- Success and failure criteria must be CONCRETE and observable (what number,
  what behavior, what threshold) — never "positive feedback".
- Numeric thresholds (prices, percentages, counts) you suggest are SUGGESTED
  STARTING ASSUMPTIONS to be challenged — NEVER industry benchmarks, unless
  the evidence provided actually supports a number.
- Use the user guidance as INTENT. Never fabricate facts, sources, or prices.
- Respond with ONLY valid JSON, no markdown fences, no commentary:
{
  "experiments": [
    {
      "title": "short name",
      "objective": "what question this answers",
      "method": "how it runs",
      "target_participants": "who",
      "recruitment_approach": "how to reach them",
      "resources": "what is needed",
      "estimated_duration": "e.g. 'about two weeks' (plain text)",
      "estimated_cost": "plain text estimate with assumption basis",
      "cost_assumptions": "explicit assumptions behind any number",
      "success_criteria": "observable condition that would support the hypothesis",
      "failure_criteria": "observable condition that would refute it",
      "data_to_collect": [
        {"field": "number_of_paid_signups", "description": "Count of people who paid", "unit": "people"},
        {"field": "repeat_orders", "description": "Number of customers ordering again", "unit": "orders"}
      ],
      "risks": "what could distort the result"
    }
  ]
}"""

MAX_REPAIR_ATTEMPTS = 1
MAX_EXPERIMENTS_PER_GENERATION = 3  # documented MVP bound (planner-style cap)

REQUIRED_FIELDS = ("title", "objective", "method", "success_criteria", "failure_criteria")
OPTIONAL_FIELDS = (
    "target_participants",
    "recruitment_approach",
    "resources",
    "estimated_duration",
    "estimated_cost",
    "cost_assumptions",
    "data_to_collect",
    "risks",
)


def _normalize_data_to_collect(value: Any) -> str | None:
    """Accept legacy text and the 2.2 structured measurement list.

    The current database column remains TEXT for backward compatibility.
    Structured lists are serialized as JSON; legacy strings remain unchanged.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, list):
        raise TypeError("experiment 'data_to_collect' must be text or a list of measurement fields")
    normalized = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            field = item.strip()
            if not field:
                raise ValueError(f"data_to_collect item #{index + 1} is empty")
            normalized.append({"field": field, "description": field, "unit": None})
            continue
        if not isinstance(item, dict):
            raise TypeError(f"data_to_collect item #{index + 1} must be text or an object")
        field = item.get("field")
        description = item.get("description")
        unit = item.get("unit")
        if not isinstance(field, str) or not field.strip():
            raise ValueError(f"data_to_collect item #{index + 1} requires a non-empty field")
        if description is not None and not isinstance(description, str):
            raise TypeError(f"data_to_collect item #{index + 1} description must be text")
        if unit is not None and not isinstance(unit, str):
            raise TypeError(f"data_to_collect item #{index + 1} unit must be text")
        normalized.append({
            "field": field.strip(),
            "description": (description or "").strip() or field.strip(),
            "unit": (unit or "").strip() or None,
        })
    if not normalized:
        return None
    return json.dumps(normalized, ensure_ascii=False)


class ExperimentDesignError(RuntimeError):
    """Design failed technically (unusable output after repair, provider
    unavailable). No experiment rows are written; routes map to 502."""


def _str_or_none(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"experiment '{field}' must be a string")
    value = value.strip()
    return value or None


def parse_design(raw: str) -> list[dict]:
    """Strict parse of the designer output. ALL proposals must validate
    before any row is written (atomic generation)."""
    payload = json.loads(strip_code_fence(raw))
    if not isinstance(payload, dict):
        raise TypeError("designer output is not a JSON object")
    experiments = payload.get("experiments")
    if not isinstance(experiments, list):
        raise TypeError("designer output missing 'experiments' list")
    experiments = experiments[:MAX_EXPERIMENTS_PER_GENERATION]  # MVP bound, planner-style
    if not experiments:
        raise ValueError("designer proposed no experiments")

    parsed: list[dict] = []
    for index, item in enumerate(experiments):
        if not isinstance(item, dict):
            raise TypeError(f"experiment #{index + 1} is not a JSON object")
        proposal: dict[str, str | None] = {}
        for field in REQUIRED_FIELDS:
            value = _str_or_none(item.get(field), field)
            if not value:
                raise ValueError(f"experiment #{index + 1}: '{field}' is required and must not be empty")
            proposal[field] = value
        for field in OPTIONAL_FIELDS:
            if field == "data_to_collect":
                proposal[field] = _normalize_data_to_collect(item.get(field))
            else:
                proposal[field] = _str_or_none(item.get(field), field)
        parsed.append(proposal)
    return parsed


def build_design_prompt(
    hypothesis: Hypothesis,
    case: BusinessCase | None,
    latest: HypothesisAssessment | None,
    guidance: str | None = None,
) -> str:
    lines = []
    if case is not None:
        lines.append(f"BUSINESS CASE: {case.title}")
        if case.idea_description:
            lines.append(f"BUSINESS CASE IDEA: {case.idea_description}")
    category = getattr(hypothesis.category, "value", hypothesis.category)
    lines.append(f"HYPOTHESIS ({category}): {hypothesis.statement}")
    if hypothesis.rationale:
        lines.append(f"HYPOTHESIS_RATIONALE (user/extractor claim, not verified): {hypothesis.rationale}")
    if latest is None:
        lines.append("LATEST ASSESSMENT: none yet — design for the most decisive first check.")
    else:
        status = getattr(latest.status, "value", latest.status)
        lines.append(
            f"LATEST ASSESSMENT (version {latest.version}): status={status}"
            f" — evidence_gaps={latest.evidence_gaps or 'n/a'};"
            f" recommended_next_step={latest.recommended_next_step or 'n/a'}"
        )
    if guidance:
        lines.append(f"USER GUIDANCE (intent): {guidance}")
    return "\n".join(lines)


class ExperimentService:
    def __init__(
        self,
        *,
        designer_llm: ChatLLM,
        experiments: ExperimentRepository,
        assessments: AssessmentRepository | None = None,
        cases: CaseRepository | None = None,
    ):
        self._llm = designer_llm
        self._experiments = experiments
        self._assessments = assessments
        self._cases = cases

    # --- generation ------------------------------------------------------------

    def generate(self, hypothesis: Hypothesis, guidance: str | None = None) -> list[Experiment]:
        """Propose + persist up to 3 experiments (status=proposed) linked to
        the hypothesis. Validation before any write: unusable output raises
        and writes nothing."""
        case = self._cases.get(hypothesis.business_case_id) if self._cases is not None else None
        latest = self._assessments.latest(hypothesis.id) if self._assessments is not None else None
        prompt = build_design_prompt(hypothesis, case, latest, guidance)
        try:
            proposals = ask_json_with_repair(
                self._llm,
                prompt,
                parse_design,
                max_repair_attempts=MAX_REPAIR_ATTEMPTS,
                system=DESIGN_SYSTEM_PROMPT,
            )
        except LLMParseError as exc:
            raise ExperimentDesignError(
                "Experiment design produced unusable output after repair retry. " + str(exc)
            ) from exc
        except Exception as exc:
            raise ExperimentDesignError(f"Designer unavailable ({type(exc).__name__}): {exc}") from exc

        return [
            self._experiments.create(
                hypothesis.business_case_id,
                proposal["title"],
                hypothesis_id=hypothesis.id,
                objective=proposal["objective"],
                method=proposal["method"],
                success_criteria=proposal["success_criteria"],
                failure_criteria=proposal["failure_criteria"],
                **{key: proposal[key] for key in OPTIONAL_FIELDS},
            )
            for proposal in proposals
        ]

    # --- status/field management -------------------------------------------------

    def update(self, experiment: Experiment, payload: dict[str, Any]) -> Experiment:
        """User edit/manage. Once outcomes exist the experiment's judged
        content is frozen; only status moves to completed/cancelled."""
        has_outcomes = bool(self._experiments.list_outcomes(experiment.id))
        if has_outcomes:
            status = payload.get("status")
            if status is not None:
                value = ExperimentStatus(status).value
                if value not in (ExperimentStatus.COMPLETED.value, ExperimentStatus.CANCELLED.value):
                    raise ValueError(
                        f"Experiment {experiment.id} has recorded outcomes — status may only become "
                        f"completed or cancelled (open a new experiment to iterate)."
                    )
            if set(payload) - {"status"}:
                raise ValueError(
                    f"Experiment {experiment.id} has recorded outcomes — its criteria/method cannot be "
                    "edited after the fact; generate a new experiment to iterate."
                )
        # No outcomes recorded: the user owns status + fields (honest corrections).
        return self._experiments.update(experiment.id, payload)

    # --- outcomes ----------------------------------------------------------------

    def add_outcome(self, experiment: Experiment, payload: dict[str, Any]) -> tuple[ExperimentOutcome, dict]:
        """Append-only timestamped outcome + a re-assessment RECOMMENDATION
        (never an automatic overwrite of history)."""
        status = ExperimentStatus(experiment.status).value
        if status in (ExperimentStatus.PROPOSED.value, ExperimentStatus.PLANNED.value):
            raise ValueError(
                f"Experiment {experiment.id} is '{status}' — record outcomes for "
                "in_progress/completed/cancelled experiments (update its real status first)."
            )
        if not payload.get("criteria_result"):
            raise ValueError("criteria_result is required to compare the outcome against the criteria.")
        if not any(
            (payload.get(key) or "").strip()
            for key in ("observations", "measurements", "notes_quotes")
        ):
            raise ValueError(
                "Record at least observations, measurements, or notes/quotes — "
                "an outcome must carry what actually happened."
            )
        outcome = self._experiments.add_outcome(experiment.id, **payload)
        criteria = getattr(outcome.criteria_result, "value", outcome.criteria_result)
        suggestion = {
            "recommended": True,
            "hypothesis_id": experiment.hypothesis_id,
            "reason": (
                f"criteria_result '{criteria}' recorded for experiment {experiment.id} "
                f"('{experiment.title}') — run an assessment to fold this outcome into a "
                "new append-only assessment version (history stays intact)."
            ),
        }
        return outcome, {"assessment_suggestion": suggestion}

    def outcomes(self, experiment_id: int) -> list[ExperimentOutcome]:
        return self._experiments.list_outcomes(experiment_id)

    def list_case(self, case_id: int) -> list[Experiment]:
        return self._experiments.list_by_case(case_id)
