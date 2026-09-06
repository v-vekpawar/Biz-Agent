"""
AgentState — the LangGraph state schema shared across every node.
"""

from typing import Dict, List, Optional, TypedDict

class AgentState(TypedDict):
    request: str
    plan: Dict
    specialist_outputs: Dict[str, str]
    critic_verdicts: Dict[str, Dict]
    retry_counts: Dict[str, int]
    last_specialist: Optional[str]
    final_report_json: Dict
    final_report: str
    run_id: str
    document_chunk_count: int
    reasoning_log: List[Dict]
