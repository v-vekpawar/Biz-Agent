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