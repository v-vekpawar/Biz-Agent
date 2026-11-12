"""
Biz-Agent 5.0: validate a business idea with real customers.

  /app            the web app (served from ../frontend)
  /api/v1/...     authenticated JSON API (interactive docs at /docs)
  /p/{slug}       public test page (no login)
  /d/{token}      public evidence dossier (no login, owner-controlled)
  /health         liveness probe
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import CORS_ORIGINS
from .core import config as settings

log = logging.getLogger("bizagent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.secret_key()  # fail fast in production if BIZAGENT_SECRET_KEY is missing
    from .api import deps
    from .db.migrate import upgrade_to_head
    from .repositories import ScanRepository

    import os
    if os.getenv("BIZAGENT_AUTO_MIGRATE", "1") != "0":
        upgrade_to_head()
    session = deps.session_factory()()
    try:
        interrupted = ScanRepository(session).fail_interrupted()
        if interrupted:
            log.warning("Marked %s interrupted scan job(s) as failed.", interrupted)
    finally:
        session.close()
    yield


app = FastAPI(
    title="Biz-Agent 5.0",
    description="Pre-registered customer validation for business ideas.",
    version="5.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


from .api.routes import v2_router  # noqa: E402
from .api.routes.public import router as public_router  # noqa: E402

app.include_router(v2_router)
app.include_router(public_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "biz-agent", "version": "5.0.0"}


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/app/")


_frontend = Path(settings.FRONTEND_DIR)
if _frontend.exists():
    app.mount("/app", StaticFiles(directory=str(_frontend), html=True), name="frontend")


@app.exception_handler(500)
async def server_error(_request: Request, _exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server."})
