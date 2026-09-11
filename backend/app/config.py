"""
Central configuration: environment loading and shared path/constant setup.
"""

import os
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

# --- Retry / critic tuning ---
MAX_RETRIES = 2

# --- Paths ---
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMA_PATH = os.path.join(BACKEND_DIR, "chroma_store")
RUNS_DIR = os.path.join(BACKEND_DIR, "runs")
PDFS_DIR = os.path.join(BACKEND_DIR, "pdfs")
UPLOADS_DIR = os.path.join(BACKEND_DIR, "uploads")

# --- Env Variables ---
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
TAVILIY_API_KEY = os.getenv("TAVILY_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

OPENROUTER_FALLBACK_MODELS = [
    m.strip() for m in os.getenv(
        "OPENROUTER_FALLBACK_MODELS",
        f"{OPENROUTER_MODEL},nvidia/nemotron-3.5-lightning:free,nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    ).split(",") if m.strip()
]

# --- CORS ---
# Comma-separated list of allowed frontend origins,
_DEFAULT_CORS_ORIGINS = (
    "http://localhost:8080,http://127.0.0.1:8080,"
    "http://localhost:5500,http://127.0.0.1:5500,"
    "http://localhost:3000,http://127.0.0.1:3000,"
)

CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",") if origin.strip()]
