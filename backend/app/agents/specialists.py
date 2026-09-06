"""
Specialist agent pool + tool-calling execution loop.
"""

import time
from typing import Dict, List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from ..clients import llm
from ..common import extract_text, invoke_with_retry, now_iso
from ..config import MAX_RETRIES
from ..rag import make_retrieve_tool
from ..state import AgentState
from ..tools import web_search

# name -> (role_description, uses_web_search)
SPECIALISTS: Dict[str, Tuple[str, bool]] = {
    "market_researcher": (
        "Market Researcher on a business planning team, focused on market size, trends, and competitor landscape", 
        True, 
    ),
    "financial_analyst": (
        "Financial Analyst on a business plannign team, focused on cost estimates, budget breakdown, and ROI reasoning", 
        False, 
    ),
    "risk_assessor": (
        "Risk Assessor on a business planning team, focused on identifying risks, gaps, and blind spots in the plan", 
        False, 
    ),
    "strategist": (
        "Strategist on a business planning team, focused on positioning, differentiation, and go-to-market approach", 
        False, 
    ),
    "copywriter": (
        "Copywriter on a business planning team, focused on messaging, launch copy, and marketing angles", 
        False, 
    ),
    "ops_planner": (
        "Ops Planner on a business planning team, focused on timeline, task sequencing, and resourcing", 
        False, 
    ),
}

def run_specialist_with_tools(system_prompt: str, user_content: str, tools: List, max_iterations: int =3):
    """Returns (output_text, tool_calls_log) - tool_calls_log records every tool call made (name, args, truncated result preview) for the reasoning log."""
    llm_with_tools = llm.bind_tools(tools) if tools else llm
    tool_map = {t.name: t for t in tools}
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_content)]
    tool_calls_log: List[Dict] = []

    for _ in range(max_iterations):
        response = invoke_with_retry(llm_with_tools, messages)

        if not getattr(response, "tool_calls", None):
            return extract_text(response), tools_calls_log
        
        messages.append(response)
        for call in response.tool_calls:
            tool_fn = tool_map.get(call["name"])
            result = tool_fn.invoke(call["args"]) if tool_fn else f"Unknown tool: {call['name']}"
            result_str = str(result)
            print(f"    [tool call] {call['name']}({call['args']}) -> {result_str[:120]}...")
            tool_calls_log.append({"tool": call["name"], "args": call["args"], "result_preview": result_str[:300], })
            messages.append(ToolMessage(content=result_str, tool_call_id=call["id"]))
    
    final = invoke_with_retry(llm, messages + [HumanMessage(content="Based on everything above, give your final answer now, without calling any more tools.")])
    
    return extract_text(final), tool_calls_log

def make_specialist_node(name: str, role_description: str, use_web_search: bool):
    def node(state: AgentState) -> AgentState:
        step_num = len(state["reasoning_log"]) + 1
        instruction = state["plan"].get("instruction", {}).get(name)
        
        if not instruction:
            print(f"[{name.upper()}] Skipped - not selected by orchestrator.")
            skip_entry = {
                "step": step_num,
                "node": name,
                "role": role_description,
                "skipped": True,
                "skip_reason": "No instruction found fo this list at execution time.",
                "instructions_given": None,
                "tools_used": [],
                "tool_calls": [],
                "output": None,
                "critic_verdict": None,
                "retry_info": None,
                "duration_seconds": 0.0,
                "timestamp": now_iso(),
            }
            new_log = state["reasoning_log"] + [skip_entry]
            return {**state, "last_specialist": name, "reasoning_log": new_log}
        
        retries_used = state["retry_counts"].get(name,0)
        feedback = None

        if retries_used > 0:
            prior_verdict = state["critic_verdicts"].get(name,{})
            feedback = prior_verdict.get("reason")
            print(f"[{name.upper()}] Retry {retries_used}/{MAX_RETRIES} — incorporating critic feedback.")
        
        print(f"[{name.upper()}] Running. Instruction: {instruction}")
        tools = [web_search] if use_web_search else []
        has_doc = state.get("document_chunk_count", 0) > 0
        if has_doc:
            tools = tools + [make_retrieve_tool(state["run_id"])]
        
        system_prompt = f"You are the {role_description}. Be concise, concrete, and specific to the request — no generic filler."
        if use_web_search:
            system_prompt += " Use the web_search tool for current market data, trends, competitor names, or numbers you're not certain about. Don't fabricate specific statistics."
        
        if has_doc:
            system_prompt += (
                " The user has uploaded a business document for this request. Use the"
                " retrieve_documents tool to check it for relevant company-specific context"
                " (existing numbers, pricing, prior plans, partnerships) before relying on"
                " generic assumptions."
            )
        
        user_content = f"Originial business request: {state['request']}\n\nYour specific task: {instruction}"
        instructions_given = instruction
        if feedback:
            user_content += (
            f"\n\nA reviewer flagged issues with your previous attempt: {feedback}\n"
            "Directly address this in your revised answer — don't just repeat the same content."
        )
            instructions_given = f"{instruction}\n[Retry feedback incorporated: {feedback}]"

        start = time.time()
        output, tool_calls_log = run_specialist_with_tools(system_prompt, user_content, tools)
        duration = round(time.time() - start, 2)

        outputs = dict(state["specailist_outputs"])
        outputs[name] = output

        tools_used = sorted({c["tool"] for c in tool_calls_log})
        log_entry = {
            "step": step_num,
            "node": name,
            "role": role_description,
            "skipped": False,
            "instructions_given": instructions_given,
            "tools_used": tools_used,
            "tool_calls": tool_calls_log,
            "output": output,
            "critic_verdict": None,
            "retry_info": {
                "is_retry": retries_used > 0,
                "retry_number": retries_used,
                "max_retries": MAX_RETRIES,
            },
            "duration_seconds": duration,
            "timestamp": now_iso(),
        }
        new_log = state["reasoning_log"] + [log_entry]

        return {**state, "specialist_outputs": outputs, "last_specialist": name, "reasoning_log": new_log}
        
    return node
