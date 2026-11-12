"""
Hypothesis extraction service (Phase 2).

Converts a business case into explicit, testable, falsifiable candidate
hypotheses. Rules enforced here:

- Missing optional context lists as explicit GAPS in the prompt and in the
  response metadata — the model is told NOT to invent missing context.
- Generated hypotheses are candidates with `current_status=unknown` and
  `origin=ai_generated` — never verified facts.
- Malformed model output triggers ONE bounded self-repair retry; failure after
  that raises ExtractionError (no fabricated success). Category values that
  fall outside the vocabulary coerce to `other`; blank statements and exact
  duplicates are dropped/deduplicated rather than stored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..common import LLMParseError, ask_json_with_repair, strip_code_fence
from ..domain.enums import HypothesisCategory
from ..domain.models import BusinessCase
from ..integrations.llm.provider import ChatLLM, get_extraction_llm

PROMPT_VERSION = "extract-2.0.0"

EXTRACTION_SYSTEM_PROMPT = """You are the hypothesis extractor for an evidence-first due diligence system.

Given a business idea and its context, propose explicit TESTABLE hypotheses — each a single
falsifiable claim someone could investigate with evidence or an experiment. Cover the
categories that matter for THIS idea among: customer_problem, market_demand,
competition_alternatives, willingness_to_pay, pricing, distribution_acquisition,
unit_economics, operations, technology_feasibility, legal_regulatory, other.

Rules:
- No generic filler ("there is demand", "the market is growing"). Each hypothesis must be
  specific enough that it could be contradicted by evidence.
- 4 to 8 hypotheses. Prefer the highest-leverage assumptions (problem, demand, WTP,
  competition, unit economics) for this specific idea.
- If a hypothesis would depend on context that is listed as a GAP in the input, say so in
  `rationale` — do NOT invent the missing context.
- Keep statements self-contained (no "the stated problem"): reference the actual subject.

Respond with ONLY valid JSON, no markdown fences, no commentary:
{
  "hypotheses": [
    {
      "statement": "string",
      "category": "<category-slug from the list above>",
      "rationale": "why this assumption matters for THIS idea (optionally noting gaps)",
      "customer_segment": "string or null",
      "geography": "string or null",
      "priority": "high | medium | low",
      "testability_notes": "how one would test or gather evidence for it"
    }
  ]
}"""

MAX_REPAIR_ATTEMPTS = 1

_NORMALIZED_PRIORITIES = {"high", "medium", "low"}


class ExtractionError(RuntimeError):
    """Model output was malformed after the bounded repair retry."""


@dataclass
class ExtractionResult:
    hypotheses: list[dict] = field(default_factory=list)
    raw_candidates: int = 0
    dropped_invalid: int = 0
    deduplicated: int = 0
    context_gaps: list[str] = field(default_factory=list)


def _case_gaps(case: BusinessCase) -> list[str]:
    """Optional intake fields that were NOT provided — explicit gaps."""
    optional_fields = (
        ("geography", case.geography),
        ("target_customer", case.target_customer),
        ("customer_problem", case.customer_problem),
        ("proposed_solution", case.proposed_solution),
        ("business_stage", case.business_stage),
        ("pricing_model", case.pricing_model),
        ("budget_constraints", case.budget_constraints),
        ("known_competitors", case.known_competitors),
        ("user_questions", case.user_questions),
    )
    return [name for name, value in optional_fields if not value]


def build_extraction_prompt(case: BusinessCase) -> str:
    def line(label: str, value: Any) -> str:
        if value:
            return f"{label}: {value}"
        return None

    lines = [line(l, v) for l, v in (
        ("TITLE", case.title),
        ("IDEA", case.idea_description),
        ("GEOGRAPHY", case.geography),
        ("TARGET_CUSTOMER", case.target_customer),
        ("CUSTOMER_PROBLEM", case.customer_problem),
        ("PROPOSED_SOLUTION", case.proposed_solution),
        ("BUSINESS_STAGE", case.business_stage),
        ("PRICING_MODEL", case.pricing_model),
        ("BUDGET_CONSTRAINTS", case.budget_constraints),
        ("KNOWN_COMPETITORS", case.known_competitors),
        ("USER_QUESTIONS", case.user_questions),
    ) if line(l, v)]
    if _case_gaps(case):
        gaps = ", ".join(_case_gaps(case))
        lines.append(f"CONTEXT GAPS (missing; do not invent): {gaps}")
    return "\n".join(lines)


def _normalize_category(raw: Any) -> str:
    try:
        HypothesisCategory(str(raw).strip().lower())
        return str(raw).strip().lower()
    except ValueError:
        return HypothesisCategory.OTHER.value


def _normalize_priority(raw: Any) -> str | None:
    value = str(raw or "").strip().lower()
    return value if value in _NORMALIZED_PRIORITIES else None


def parse_and_validate(raw: str, existing_statements: Iterable[str] = ()) -> ExtractionResult:
    """Parse the model's JSON output into validated candidate dicts.

    Raises json.JSONDecodeError / AttributeError on fundamentally malformed
    output (the caller retries once, then fails explicitly).
    """
    payload = json.loads(strip_code_fence(raw))
    items = payload["hypotheses"]  # KeyError means wrong shape -> malformed

    result = ExtractionResult(context_gaps=[])
    seen: set[str] = set()
    for existing in existing_statements:
        seen.add(existing.strip().casefold())

    result.raw_candidates = len(items)
    for item in items:
        if not isinstance(item, dict):
            result.dropped_invalid += 1
            continue
        statement = str(item.get("statement", "")).strip()
        if not statement:
            result.dropped_invalid += 1
            continue
        key = statement.casefold()
        if key in seen:
            result.deduplicated += 1
            continue
        seen.add(key)
        result.hypotheses.append({
            "statement": statement,
            "category": _normalize_category(item.get("category")),
            "rationale": (str(item.get("rationale")).strip() or None) if item.get("rationale") else None,
            "customer_segment": (str(item.get("customer_segment")).strip() or None) if item.get("customer_segment") else None,
            "geography": (str(item.get("geography")).strip() or None) if item.get("geography") else None,
            "priority": _normalize_priority(item.get("priority")),
            "testability_notes": (str(item.get("testability_notes")).strip() or None) if item.get("testability_notes") else None,
        })
    return result


class HypothesisExtractionService:
    def __init__(self, llm: ChatLLM | None = None):
        self._llm = llm

    def extract(self, case: BusinessCase, existing_statements: Iterable[str] = ()) -> tuple[ExtractionResult, dict]:
        """Run extraction against a case. Returns (validated candidates, meta).

        Bounded retry: one repair attempt on malformed JSON; extraction then
        fails explicitly rather than fabricating hypotheses.
        """
        def _parse(raw: str) -> tuple[ExtractionResult, dict, list]:
            try:
                result = parse_and_validate(raw, existing_statements)
            except Exception as exc:  # normalized -> repair prompt rebuilds
                raise LLMParseError(str(exc)) from exc
            context_gaps = _case_gaps(case)
            result.context_gaps = context_gaps
            meta = {
                **llm.describe(),
                "prompt_version": PROMPT_VERSION,
                "context_gaps": context_gaps,
            }
            return result, meta

        prompt = build_extraction_prompt(case)
        llm = self._llm if self._llm is not None else get_extraction_llm()
        try:
            result, meta = ask_json_with_repair(
                llm, prompt, _parse, max_repair_attempts=MAX_REPAIR_ATTEMPTS,
                system=EXTRACTION_SYSTEM_PROMPT,
            )
        except LLMParseError as exc:
            raise ExtractionError(str(exc)) from exc
        return result, meta

