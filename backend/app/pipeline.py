"""
run_once(): the single entry point that runs one full request through the graph, saves the reasoning-log record, and exports a PDF.
 
This is what main.py's background task calls per job. Kept as one shared
function (rather than duplicated between an API path and a CLI path) so
there's exactly one place that defines "what a full run does."
"""

import uuid
from typing import Dict, Optional

from .graph import build_graph
from .rag import ingest_document
from .reports import export_report_pdf, print_reasoning_log, save_run_record

def run_once(request: str, document_path: Optional[str] = None, run_id: Optional[str] = None) -> Dict:
    run_id = run_id or uuid.uuid4().hex[:8]
    chunk_count = 0
    if document_path:
        chunk_count = ingest_document(document_path, run_id)

    graph = build_graph()
    result = graph.invoke({
        "request": request,
        "plan": {},
        "specialist_outputs": {},
        "critic_verdicts": {},
        "retry_counts": {},
        "last_specialist": None,
        "final_report_json": {},
        "final_report": "",
        "run_id": run_id,
        "document_chunk_count": chunk_count,
        "reasoning_log": [],
    })

    retried = {n: c for n, c in result["retry_counts"].items() if c>0}
    print("\n" + "=" * 60)
    print(f"REQUEST: {request}")
    if document_path:
        print(f"DOCUMENT: {document_path} ({chunk_count} chunks ingested)")
    print("=" * 60)
    print(result["final_report"])
    print(f"[SUMMARY] Retries triggered: {retried}" if retried else "[SUMMMARY] No retries were triggered.")

    print_reasoning_log(result)
    saved_path = save_run_record(result)
    print(f"[REASONING LOG] Full structured run record saved to: {saved_path}")

    # Post-processing step, not a graph node — generating a PDF isn't an agent decision.
    export_report_pdf(result.get("final_report_json", {}), run_id)
    print()

    return result