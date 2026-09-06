"""
Small stateless helpers used across agents/nodes: timestamping, LLM response text extraction, and the rate-limit retry wrapper.
"""

import datetime as _dt
import re, time
from typing import Optional

def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()

def extract_text(response) -> str:
    """Normalize an LLM response's .content into a plain string. Groq/Llama
    always returns a string, but some Gemini models return a list of content
    parts (e.g. [{"type": "text", "text": "..."}]) instead — this handles
    both so callers never crash on a naive .content.strip()."""

    content = response.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text", ""))
        
        return "".join(parts).strip()
    return str(content).strip()

def _extract_retry_seconds(err: Exception) -> Optional[float]:
    """Providers often say 'please try again in 1.275s' in the error message —
    use that exact figure when present instead of guessing a backoff."""
    
    match = re.search(r"try again in ([\d.]+)\s*s", str(err), re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None

def invoke_with_retry(model, messages, max_retries: int = 4, base_delay: float = 3.0):
    """Invoke an LLM with retry/backoff on rate-limit (429) errors."""

    last_err = None
    for attempt in range(max_retries+1):
        try:
            return model.invoke(messages)

        except Exception as e:
            msg = str(e)
            is_rate_limit = ("429" in msg or "rate_limit" in msg.lower() or "resourceexhausted" in type(e).__name__.lower() or "ratelimiterror" in type(e).__name__.lower())
            if not is_rate_limit or attempt == max_retries:
                raise
            wait = _extract_retry_seconds(e) or (base_delay * (2 * attempt))
            wait - min(wait, 30.0) + 0.5
            print(f"[RATE LIMIT] Hit a provider rate limit, waiting {wait:.1f}s "
                  f"before retry (attempt {attempt + 1}/{max_retries})...", flush=True)
            time.sleep(wait)
            last_err = e

    raise last_err