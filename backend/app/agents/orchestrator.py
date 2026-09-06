"""
Orchestrator node: decomposes the request and decides which specialists to invoke, in what order, with what sub-instructions. This routing decision is the core "agentic" behavior the project showcases.
"""

import json
import time

from langchain_core.messages import HumanMessage, SystemMessage

from ..clients import llm
from ..common import extract_text, invoke_with_retry, now_iso, strip_code_fence
from .specialists import SPECIALISTS

ORCHESTRATOR_SYSTEM_PROMPT = """You are the orchestrator for a business planning system.
 
Available specialists:
- market_researcher: market size, trends, competitor landscape (has live web search)
- financial_analyst: cost estimates, budget breakdown, ROI reasoning
- risk_assessor: identifies risks, gaps, and blind spots in the plan
- strategist: positioning, differentiation, go-to-market approach
- copywriter: messaging, launch copy, marketing angles
- ops_planner: timeline, task sequencing, resourcing
 
Given the user's request, decide:
1. Which specialists are relevant — do NOT default to invoking all six.
   A narrow request (e.g. "just analyze the market") might only need one
   or two. Only pick the ones that would meaningfully contribute.
2. What order to run them in (e.g. market research before strategy often
   makes sense, since strategy can then reference it)
3. A specific sub-instruction for each chosen specialist, tailored to this
   exact request — not a generic restatement of their role
 
Respond with ONLY valid JSON, no markdown code fences, no preamble or
explanation outside the JSON, in exactly this shape:
 
{
  "specialists": ["market_researcher", "strategist"],
  "instructions": {
    "market_researcher": "specific instruction here",
    "strategist": "specific instruction here"
  }
}
 
Only include keys in "instructions" for specialists you actually chose to
invoke, and list them in "specialists" in the order they should run."""

def orchestrator_node(state: AgentState) -> AgentState:
    start = time.time()
    response = invoke_with_retry(llm, [SystemMessage(content=ORCHESTRATOR_SYSTEM_PROMPT), HumanMessage(content=f"User request: {state['request']}"), ], )
    raw = strip_code_fence(extract_text(response))

    try:
        plan = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[ORCHESTRATOR] Could not parse plan JSON, failing back to running all specialists.\nRaw response was:\n{raw}\n")
        plan = {
            "specialists": list(SPECIALISTS.keys()),
            "instructions": {s: state["request"] for s in SPECIALISTS},
        }
    
    print(f"\n[ORCHESTRATOR] Plan:\n{json.dumps(plan, indent=2)}\n")

    orchestrator_entry = {
        "step": 1,
        "node": "orchestrator",
        "role": "Orchestrator",
        "skipped": False,
        "instructions_given": f"User request: {state['request']}",
        "tools_used": [],
        "tool_calls": [],
        "output": plan,
        "critic_verdict": None,
        "retry_info": None,
        "duration_seconds": round(time.time() - start, 2),
        "timestamp": now_iso(),
    }
    new_log = [orchestrator_entry]

    selected = set(plan.get("specialists", []))
    for name, (role, _use_search) in SPECIALISTS.items():
        if name not in selected:
            new_log.append({
                "step": len(new_log) + 1,
                "node": name,
                "role": role,
                "skipped": True,
                "skip_reason": "Not selected by orchestrator for this request.",
                "instructions_given": None,
                "tools_used": [],
                "tool_calls": [],
                "output": None,
                "critic_verdict": None,
                "retry_info": None,
                "duration_seconds": 0.0,
                "timestamp": now_iso(),
            })
    
    return {
        **state,
        "plan":plan,
        "specialist_outputs": {},
        "critic_verdicts": {},
        "retry_counts": {},
        "last_specialist": None,
        "reasoning_log": new_log,
    }