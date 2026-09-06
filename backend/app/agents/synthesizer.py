"""
Synthesizer node: combines verified specialist outputs into one structured report (title, executive_summary, sections, checklist), plus a Markdown render of that same structure for text/console display.
"""

import json, time
from typing import Dict

from langchain_core.messages import HumanMessage, SystemMessage

from ..clients import synthesizer_llm
from ..common import extract_text, invoke_with_retry, now_iso, strip_code_fence
from ..state import AgentState

SYNTHESIZER_SYSTEM_PROMPT = """You are the Synthesizer for a business planning system. You \
receive the outputs of several specialist agents (Market Researcher, Financial Analyst, \
Risk Assessor, Strategist, Copywriter, Ops Planner — only some may have run, depending on \
the request) and combine them into ONE coherent report.
 
Rules:
- Do not just concatenate the specialists' text. Synthesize: resolve overlaps, connect
  related points across specialists (e.g. tie a risk back to the strategy that creates it),
  and write in one consistent voice.
- If a specialist's output is marked "still failing after retries" below, you may use it,
  but hedge appropriately (e.g. "early estimate," "needs validation") rather than presenting
  it with full confidence.
- The checklist must be concrete and actionable — each item something a person could put on
  a to-do list, not a restatement of a goal.
- Keep section content substantive but not padded — real content, no filler.
 
Respond with ONLY valid JSON, no markdown code fences, no preamble, in exactly this shape:
 
{
  "title": "short report title specific to this request",
  "executive_summary": "2-4 sentence high-level summary of the whole plan",
  "sections": [
    {"heading": "Market Overview", "specialist": "market_researcher", "content": "..."}
  ],
  "checklist": ["concrete actionable next step", "another concrete next step"]
}
 
Only include a section for a specialist that actually ran. Order sections sensibly (e.g.
market/financial/risk context before strategy, strategy before copy/ops execution details)."""

def run_synthesizer(state: AgentState) -> Dict:
    parts = []
    for name in state["plan"].get(specialists, []):
        output = state["specialist_outputs"].get(name)
        if output is None:
            continue
        verdict = state["critic_verdicts"].get(name, {})
        status = "passed critic review" if verdict.get("passed") else "still failing after retries - use with hedged language"
        parts.append(f"### {name} ({status})\n{output}")

    if not parts:
        return {
            "title": "No Report Generated",
            "executive_summary": "No specialists were invoked for this request."
            "sections": [],
            "checklist": [],
        }
    
    user_content = f"Original business request: {state['request']}\n\n" + "\n\n".join(parts)
    response = invoke_with_retry(synthesizer_llm, [SystemMessage(content=SYNTHESIZER_SYSTEM_PROMPT), HumanMessage(content=user_content)],)
    raw = strip_code_fence(extract_text(response))

    try:
        report = json.loads(raw)
        report.setdefault("title","Business Plan Report")
        report.setdefault("executive_summary","")
        report.setdefault("sections","")
        report.setdefault("checklist",[])
    except json.JSONDecodeError:
        print(f"[SYNTHESIZER] Could not parse report JSON, falling back to raw concatenation.\nRaw response was:\n{raw}\n")
        report = {
            "title": "Business Plan Report (fallback format)",
            "executive_summary": "The synthesizer's structured output could not be parsed; showing raw specialist outputs instead.",
            "sections": [
                {"heading": name.replace("_", " ").title(), "specialist": name, "content": state["specialist_outputs"][name]}
                for name in state["plan"].get("specialists", [])
                if name in state["specialist_outputs"]
            ],
            "checklist": [],
        }
    
    return report

def render_markdown_report(report: Dict) -> str:
    lines = [f"# {report.get('title', 'Business Plan Report')}", ""]
    
    summary = report.get("executive_summary")
    if summary:
        lines += ["## Executive Summary", "", summary, ""]
    
    for section in report.get("sections", []):
        heading = section.get("heading") or section.get("specialist", "Section").replace("-", " ").title()
        lines += [f"## {heading}", "", section.get("content", ""), ""]
    
    checklist = report.get("checklist", [])
    if checklist:
        lines += ["## Checklist / Next Steps", ""]
        lines += [f"- [ ] {item}" for item in checklist]
        lines += [""]
    
    return "\n".join(lines)

def synthesizer_node(state: AgentState) -> AgentState:
    print("[SYNTHESIZER] Combining specialist out[uts into final report...]")
    start = time.time()
    report = run_synthesizer(state)
    duration = round(time.time() - start, 2)
    markdown = render_markdown_report(report)

    ran_specialists = [n for n in state["plan"].get("specialists", []) if n in state["specialist_outputs"]]
    log_entry = {
        "step": len(state["reasoning_log"] + 1),
        "node": "synthesizer",
        "role": "Synthesizer",
        "skipped": False,
        "instruction_given": f"Combine verified outputs from: {ran_Specialists}",
        "tools_used": [],
        "tool_calls": [],
        "output": report,
        "critic_verdict": None,
        "retry_info": None,
        "duration_seconds": duration,
        "timestamp": now_iso(),
    }
    new_log = state["reasoning_log"] + [log_entry]

    return {**state, "final_report_json": report, "final_report": markdown, "reasoning_log": new_log,}
