"""
LLM + external API client instantiation. One place to change models/providers without hunting through agent modules.
"""

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from tavily import TavilyClient

from .import config

llm = ChatOpenAI(
    model=config.OPENROUTER_MODEL,
    temperature=0.3,
    api_key=config.OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)

groq_fallback_llm = ChatGroq(model=config.GROQ_MODEL, temperature=0.3, api_key=config.GROQ_API_KEY)

critic_llm = ChatGoogleGenerativeAI(model=config.GEMINI_MODEL, temperature=0.0, google_api_key=config.GOOGLE_API_KEY)

synthesizer_llm = ChatGoogleGenerativeAI(model=config.GEMINI_MODEL, temperature=0.4, google_api_key=config.GOOGLE_API_KEY)

tavily_client = TavilyClient(api_key=config.TAVILIY_API_KEY)