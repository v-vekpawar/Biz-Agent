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

CRITIC_SYSTEM_PROMPT = """You are the Critic/Verifier for a business planning system. \
You review one specialist's output at a time and check for:
- Gaps: does it actually address the instruction it was given?
- Contradictions: internal inconsistencies, or conflicts with the original request?
- Unsupported claims: specific numbers, stats, or names stated with unwarranted confidence
  and no grounding (this matters most for web-search-backed specialists)
- Generic filler: vague, non-actionable content that could apply to any business
 
Be a reasonably strict but fair reviewer — the goal is to catch real problems worth a
retry, not to nitpick style. A short but specific, well-grounded answer should pass.
 
Respond with ONLY valid JSON, no markdown code fences, no preamble, in exactly this shape:
 
{
  "passed": true,
  "confidence": 0.8,
  "reason": "one or two sentence explanation, specific enough to guide a rewrite if failed"
}
 
confidence is your own confidence in this verdict, from 0.0 to 1.0."""

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
    
    return verdict

def critic_node(state:AgentState) -> AgentState:
    name = state.get("last_specialist")
    
    if name is None or name not in state["specialist_outputs"]:
        return state
    
    instruction = state["plan"].get("instruction", {}).get(name, state["request"])
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
