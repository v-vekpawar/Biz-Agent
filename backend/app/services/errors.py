"""Turn low-level provider/network exceptions into messages a user can act on."""

from __future__ import annotations

_PROVIDER_MODULES = ("httpx", "httpcore", "groq", "google", "openai", "anthropic", "requests", "urllib3",
                     "tenacity", "langchain", "grpc", "ssl", "socket")

PROVIDER_MESSAGE = (
    "The AI provider couldn't be reached or rejected the request. Check the API keys, the account's quota "
    "and the server's network access, then try again."
)


def looks_like_provider_error(exc: BaseException) -> bool:
    module = type(exc).__module__ or ""
    return isinstance(exc, (ConnectionError, TimeoutError)) or module.startswith(_PROVIDER_MODULES)
