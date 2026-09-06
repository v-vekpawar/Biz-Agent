"""
Document ingestion: file text extraction, sliding-window chunking, and storing into a run's ChromaDB collection.
"""

import os, re
from typing import List

from .store import get_or_create_collection

def extract_file_text(path: str) -> str:
    """Pull raw text out of an uploaded document. Supports .pdf and plain text(.txt, .md, etc.)."""
    if path.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("pypdf is required to read PDF uploads. Install it with: pip install pypdf") from exc
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
    """Simple sliding-window character chunking."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks

def ingest_document(path: str, run_id: str) -> int:
    """Chunk + embed + store one document into this run's ChromaDB collection. Returns the number of chunks stored (0 if the file had no usable text)."""
    text = extract_file_text(path)
    chunks = chunk_text(text)
    if not chunks:
        print(f"[RAG] No extractable text found in {path} - skipping ingestion.")
        return 0
    
    collection = get_or_create_collection(run_id)
    ids = [f"run_{run_id}-{i}" for i in range(len(chunks))]
    metadatas = [{"source": os.path.basename(path), "chunk_index": i} for i in range(len(chunks))]
    collection.add(documents=chunks, ids=ids, metadatas=metadatas)
    print(f"[RAG] Ingested {len(chunks)} chunks from '{os.path.basename(path)}' "
          f"into collection run_{run_id}.")
    return len(chunks)
