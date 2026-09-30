"""Pinecone access: one integrated-embedding index, two namespaces.

Records are embedded server-side from their `chunk_text` field, so the app
never handles raw vectors.
"""
from functools import lru_cache

from pinecone import Pinecone

from .config import get_settings

DOCS_NS = "docs"
CODEBOOK_NS = "codebook"
EMBED_MODEL = "llama-text-embed-v2"
TEXT_FIELD = "chunk_text"


@lru_cache
def client() -> Pinecone:
    return Pinecone(api_key=get_settings().pinecone_api_key)


@lru_cache
def index():
    return client().index(name=get_settings().pinecone_index)


def search(namespace: str, text: str, top_k: int, fields: list[str]) -> list[dict]:
    """Dense semantic search. Returns [{id, score, **fields}] best first."""
    response = index().search(namespace=namespace, top_k=top_k, inputs={"text": text}, fields=fields)
    return [{"id": hit.id, "score": float(hit.score), **(hit.fields or {})} for hit in response.result.hits]


def rerank(query: str, docs: list[dict], top_n: int) -> list[dict]:
    """Cross-encoder rerank of [{id, text, ...}] with Pinecone's hosted reranker."""
    if not docs:
        return []
    result = client().inference.rerank(
        model=get_settings().pinecone_rerank_model,
        query=query,
        documents=[{"id": d["id"], "text": d["text"]} for d in docs],
        top_n=min(top_n, len(docs)),
        return_documents=False,
    )
    return [{**docs[item.index], "rerank_score": float(item.score)} for item in result.data]
