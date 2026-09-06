"""
Phase 0 checkpoint app.

This is deliberately tiny: one endpoint, CORS turned on, nothing else.
Once you can load frontend/index.html in a browser and see a live
response from this server, Phase 0 is done — don't add anything else
here yet. Phase 1 (the actual LangGraph pipeline) happens in a
separate script/notebook first, per build-order.md.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Business Planning Agent System — Phase 0")

# Wide open for local dev. Tighten this to your actual deployed
# frontend origin (e.g. https://your-app.vercel.app) before Phase 10.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "message": "Backend is alive."}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from FastAPI — your Phase 0 checkpoint works."}
