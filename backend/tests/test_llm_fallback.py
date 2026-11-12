from __future__ import annotations

import pytest

from app.integrations.llm.provider import FallbackChatLLM, OpenAICompatibleChatLLM


class StubProvider:
    def __init__(self, name, result=None, error=None):
        self.name = name
        self.result = result
        self.error = error
        self.calls = 0

    def describe(self):
        return {"provider": self.name, "model": "stub"}

    def invoke_text(self, prompt):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_fallback_uses_next_provider_after_primary_failure():
    first = StubProvider("gemini", error=RuntimeError("429 rate limit"))
    second = StubProvider("groq", result='{"ok": true}')
    chain = FallbackChatLLM([first, second], purpose="test")
    assert chain.invoke_text("hello") == '{"ok": true}'
    assert first.calls == 1
    assert second.calls == 1
    assert chain.describe()["last_successful_provider"] == "groq"


def test_fallback_fails_clearly_when_every_provider_is_unavailable():
    first = StubProvider("gemini", error=RuntimeError("unavailable"))
    second = StubProvider("groq", error=RuntimeError("quota"))
    chain = FallbackChatLLM([first, second], purpose="test")
    with pytest.raises(RuntimeError, match="No configured free LLM provider"):
        chain.invoke_text("hello")


def test_openrouter_rejects_paid_model_in_free_only_mode(monkeypatch):
    adapter = OpenAICompatibleChatLLM(
        "openrouter", api_key="test-key", model="provider/model",
        base_url="https://openrouter.ai/api/v1", free_only=True,
    )
    with pytest.raises(RuntimeError, match="free-only mode"):
        adapter._build()


def test_openrouter_free_router_is_allowed(monkeypatch):
    # The model guard is checked before importing the optional client.
    adapter = OpenAICompatibleChatLLM(
        "openrouter", api_key="test-key", model="openrouter/free",
        base_url="https://openrouter.ai/api/v1", free_only=True,
    )
    assert adapter.model == "openrouter/free"



def test_provider_status_marks_openrouter_free_only(monkeypatch):
    from app import config as cfg
    from app.integrations.llm.provider import provider_status

    monkeypatch.setattr(cfg, "GOOGLE_API_KEY", "gemini-key")
    monkeypatch.setattr(cfg, "GROQ_API_KEY", None)
    monkeypatch.setattr(cfg, "CEREBRAS_API_KEY", None)
    monkeypatch.setattr(cfg, "OPENROUTER_API_KEY", "router-key")
    monkeypatch.setattr(cfg, "OPENROUTER_MODEL", "openrouter/free")
    monkeypatch.setenv("BIZAGENT_LLM_ORDER", "gemini,openrouter")
    status = provider_status()
    assert status["policy"] == "free_only"
    assert status["paid_fallbacks_enabled"] is False
    assert status["fallback_order"] == ["gemini", "openrouter"]
