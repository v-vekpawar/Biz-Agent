"""
Tavily web search tool, given to specialists that need current market data
"""

from langchain_core.tools import tool
from ..clients import tavily_client

@tool
def web_search(query: str) -> str:
    """Seaarch the web for current informations. Use this for market size, trends, competitor names, pricing, or any fact you're not confident about from memory alone - don't fabricate specific numbers or names."""
    results = tavily_client.search(query=query, max_results=4)
    hits = results.get("results",[])
    if not hits:
        return "No results found."
    return "\n".join(f"- {h['title']}: {h['content']} (source: {h['url']})" for h in hits)
