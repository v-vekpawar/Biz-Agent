"""
Reasoning-log assembly: one clean JSON record per run, plus a readable console printer.
"""

import json, os
from typing import Dict

from ..config import RUNS_DIR
from ..state import AgentState

def build_run_record(state: AgentState) -> Dict:
    return {
        "run_id": state["run_id"],
        "request": state["request"],
        "document_uploaded": state.get("document_chunk_count", 0) > 0,
        "document_chunk_count": state.get("document_chunk_count"),
        "orchestrator_plan": state.get("plan", {}),
        "steps": state.get("reasoning_log", []),
        "retry_counts": state.get("retry_counts", {}),
        "final_report": state.get("final_report_json", {}),
        "final_report_markdown": state.get("final_report", ""),
    }

def save_run_record(state: AgentState) -> str:
    os.makedirs(RUNS_DIR, exist_ok=True)
    record = build_run_record(state)
    path = os.path.join(RUNS_DIR, f"run_{state['run_id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)
    return path

def print_reasoning_log(state: AgentState) -> None:
    print("\n" + "-" * 60)
    print("REASONING LOG")
    print("-" * 60)
    for entry in state.get("reasoning_log", []):
        label = entry["role"]
        if entry.get("skipped"):
            reason = entry.get("skip_reason", "skipped")
            print(f"[{entry['step']}] {label} - SKIPPED ({reason})")
            continue
        
        print(f"[{entry['step']}] {label} ({entry['duration_seconds']}s)")
        if entry["tools_used"]:
            print(f"    tools used: {','.join(entry['tools_used'])} ({len(entry['tool_calls'])} call(s))")
        retry_info = entry.get("retry_info")
        if retry_info and retry_info.get("is_retry"):
            print(f"    retry attempt {retry_info['retry_number']} of {retry_info['max_retries']}")
        verdict =  entry.get("critic_verdict")
        if verdict:
            status = "PASS" if verdict["passed"] else "FAIL"
            print(f"    critic:{status} (confidence {verdict['confidence']:.2f}) - {verdict['reason']}")
    print("-" * 60 + "\n")
