"""
ChromaDB client + embedding function + per-run retrieval tool.
 
Per-run collection isolation (run_{run_id}) is the key design decision here —
it's what prevents one user's uploaded document from leaking into another
request's retrieval results. See make_retrieve_tool()'s factory pattern
below, which binds a tool instance to one specific run's collection.
"""

import chromadb
from chromadb.utils import embedding_functions
from langchain_core.tools import tool

from .. import config

# Both the ChromaDB client and the embedding model are lazy-loaded (only
# created the first time they're actually needed) rather than at import time,
# so importing this module doesn't eagerly download the embedding model.

_chroma_client = None
_sbert_ef = None

def _get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=config.CHROMA_PATH)
    return _chroma_client

def _get_embedding_fn():
    global _sbert_ef
    if _sbert_ef is None:
        print("[RAG] Loading embedding model (all-MiniLM-L6-v2)... "
              "first run downloads it (~90MB), later runs load it from local cache.", flush=True)
        _sbert_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        print("[RAG] Embedding model ready.", flush=True)
    return _sbert_ef

def get_or_create_collection(run_id: str):
    return _get_chroma_client().get_or_create_collection(name=f"run_{run_id}", embedding_function=_get_embedding_fn())

def make_retrieve_tool(run_id: str):
    """Build a retrieve_documents tool bound to this specific run's collection."""
    collection = get_or_create_collection(run_id)

    @tool
    def retrieve_documents(query: str) -> str:
        """Retrieve relevant excerpts from the business document(s) the user
        uploaded for this request. Use this for company-specific or proprietary
        context that web search can't know about — e.g. the company's existing
        user base, internal pricing, prior plans, partnerships, or financials
        mentioned in the uploaded material. If nothing relevant comes back, say
        so rather than guessing."""

        if collection.count() == 0:
            return "No documents have been uploaded for this request."

        results = collection.query(query_texts=[query], n_results=3)
        docs = (results.get("documents") or [[]])[0]
        if not docs:
            return "No relevant excerpts found in uploaded document(s)."
        return "\n---\n".join(docs)
    
    return retrieve_documents
