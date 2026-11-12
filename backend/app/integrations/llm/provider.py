"""
Provider abstraction, v2 (SYSTEM_DESIGN §9): LLM clients are constructed
LAZILY at first use — fixing Phase 0 finding F-1 (v1's import-time
construction makes the app un-bootable without every provider key).

v1 clients continue to work unchanged for the v1 graph; v2 code should use
this module. Construction happens inside call paths, and missing keys raise a
descriptive error at the point of use instead of killing the process.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Protocol

from ...common import invoke_with_retry
from ... import config as v1_config

log = logging.getLogger("bizagent.llm")

# Shared across task-specific chains so a 429 in the planner also cools the
# same provider for the assessor/verifier during the same scan.
_PROVIDER_STATE_LOCK = threading.Lock()
_PROVIDER_COOLDOWNS: dict[str, float] = {}
_PROVIDER_DISABLED: dict[str, str] = {}


class ChatLLM(Protocol):
    """Minimal interface v2 services consume. Structural so tests can pass
    lightweight fakes without importing any provider SDK."""

    def invoke_text(self, prompt: str) -> str: ...

    def describe(self) -> dict[str, Any]: ...


def _provider_credential_error(message: str) -> RuntimeError:
    return RuntimeError(
        "LLM provider unavailable: " + message
        + " (set the relevant keys in backend/.env — see .env.example)"
    )


class _BaseChatLLM:
    provider_name = "unknown"

    def __init__(self, model: str, temperature: float = 0.2):
        self.model = model
        self.temperature = temperature
        self._llm = None
        self._lock = threading.Lock()

    def _build(self):
        raise NotImplementedError

    def _get(self):
        if self._llm is None:
            with self._lock:
                if self._llm is None:
                    self._llm = self._build()
        return self._llm

    def invoke_text(self, prompt: str) -> str:
        from langchain_core.messages import HumanMessage
        from ...common import extract_text

        # One short retry per provider. The fallback manager moves to the next
        # provider promptly instead of sleeping through a long retry sequence.
        response = invoke_with_retry(
            self._get(), [HumanMessage(content=prompt)],
            max_retries=1, base_delay=1.0,
        )
        return extract_text(response)

    def describe(self) -> dict[str, Any]:
        return {"provider": self.provider_name, "model": self.model}


class GeminiChatLLM(_BaseChatLLM):
    provider_name = "gemini"

    def __init__(self, temperature: float = 0.2):
        super().__init__(v1_config.GEMINI_MODEL, temperature)

    def _build(self):
        from langchain_google_genai import ChatGoogleGenerativeAI
        if not v1_config.GOOGLE_API_KEY:
            raise _provider_credential_error("GOOGLE_API_KEY is not set")
        return ChatGoogleGenerativeAI(
            model=self.model, temperature=self.temperature,
            google_api_key=v1_config.GOOGLE_API_KEY,
        )


class GroqChatLLM(_BaseChatLLM):
    provider_name = "groq"

    def __init__(self, temperature: float = 0.2):
        super().__init__(v1_config.GROQ_MODEL, temperature)

    def _build(self):
        from langchain_groq import ChatGroq
        if not v1_config.GROQ_API_KEY:
            raise _provider_credential_error("GROQ_API_KEY is not set")
        return ChatGroq(
            model=self.model, temperature=self.temperature,
            api_key=v1_config.GROQ_API_KEY,
        )


class OpenAICompatibleChatLLM(_BaseChatLLM):
    """Adapter for OpenAI-compatible free inference APIs (Cerebras/OpenRouter)."""

    def __init__(self, provider: str, *, api_key: str | None, model: str,
                 base_url: str, temperature: float = 0.2, free_only: bool = True):
        super().__init__(model, temperature)
        self.provider_name = provider
        self.api_key = api_key
        self.base_url = base_url
        self.free_only = free_only

    def _build(self):
        if not self.api_key:
            raise _provider_credential_error(f"{self.provider_name.upper()}_API_KEY is not set")
        if self.provider_name == "openrouter" and self.free_only:
            # openrouter/free is guaranteed to route only to free models.
            # Explicit :free model IDs are also allowed; paid model IDs are rejected.
            if self.model != "openrouter/free" and not self.model.endswith(":free"):
                raise RuntimeError(
                    "OpenRouter is configured in free-only mode. Set OPENROUTER_MODEL=openrouter/free "
                    "or use a model ID ending in :free. Paid models are blocked."
                )
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=45,
            max_retries=0,
        )


class FallbackChatLLM:
    """Quota-aware free-only provider chain. Tries configured providers in order.

    Provider failures are isolated; no paid provider is ever introduced by this
    manager. Output parsing remains the responsibility of the calling service.
    """

    def __init__(self, providers: list[ChatLLM], *, purpose: str):
        self.providers = providers
        self.purpose = purpose
        self._last_provider: str | None = None

    def invoke_text(self, prompt: str) -> str:
        failures: list[str] = []
        now = time.monotonic()
        for provider in self.providers:
            info = provider.describe()
            name = info.get("provider", "unknown")
            with _PROVIDER_STATE_LOCK:
                disabled_reason = _PROVIDER_DISABLED.get(name)
                cooldown_until = _PROVIDER_COOLDOWNS.get(name, 0.0)
            if disabled_reason:
                failures.append(f"{name}: disabled until restart ({disabled_reason})")
                continue
            if cooldown_until > now:
                failures.append(f"{name}: cooling down for {max(1, int(cooldown_until - now))}s")
                continue
            try:
                result = provider.invoke_text(prompt)
                self._last_provider = name
                with _PROVIDER_STATE_LOCK:
                    _PROVIDER_COOLDOWNS.pop(name, None)
                if failures:
                    log.warning(
                        "LLM fallback succeeded for %s with %s after: %s",
                        self.purpose, name, "; ".join(failures),
                    )
                return result
            except Exception as exc:  # provider-specific quota, timeout, key, model errors
                message = str(exc)
                summary = f"{name}: {type(exc).__name__}: {message[:240]}"
                failures.append(summary)
                lowered = message.lower()
                status_code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
                with _PROVIDER_STATE_LOCK:
                    if status_code in (401, 403) or any(x in lowered for x in ("invalid api key", "unauthorized", "authentication failed")):
                        _PROVIDER_DISABLED[name] = "authentication or access rejected"
                    elif status_code == 429 or any(x in lowered for x in ("429", "rate limit", "resource_exhausted", "quota exceeded")):
                        match = re.search(r"(?:retry[- ]after|try again in)[:= ]+([0-9.]+)", lowered)
                        wait = min(300.0, max(15.0, float(match.group(1)) if match else 60.0))
                        _PROVIDER_COOLDOWNS[name] = time.monotonic() + wait
                    elif status_code == 503 or any(x in lowered for x in ("timed out", "timeout", "service unavailable")):
                        _PROVIDER_COOLDOWNS[name] = time.monotonic() + 20.0
                log.warning("LLM provider failed for %s: %s", self.purpose, summary)
        configured = ", ".join(p.describe().get("provider", "?") for p in self.providers) or "none"
        raise RuntimeError(
            f"No configured free LLM provider could complete {self.purpose}. "
            f"Tried: {configured}. Details: {' | '.join(failures) or 'No provider API keys configured.'}"
        )

    def describe(self) -> dict[str, Any]:
        return {
            "provider": "fallback_chain",
            "purpose": self.purpose,
            "providers": [p.describe() for p in self.providers],
            "last_successful_provider": self._last_provider,
            "free_only": True,
        }


def _configured_chain(temperature: float, purpose: str) -> FallbackChatLLM:
    from ... import config as cfg

    available: dict[str, ChatLLM] = {
        "gemini": GeminiChatLLM(temperature=temperature),
        "groq": GroqChatLLM(temperature=temperature),
        "cerebras": OpenAICompatibleChatLLM(
            "cerebras", api_key=cfg.CEREBRAS_API_KEY,
            model=cfg.CEREBRAS_MODEL, base_url="https://api.cerebras.ai/v1",
            temperature=temperature,
        ),
        "openrouter": OpenAICompatibleChatLLM(
            "openrouter", api_key=cfg.OPENROUTER_API_KEY,
            model=cfg.OPENROUTER_MODEL, base_url="https://openrouter.ai/api/v1",
            temperature=temperature, free_only=True,
        ),
    }
    order = [
        item.strip().lower()
        for item in os.getenv("BIZAGENT_LLM_ORDER", "gemini,groq,cerebras,openrouter").split(",")
        if item.strip()
    ]
    # Only configured providers are attempted. Gemini/Groq credentials are
    # imported from the existing v1 config; optional adapters are environment-driven.
    configured = []
    keys = {
        "gemini": bool(cfg.GOOGLE_API_KEY),
        "groq": bool(cfg.GROQ_API_KEY),
        "cerebras": bool(cfg.CEREBRAS_API_KEY),
        "openrouter": bool(cfg.OPENROUTER_API_KEY) and (
            cfg.OPENROUTER_MODEL == "openrouter/free" or cfg.OPENROUTER_MODEL.endswith(":free")
        ),
    }
    for name in order:
        if name in available and keys.get(name):
            configured.append(available[name])
    return FallbackChatLLM(configured, purpose=purpose)


def get_extraction_llm() -> ChatLLM:
    return _configured_chain(0.2, "hypothesis extraction")


def get_reasoning_llm() -> ChatLLM:
    return _configured_chain(0.3, "planning and experiment design")


def get_verifier_llm() -> ChatLLM:
    return _configured_chain(0.0, "evidence verification and assessment")


def get_secondary_llm() -> ChatLLM:
    """Compatibility helper; returns the configured free-only chain."""
    return _configured_chain(0.2, "secondary inference")



def provider_status() -> dict[str, Any]:
    """Safe operational view of the configured free-only fallback chain."""
    from ... import config as cfg

    providers = [
        {"provider": "gemini", "configured": bool(cfg.GOOGLE_API_KEY), "model": cfg.GEMINI_MODEL},
        {"provider": "groq", "configured": bool(cfg.GROQ_API_KEY), "model": cfg.GROQ_MODEL},
        {"provider": "cerebras", "configured": bool(cfg.CEREBRAS_API_KEY), "model": cfg.CEREBRAS_MODEL},
        {"provider": "openrouter", "configured": bool(cfg.OPENROUTER_API_KEY), "model": cfg.OPENROUTER_MODEL,
         "free_only": cfg.OPENROUTER_MODEL == "openrouter/free" or cfg.OPENROUTER_MODEL.endswith(":free")},
    ]
    order = [
        p.strip().lower()
        for p in os.getenv("BIZAGENT_LLM_ORDER", "gemini,groq,cerebras,openrouter").split(",")
        if p.strip()
    ]
    configured = [
        p for name in order for p in providers
        if p["provider"] == name and p["configured"] and p.get("free_only", True)
    ]
    return {
        "policy": "free_only",
        "paid_fallbacks_enabled": False,
        "fallback_order": [p["provider"] for p in configured],
        "providers": providers,
        "configured_count": len(configured),
        "note": "Free-tier quotas still apply. OpenRouter is restricted to openrouter/free or :free model IDs.",
    }
