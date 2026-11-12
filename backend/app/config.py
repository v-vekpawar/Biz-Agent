"""
Central configuration: environment loading for provider keys and CORS.

Everything is read from environment variables (a `.env` file is loaded when
present). Nothing here requires a provider key at import time.
"""

import os

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

# --- Providers ---
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "llama3.1-8b")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
# The router itself only selects free models. Never change this to a paid model
# unless the user explicitly changes the product's free-only policy.
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")

# --- CORS ---
# The bundled frontend is served by the API itself (same origin), so CORS only
# matters when the frontend is hosted separately. Comma-separated origins.
_DEFAULT_CORS_ORIGINS = (
    "http://localhost:8000,http://127.0.0.1:8000,"
    "http://localhost:5500,http://127.0.0.1:5500,"
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:5173,http://127.0.0.1:5173"
)
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",") if o.strip()]
