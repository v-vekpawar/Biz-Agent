"""Investigation service (Phase 3): per-hypothesis plans, search collection,
uploaded-document ingestion, normalization + dedup, and durable evidence.

Division of labor (SYSTEM_DESIGN §7):
- LLM (InvestigationPlanner role, via ChatLLM protocol): evidence needs,
  research questions, and search queries for ONE hypothesis at a time, with
  the same bounded self-repair semantics as extraction (common.ask_json_with_repair).
- Deterministic code (this module): run transitions, query dedup/economy,
  evidence normalization, URL dedup WITHOUT losing links, document ingestion,
  provenance events, and honest gap accounting.

Nothing here invents metadata: fields a provider did not return stay None,
and every evidence row carries an explicit honesty note in `limitations`.
Links default to `neutral` — support/contradict classification is Phase 4's
EvidenceVerifier's job, not the collector's. Uploaded documents are ingested
as case-level evidence (their excerpt/content is recorded) but are NOT
auto-linked to hypotheses; users/linking APIs decide relevance.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..common import LLMParseError, ask_json_with_repair, strip_code_fence
from ..domain.enums import (
    DocumentProcessingStatus,
    EvidenceKind,
    EvidenceRelationship,
    RunStatus,
)
from ..domain.models import BusinessCase, Evidence, Hypothesis, InvestigationRun, UploadedDocument
from ..integrations.llm.provider import ChatLLM
from ..integrations.search.base import SearchProvider, SearchHit, normalize_url
from ..repositories import (
    EvidenceRepository,
    HypothesisRepository,
    RunRepository,
    UploadRepository,
)

PLANNER_PROMPT_VERSION = "plan-5.0.0"

PLAN_SYSTEM_PROMPT = """You are the investigation planner for an evidence-first due diligence system.

You are given ONE hypothesis about a business case plus available context (missing
context is listed as GAPS — do not invent it). Plan how to investigate this
specific hypothesis, in BOTH directions.

Produce:
- evidence_needs: what information would support or contradict THIS hypothesis.
- research_questions: the questions a researcher should answer.
- disconfirmation_questions: 1-3 questions that could definitively FALSIFY this
  hypothesis (what would the world look like if the hypothesis is FALSE?).
- search_queries: 1 to 4 concrete web search queries that could surface
  SUPPORTING evidence (keywords optimized for a search engine: include the
  product category, geography/segment hints where given, and intent terms like
  pricing, reviews, competitors, market size).
- counter_evidence_queries: 1 to 4 DISTINCT web search queries aimed at finding
  COUNTER-evidence: failed lawsuits/gate reviews, low ratings, substitutions
  winning, price collapse, evidence the problem is already solved, regulatory
  bans, market decline. Do NOT rephrase the supporting queries; attack the
  hypothesis from the opposite side. If the hypothesis cannot be attacked by
  any web search, return an empty list and say so in evidence_needs.

Respond with ONLY valid JSON, no markdown fences, no commentary:
{
  "evidence_needs": ["string", ...],
  "research_questions": ["string", ...],
  "disconfirmation_questions": ["string", ...],
  "search_queries": ["string", ...],
  "counter_evidence_queries": ["string", ...]
}"""

MAX_REPAIR_ATTEMPTS = 1
MAX_QUERIES_PER_HYPOTHESIS = 2
MAX_DISCONFIRMATION_QUESTIONS = 3
RESULTS_PER_QUERY = 2
DOCUMENT_EXCERPT_CHARS = 2000
SNIPPET_EXCERPT_CHARS = 1000

SEARCH_LIMITATION_NOTE = (
    "Collected from web search results ({provider}). The excerpt is the search "
    "provider's snippet/content excerpt, not independently read or verified; "
    "treated as indirect."
)
DOCUMENT_LIMITATION_NOTE = (
    "User-uploaded document; contents are quoted from the file and have not "
    "been independently verified."
)


class InvestigationError(RuntimeError):
    """Technical failure (planner output unusable, search provider crash).
    Persisted as run.status=failed — DISTINCT from 'search found nothing', a gap."""

    @classmethod
    def from_planner_failure(cls, exc: LLMParseError) -> "InvestigationError":
        return cls(
            "Investigation planning produced unparsable output after repair retry. "
            + str(exc)
        )


@dataclass
class ParsedPlan:
    evidence_needs: list[str]
    research_questions: list[str]
    search_queries: list[str]
    counter_evidence_queries: list[str]
    disconfirmation_questions: list[str]


@dataclass
class HypothesisPlan:
    hypothesis_id: int
    evidence_needs: list[str] = field(default_factory=list)
    research_questions: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    counter_evidence_queries: list[str] = field(default_factory=list)
    disconfirmation_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "evidence_needs": self.evidence_needs,
            "research_questions": self.research_questions,
            "search_queries": self.search_queries,
            "counter_evidence_queries": self.counter_evidence_queries,
            "disconfirmation_questions": self.disconfirmation_questions,
        }


def _clean_str_list(items: Iterable[Any], *, cap: int | None = None) -> list[str]:
    """Strip + drop non-strings/empties; casefold-dedup with an optional cap."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            value = item.strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(value)
            if cap is not None and len(cleaned) >= cap:
                break
    return cleaned


def build_planning_prompt(hypothesis: Hypothesis, case: BusinessCase) -> str:
    category = getattr(hypothesis.category, "value", hypothesis.category)
    lines = [
        f"HYPOTHESIS ({category}): {hypothesis.statement}",
    ]
    for label, value in (
        ("RATIONALE", hypothesis.rationale),
        ("CUSTOMER_SEGMENT", hypothesis.customer_segment),
        ("GEOGRAPHY", hypothesis.geography),
        ("PRIORITY", hypothesis.priority),
        ("TESTABILITY_NOTES", hypothesis.testability_notes),
    ):
        if value:
            lines.append(f"{label}: {value}")

    for label, value in (
        ("CASE_TITLE", case.title),
        ("IDEA", case.idea_description),
        ("CASE_GEOGRAPHY", case.geography),
        ("TARGET_CUSTOMER", case.target_customer),
        ("CUSTOMER_PROBLEM", case.customer_problem),
        ("PROPOSED_SOLUTION", case.proposed_solution),
        ("BUSINESS_STAGE", case.business_stage),
        ("PRICING_MODEL", case.pricing_model),
        ("KNOWN_COMPETITORS", case.known_competitors),
        ("USER_QUESTIONS", case.user_questions),
    ):
        if value:
            lines.append(f"{label}: {value}")

    missing = [
        name
        for name, value in (
            ("geography", case.geography),
            ("target_customer", case.target_customer),
            ("customer_problem", case.customer_problem),
            ("proposed_solution", case.proposed_solution),
            ("business_stage", case.business_stage),
            ("pricing_model", case.pricing_model),
            ("budget_constraints", case.budget_constraints),
            ("known_competitors", case.known_competitors),
        )
        if not value
    ]
    if missing:
        lines.append("CONTEXT GAPS (missing; do not invent): " + ", ".join(missing))
    return "\n".join(lines)


def parse_plan(raw: str) -> ParsedPlan:
    """Parse + normalize planner JSON.

    The three v1 keys (evidence_needs, research_questions, search_queries)
    must be present as JSON lists — a dict without them is malformed and
    triggers the bounded repair retry, not silent acceptance. The Phase 4
    direction keys (counter_evidence_queries, disconfirmation_questions) are
    optional and default to [] when absent (older prompts stay parseable).
    """
    payload = json.loads(strip_code_fence(raw))
    if not isinstance(payload, dict):
        raise TypeError("planner output is not a JSON object")
    for key in ("evidence_needs", "research_questions", "search_queries"):
        if not isinstance(payload.get(key), list):
            raise TypeError(f"planner output missing or invalid '{key}' list")
    # Phase 4 direction keys: absent -> [] (legacy tolerance); present but
    # non-list -> malformed (repair retry), never character-mangled.
    optional_lists = {}
    for key, cap in (
        ("counter_evidence_queries", MAX_QUERIES_PER_HYPOTHESIS),
        ("disconfirmation_questions", MAX_DISCONFIRMATION_QUESTIONS),
    ):
        value = payload.get(key)
        if value is None:
            value = []
        if not isinstance(value, list):
            raise TypeError(f"planner '{key}' must be a list of strings")
        optional_lists[key] = _clean_str_list(value, cap=cap)
    return ParsedPlan(
        evidence_needs=_clean_str_list(payload["evidence_needs"]),
        research_questions=_clean_str_list(payload["research_questions"]),
        search_queries=_clean_str_list(payload["search_queries"], cap=MAX_QUERIES_PER_HYPOTHESIS),
        counter_evidence_queries=optional_lists["counter_evidence_queries"],
        disconfirmation_questions=optional_lists["disconfirmation_questions"],
    )


def _parse_plan_or_raise(raw: str) -> ParsedPlan:
    try:
        return parse_plan(raw)
    except Exception as exc:  # normalized for ask_json_with_repair
        raise LLMParseError(str(exc)) from exc


class InvestigationService:
    def __init__(
        self,
        *,
        planner_llm: ChatLLM,
        search_provider: SearchProvider | None,
        hypotheses: HypothesisRepository,
        evidence: EvidenceRepository,
        runs: RunRepository,
        uploads: UploadRepository,
    ):
        self._planner = planner_llm
        self._search = search_provider
        self._hypotheses = hypotheses
        self._evidence = evidence
        self._runs = runs
        self._uploads = uploads
        self._prefetched_search_results: dict[str, list[SearchHit]] = {}

    # --- public entry point ---------------------------------------------------

    def investigate_case(
        self,
        case: BusinessCase,
        hypothesis_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Run a full investigation pass for the given hypotheses (default:
        every hypothesis in the case). Returns a serializable summary.

        Semantics:
        - Technical failure (planner unusable, provider crash) -> run FAILED
          and the original error is re-raised (routes map to 502).
        - No search provider / empty results / failed document extraction are
          GAPS -> run completes as completed_with_gaps (no fabricated evidence).
        - Input validation (bad hypothesis ids) raises BEFORE any run is
          created, so no poisoned run rows accumulate.
        """
        targets = self._resolve_targets(case.id, hypothesis_ids)
        run: InvestigationRun = self._runs.create(
            case.id,
            requested_scope={"hypothesis_ids": list(hypothesis_ids or [])},
        )
        self._runs.start(run.id)

        events: list[dict] = []
        gaps: list[str] = []

        try:
            plans = self._plan_all(targets, case, events)
            # Search calls are independent network I/O. Fetch them concurrently
            # with a small configurable cap, then persist/link results in the
            # original deterministic order on this thread/session.
            self._prefetched_search_results = self._prefetch_searches(plans, events, gaps)
            evidence_by_url: dict[str, Evidence] = self._evidence_key_map(case.id)
            query_memo: dict[str, list[int]] = {}

            created: list[Evidence] = []
            reused: list[Evidence] = []
            links = 0

            for plan, target in plans:
                already_linked = {
                    evidence.id for evidence, _ in self._evidence.links_for_hypothesis(target.id)
                }
                if not plan.search_queries:
                    gaps.append(
                        f"hypothesis {target.id}: planner produced no supporting web search queries"
                    )
                for query in plan.search_queries:
                    links += self._collect_direction(
                        case.id,
                        plan,
                        target,
                        query,
                        evidence_by_url,
                        query_memo,
                        already_linked,
                        created,
                        reused,
                        events,
                        gaps,
                    )
                if not plan.counter_evidence_queries:
                    gaps.append(
                        f"hypothesis {target.id}: planner produced no counter-evidence queries"
                    )
                for query in plan.counter_evidence_queries:
                    links += self._collect_direction(
                        case.id,
                        plan,
                        target,
                        query,
                        evidence_by_url,
                        query_memo,
                        already_linked,
                        created,
                        reused,
                        events,
                        gaps,
                        direction="counter",
                    )

            gathered_docs = self._ingest_documents(case, events, gaps)
            created.extend(gathered_docs)

            produced_any_evidence = bool(created) or bool(gathered_docs)
            self._runs.complete(
                run.id,
                with_gaps=(gaps or not produced_any_evidence),
                workflow_metadata={
                    "prompt_version": PLANNER_PROMPT_VERSION,
                    "search_provider": getattr(self._search, "provider_name", None),
                    "plans": [plan.to_dict() for plan, _ in plans],
                    "events": events,
                    "gaps": gaps,
                },
            )
            return {
                "run": run,
                "plans": [plan for plan, _target in plans],
                "created": created,
                "reused": reused,
                "links": links,
                "gaps": gaps,
            }
        except Exception as exc:
            self._runs.fail(run.id, f"{type(exc).__name__}: {exc}")
            raise

    # --- steps --------------------------------------------------------------

    def _prefetch_searches(
        self,
        plans: list[tuple[HypothesisPlan, Hypothesis]],
        events: list[dict],
        gaps: list[str],
    ) -> dict[str, list[SearchHit]]:
        if self._search is None:
            return {}
        queries: list[str] = []
        seen: set[str] = set()
        for plan, _target in plans:
            for query in [*plan.search_queries, *plan.counter_evidence_queries]:
                key = query.casefold()
                if key and key not in seen:
                    seen.add(key)
                    queries.append(query)
        if not queries:
            return {}
        try:
            workers = int(os.getenv("BIZAGENT_SCAN_SEARCH_CONCURRENCY", "3"))
        except ValueError:
            workers = 3
        workers = max(1, min(workers, 4, len(queries)))
        results: dict[str, list[SearchHit]] = {}
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bizagent-search") as pool:
            futures = {
                pool.submit(self._search.search, query, max_results=RESULTS_PER_QUERY): query
                for query in queries
            }
            for future in as_completed(futures):
                query = futures[future]
                try:
                    results[query.casefold()] = future.result()
                except Exception as exc:
                    raise InvestigationError(
                        f"Search provider crashed on query {query!r}: {type(exc).__name__}: {exc}"
                    ) from exc
        events.append({
            "type": "search_batch",
            "queries": len(queries),
            "concurrency": workers,
            "provider": self._search.provider_name,
        })
        return results

    def _resolve_targets(self, case_id: int, hypothesis_ids: list[int] | None) -> list[Hypothesis]:
        if hypothesis_ids:
            targets = [self._hypotheses.require(hid) for hid in hypothesis_ids]
            foreign = [t for t in targets if t.business_case_id != case_id]
            if foreign:
                ids = ", ".join(str(t.id) for t in foreign)
                raise ValueError(
                    f"Hypotheses {ids} not found in business case {case_id} "
                    f"(they belong to other cases)."
                )
            return targets
        return self._hypotheses.list_by_case(case_id)

    def _plan_all(
        self,
        targets: list[Hypothesis],
        case: BusinessCase,
        events: list[dict],
    ) -> list[tuple[HypothesisPlan, Hypothesis]]:
        plans: list[tuple[HypothesisPlan, Hypothesis]] = []
        for target in targets:
            prompt = build_planning_prompt(target, case)
            try:
                parsed = ask_json_with_repair(
                    self._planner,
                    prompt,
                    _parse_plan_or_raise,
                    max_repair_attempts=MAX_REPAIR_ATTEMPTS,
                    system=PLAN_SYSTEM_PROMPT,
                )
            except LLMParseError as exc:
                raise InvestigationError.from_planner_failure(exc) from exc
            except Exception as exc:
                # Provider misconfiguration/network (e.g. missing key) — a
                # technical failure, persisted on the run, never a fake success.
                raise InvestigationError(
                    f"Planner unavailable ({type(exc).__name__}): {exc}"
                ) from exc
            plans.append(
                (
                    HypothesisPlan(
                        hypothesis_id=target.id,
                        evidence_needs=parsed.evidence_needs,
                        research_questions=parsed.research_questions,
                        search_queries=parsed.search_queries,
                        counter_evidence_queries=parsed.counter_evidence_queries,
                        disconfirmation_questions=parsed.disconfirmation_questions,
                    ),
                    target,
                )
            )
            events.append(
                {
                    "type": "plan",
                    "hypothesis_id": target.id,
                    "queries": parsed.search_queries,
                    "counter_queries": parsed.counter_evidence_queries,
                }
            )
        return plans

    def _evidence_key_map(self, case_id: int) -> dict[str, Evidence]:
        mapping: dict[str, Evidence] = {}
        for evidence in self._evidence.list_by_case(case_id):
            key = normalize_url(evidence.source_url)
            if key:
                mapping[key] = evidence
        return mapping

    def _collect_direction(
        self,
        case_id: int,
        plan: HypothesisPlan,
        target: Hypothesis,
        query: str,
        evidence_by_url: dict[str, Evidence],
        query_memo: dict[str, list[int]],
        already_linked: set[int],
        created: list[Evidence],
        reused: list[Evidence],
        events: list[dict],
        gaps: list[str],
        direction: str = "supporting",
    ) -> int:
        """Run one planned query in one direction (supporting/counter) and link
        its evidence to the hypothesis neutrally. Returns new links created.

        The query memo is SHARED across directions: an identical query text
        (casefolded) is executed once per run no matter which list asked for
        it; the event log shows which direction actually executed it.
        """
        key = query.casefold()
        evidence_ids = query_memo.get(key)
        if evidence_ids is None:
            evidence_ids = self._execute_query(
                case_id,
                query,
                evidence_by_url,
                created,
                reused,
                events,
                gaps,
                direction=direction,
            )
            query_memo[key] = evidence_ids
        new_links = 0
        for evidence_id in evidence_ids:
            if evidence_id in already_linked:
                continue  # idempotent: pair already exists
            already_linked.add(evidence_id)
            self._evidence.link(
                target.id,
                evidence_id,
                EvidenceRelationship.NEUTRAL,
                None,
            )
            new_links += 1
        return new_links

    def _execute_query(
        self,
        case_id: int,
        query: str,
        evidence_by_url: dict[str, Evidence],
        created: list[Evidence],
        reused: list[Evidence],
        events: list[dict],
        gaps: list[str],
        direction: str = "supporting",
    ) -> list[int]:
        """Run one search query; create or reuse evidence rows; return the ids
        that should be linked from the requesting hypothesis. Event/gap names
        are direction-qualified (search vs counter_search)."""
        prefix = "" if direction == "supporting" else "counter_"
        if self._search is None:
            gaps.append(
                f"search provider not configured — {direction} query {query!r} not executed"
            )
            events.append(
                {
                    "type": f"{prefix}search_gap",
                    "query": query,
                    "reason": "search provider not configured",
                }
            )
            return []

        prefetched = self._prefetched_search_results.get(query.casefold())
        if prefetched is not None:
            hits = prefetched
        else:
            try:
                hits: list[SearchHit] = self._search.search(query, max_results=RESULTS_PER_QUERY)
            except Exception as exc:
                raise InvestigationError(
                    f"Search provider crashed on query {query!r}: {type(exc).__name__}: {exc}"
                ) from exc

        evidence_ids: list[int] = []
        created_ids: list[int] = []
        reused_ids: list[int] = []
        for hit in hits:
            key = normalize_url(hit.url)
            existing = evidence_by_url.get(key) if key else None
            if existing is not None:
                reused_ids.append(existing.id)
                reused.append(existing)
            else:
                row = self._evidence.create(
                    case_id,
                    source_title=hit.title,
                    source_url=hit.url,
                    source_type="web_search",
                    published_at=hit.published_at,  # None stays None — never invented
                    excerpt=(hit.snippet or "").strip()[:SNIPPET_EXCERPT_CHARS] or None,
                    evidence_kind=EvidenceKind.INDIRECT,
                    limitations=SEARCH_LIMITATION_NOTE.format(
                        provider=self._search.provider_name
                    ),
                )
                if key:
                    evidence_by_url[key] = row
                created_ids.append(row.id)
                created.append(row)
            evidence_ids.append(existing.id if existing else created[-1].id)

        events.append(
            {
                "type": f"{prefix}search",
                "direction": direction,
                "query": query,
                "provider": self._search.provider_name,
                "results": len(hits),
                "evidence_created": created_ids,
                "evidence_reused": reused_ids,
            }
        )
        if not hits:
            events.append({"type": f"{prefix}search_empty", "direction": direction, "query": query})
        return evidence_ids

    def _ingest_documents(
        self,
        case: BusinessCase,
        events: list[dict],
        gaps: list[str],
    ) -> list[Evidence]:
        """Turn uploaded documents into durable case-level evidence (best
        effort: extraction failures become recorded gaps + failed status,
        never invented content)."""
        gathered: list[Evidence] = []
        for document in self._uploads.list_by_case(case.id):
            if document.processing_status == DocumentProcessingStatus.FAILED:
                continue
            try:
                excerpt = self._document_excerpt(document)
                self._uploads.set_status(document.id, DocumentProcessingStatus.PROCESSED)
                row = self._evidence.create(
                    case.id,
                    source_title=document.original_filename,
                    source_type="uploaded_document",
                    excerpt=excerpt,
                    evidence_kind=EvidenceKind.INDIRECT,
                    limitations=DOCUMENT_LIMITATION_NOTE,
                )
                gathered.append(row)
                events.append(
                    {
                        "type": "document",
                        "document_id": document.id,
                        "evidence_id": row.id,
                        "status": "ingested",
                    }
                )
            except Exception as exc:
                self._uploads.set_status(document.id, DocumentProcessingStatus.FAILED)
                gaps.append(
                    f"document {document.id} ({document.original_filename}) could not be "
                    f"text-extracted — marked failed, no content invented"
                )
                events.append(
                    {
                        "type": "document",
                        "document_id": document.id,
                        "status": "failed",
                        "error": type(exc).__name__,
                    }
                )
        return gathered

    def _document_excerpt(self, document: UploadedDocument) -> str | None:
        """Best-effort leading text from the stored upload. .txt/.md/.csv read
        directly; .pdf via pypdf (first 3 pages); unsupported/missing -> error
        (recorded as a gap upstream)."""
        from ..core import config as core_config

        path = core_config.uploads_dir() / document.storage_reference
        if not path.exists():
            raise FileNotFoundError(f"stored file missing: {path.name}")
        from .doctext import extract_file_text

        text = extract_file_text(str(path), max_pdf_pages=3)
        cleaned = text.strip()
        return cleaned[:DOCUMENT_EXCERPT_CHARS] if cleaned else None
