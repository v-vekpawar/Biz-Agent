"""
Critic/Verifier node: reviews a specialist's output and returns a structured pass/fail verdict + confidence score, wired into the retry loop.
"""

import json
from typing import Dict

from langchain_core.messages import HumanMessage, SystemMessage

from ..clients import critic_llm
from ..common import extract_text, invoke_with_retry, strip_code_fence
from ..config import MAX_RETRIES
from ..state import AgentState

MIN_PASS_CONFIDENCE = 0.6

CRITIC_SYSTEM_PROMPT = """You are the Critic/Verifier for a business planning system. \
You review one specialist's output at a time against a fixed rubric. Business requests \
are open-ended, so a plausible-sounding, fluently-written, correctly-formatted answer is \
NOT the bar — that describes most LLM output, including weak output. Your job is to catch \
the difference between output that is actually grounded in THIS specific request and output \
that is generic filler dressed up to look substantive.
 
Score each dimension 0.0-1.0, thinking silently, then decide:
 
1. INSTRUCTION COVERAGE: Does it address every part of the specific instruction it was
   given, not just the general topic? Partial coverage of a multi-part instruction fails
   this dimension even if what IS covered is well-written.
2. SPECIFICITY TEST (most important — this is where leniency usually goes wrong):
   Could this exact paragraph be pasted into a completely different business plan (different
   industry, different product) with only the company name swapped, and still read as fully
   applicable? If yes, that is generic filler and this dimension scores near 0.0, regardless
   of how confident, fluent, or well-organized the prose is. A real pass requires details
   specific to THIS request: named competitors/tools, concrete numbers, dates, or facts that
   would need to be rewritten for a different business.
3. GROUNDING: Are specific numbers, statistics, market sizes, or named entities backed by
   something (a cited search result, a document reference, explicit reasoning shown), or
   stated with confidence and no support? Ungrounded specifics score low here — note this is
   a DIFFERENT failure from dimension 2's genericness; an output can be specific-sounding
   (has numbers) yet still ungrounded (numbers are invented).
4. INTERNAL CONSISTENCY: Any contradictions within the output, or with the original request?
 
Do not let fluency, length, confident tone, or correct formatting raise these scores — those
are surface properties and are exactly what generic filler optimizes for. A short, plainly-
written answer with two specific, well-grounded details beats a long, polished answer with
none, and should score higher.
 
Calibration:
- WEAK example (should fail): "The market for this product shows strong growth potential
  with increasing consumer demand. Key competitors are actively investing in this space, and
  a well-positioned entrant could capture meaningful market share by focusing on quality and
  customer experience." — This has zero details specific to the actual request. Fails
  dimension 2 outright regardless of tone.
- STRONG example (should pass): "The reusable water bottle market in the US was valued at
  ~$9B in 2023 per [source], growing ~4% annually. Hydro Flask and Yeti dominate the premium
  segment; Owala has taken share recently via TikTok-driven virality rather than retail
  presence — suggesting a social-first launch channel could work for a new entrant here." —
  Specific, named, grounded, and could not be pasted into an unrelated plan unchanged.
 
passed = true only if ALL FOUR dimensions score at least 0.6. If any one dimension is weak,
fail the whole output even if the others are strong — do not average across dimensions to
compensate for one bad one.
 
confidence = your assessment of how strong THIS SPECIFIC output is, using the same 0.0-1.0
dimension scores above (roughly, the score of the weakest dimension). This is NOT your
confidence in your own verdict — it is a quality signal about the content you just reviewed.
A generic-filler output should score confidence well below 0.5, even if you are personally
certain that's the correct call.
 
Respond with ONLY valid JSON, no markdown code fences, no preamble, in exactly this shape:
 
{
  "passed": true,
  "confidence": 0.8,
  "reason": "one or two sentence explanation naming which dimension(s) drove the verdict, specific enough to guide a rewrite if failed"
}"""

def run_critic(name: str, instruction: str, output: str) -> Dict:
    user_content = (
        f"Specialist role: {name}\n"
        f"Instruction given to the specialist: {instruction}\n\n"
        f"Specialist's output to review:\n{output}"
    )
    response = invoke_with_retry(critic_llm, [SystemMessage(content=CRITIC_SYSTEM_PROMPT), HumanMessage(content=user_content)],)
    raw = strip_code_fence(extract_text(response))

    try:
        verdict = json.loads(raw)
        verdict["passed"] = bool(verdict.get("passed", False))
        verdict["confidence"] = float(verdict.get("confidence", 0.5))
        verdict["reason"] = str(verdict.get("reason","")).strip() or "No reason given."
    except (json.JSONDecodeError, ValueError, TypeError):
        print(f"[CRITIC] Could not parse verdict JSON for {name}, defaulting to pass (fail-open).\nRaw response was:\n{raw}\n")
        verdict = {"passed": True, "confidence": 0.0, "reason": "Critic response unparseable — defaulted to pass."}
    
    if verdict["passed"] and verdict["confidence"] < MIN_PASS_CONFIDENCE:
        verdict["passed"] = False
        verdict["reason"] = (
            f"{verdict['reason']} [Overridden to FAIL: confidence {verdict['confidence']:.2f} "
            f"is below the {MIN_PASS_CONFIDENCE} pass threshold."
        )

    return verdict

def critic_node(state:AgentState) -> AgentState:
    name = state.get("last_specialist")
    
    if name is None or name not in state["specialist_outputs"]:
        return state
    
    instruction = state["plan"].get("instructions", {}).get(name, state["request"])
    output = state["specialist_outputs"][name]
    retries_used = state["retry_counts"].get(name,0)

    verdict = run_critic(name, instruction, output)
    will_retry = (not verdict["passed"] and (retries_used < MAX_RETRIES))
    verdict["will_retry"] = will_retry

    new_retry_counts = dict(state["retry_counts"])
    if will_retry:
        new_retry_counts[name] = retries_used + 1
    
    new_verdicts = dict(state["critic_verdicts"])
    new_verdicts[name] = verdict

    status = "PASS" if verdict["passed"] else "FAIL"
    print(f"[CRITIC] {name}: {status} (confidence {verdict['confidence']:.2f}) - {verdict['reason']}")
    if will_retry:
        print(f"[CRITIC] -> retrying {name} (attempt {new_retry_counts[name] + 1} of {MAX_RETRIES + 1})")
    elif not verdict["passed"]:
        print(f"[CRITIC] -> {name} still failing after {retries_used} retries, moving on with last output.")
    
    # Attach the verdict to the most recent unreviewed log entry for this
    # specialist (walking backward). This correctly handles retries: each
    # retry writes its own specialist entry, and each gets its own verdict
    # attached here rather than overwriting the previous one.
    new_log = list(state["reasoning_log"])
    for i in range(len(new_log) - 1, -1, -1):
        entry = new_log[i]
        if entry["node"] == name and not entry.get("skipped") and entry.get("critic_verdict") is None:
            update_entry = dict(entry)
            update_entry["critic_verdict"] = {
                "passed": verdict["passed"],
                "confidence": verdict["confidence"],
                "reason": verdict["reason"],
                "will_retry": verdict["will_retry"],
            }
            new_log[i] = update_entry
            break
    
    return {
        **state,
        "critic_verdicts": new_verdicts,
        "retry_counts": new_retry_counts,
        "reasoning_log": new_log,
    }
