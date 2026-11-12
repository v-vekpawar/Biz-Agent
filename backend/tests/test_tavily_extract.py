from app.integrations.fetch.base import FetchFailure
from app.integrations.fetch.tavily_extract import TavilyExtractFetcher


class FakeTavily:
    def __init__(self, response):
        self.response = response

    def extract(self, **kwargs):
        return self.response


def fetcher(response):
    instance = TavilyExtractFetcher(api_key="test-only")
    instance._client = FakeTavily(response)
    return instance


def test_extract_returns_content_for_exact_requested_url():
    instance = fetcher({"results": [{"url": "https://example.com/page", "raw_content": "Requested page"}]})
    assert instance.fetch("https://example.com/page") == "Requested page"


def test_extract_refuses_content_from_a_different_url():
    instance = fetcher({"results": [{"url": "https://other.example/page", "raw_content": "Wrong page"}]})
    try:
        instance.fetch("https://example.com/page")
    except FetchFailure as exc:
        assert "refusing unrelated content" in str(exc)
    else:
        raise AssertionError("unrelated page content must never be returned")


def test_extract_matches_only_safe_url_equivalences():
    instance = fetcher({"results": [{"url": "HTTPS://EXAMPLE.COM:443/page#section", "raw_content": "Same page"}]})
    assert instance.fetch("https://example.com/page") == "Same page"


def test_extract_reports_provider_failure_for_requested_url():
    instance = fetcher({"results": [], "failed_results": [{"url": "https://example.com/page", "error": "paywall"}]})
    try:
        instance.fetch("https://example.com/page")
    except FetchFailure as exc:
        assert "paywall" in str(exc)
    else:
        raise AssertionError("failed extraction must raise")


def test_extract_rejects_empty_content():
    instance = fetcher({"results": [{"url": "https://example.com/page", "raw_content": "  "}]})
    try:
        instance.fetch("https://example.com/page")
    except FetchFailure as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("empty content must raise")
