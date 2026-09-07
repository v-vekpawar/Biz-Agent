"""
FastAPI wrapping for the multi-agent business-planning pipeline (Phase 8).
 
Endpoints:
  POST /submit               — request text + optional file upload, kicks
                                off the pipeline in a background task,
                                returns a job_id immediately.
  GET  /result/{job_id}      — returns the structured report + reasoning log
                                once the job has finished (poll this).
  GET  /result/{job_id}/pdf  — streams the generated PDF for that job.
  GET  /                     — trivial health check.
"""

import os, threading, traceback, uuid
from typing import Dict, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import CORS_ORIGINS, PDFS_DIR, UPLOADS_DIR
from .pipeline import run_once
from .reports import build_run_record

app = FastAPI(title="Multi-Agent Business Planning API")

app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"],)

_jobs: Dict[str, Dict] = {}
_jobs_lock = threading.Lock()

def _set_job(job_id: str, **updates) -> None:
    with _jobs_lock:
        _jobs[job_id].update(updates)

def _run_job(job_id: str, request: str, document_path: Optional[str]) -> None:
    _set_job(job_id, status="running")
    try:
        result = run_once(request, document_path=document_path, run_id=job_id)
        record = build_run_record(result)
        _set_job(job_id, status="done", record=record, error=None)
    except Exception as e:
        traceback.print_exc()
        _set_job(job_id, status="error", error=f"{type(e).__name__}: {e}")
    finally:
        if document_path and os.path.exists(document_path):
            try:
                os.remove(document_path)
            except OSError:
                pass

@app.post("/submit")
async def submit(background_tasks: BackgroundTasks, request: str = Form(...), document: Optional[UploadFile] = File(None),):
    """Accepts multipart/form-data: `request` (text) + optional `document` (PDF or text file). Returns immediately with a job_id to poll."""
    if not request or not request.strip():
        raise HTTPException(status_code=400, detail="`request` must not be empty.")
    
    job_id = uuid.uuid4().hex[:8]
    document_path = None

    if document is not None:
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        ext = os.path.splitext(document.filename or "")[1] or ".txt"
        document_path = os.path.join(UPLOADS_DIR, f"{job_id}{ext}")
        with open(document_path, "wb") as f:
            f.write(await document.read())
    
    with _jobs_lock:
        _jobs[job_id] = {"status": "pending", "record": None, "error": None}
    
    background_tasks.add_task(_run_job, job_id, request.strip(), document_path)

    return {"job_id": job_id, "status": "pending"}

@app.get("/result/{job_id}")
async def get_result(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    
    if job["status"] in ("pending","running"):
        return {"job_id": job_id, "status": job["status"]}
    
    if job["status"] == "error":
        return {"job_id": job_id, "status": "error", "error": job["error"]}
    
    return {"job_id": job_id, "status": "done", **job["record"]}

@app.get("/result/{job_id}/pdf")
async def get_result_pdf(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Job is not finished yet (status: {job['status']}).")
    
    pdf_path = os.path.join(PDFS_DIR, f"report_{job_id}.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF was not generated for this job.")
    
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"report_{job_id}.pdf")

@app.get("/")
async def health():
    return {"status": "ok", "service": "multi-agent-business-planning-api"}
