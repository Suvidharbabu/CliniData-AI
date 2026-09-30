"""Hybrid retrieval: HyDE-expanded dense search (Pinecone) + keyword search
(Postgres full-text), fused with Reciprocal Rank Fusion, then reranked."""
from concurrent.futures import ThreadPoolExecutor

from .. import db, vector

RRF_K = 60
CANDIDATES = 20
FINAL_TOP = 10


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: score(d) = sum over lists of 1 / (k + rank)."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def dense_search(text: str, top_k: int = CANDIDATES) -> list[dict]:
    hits = vector.search(vector.DOCS_NS, text, top_k,
                         fields=[vector.TEXT_FIELD, "node_id", "node_type", "framework"])
    return [
        {"id": h["id"], "text": h.get(vector.TEXT_FIELD, ""), "node_id": h.get("node_id"),
         "node_type": h.get("node_type"), "framework": h.get("framework"), "score": h["score"]}
        for h in hits
    ]


def sparse_search(query: str, top_k: int = CANDIDATES) -> list[dict]:
    # plainto_tsquery ANDs every term; OR them instead so natural-language
    # questions still match, and let ts_rank_cd reward chunks that hit more terms.
    rows = db.fetch_all(
        """
        select c.id, c.text, c.source_node_id as node_id, c.node_type, c.framework,
               ts_rank_cd(c.tsv, s.q) as score
        from doc_chunks c,
             (select nullif(replace(plainto_tsquery('english', %s)::text, '&', '|'), '')::tsquery as q) s
        where c.tsv @@ s.q
        order by score desc
        limit %s
        """,
        (query, top_k),
    )
    return [{**r, "score": float(r["score"])} for r in rows]


def hybrid_retrieve(query: str, hyde_text: str) -> dict:
    """Returns the final chunks plus per-stage details for the trace."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        dense_f = pool.submit(dense_search, hyde_text or query)
        sparse_f = pool.submit(sparse_search, query)
        dense, sparse = dense_f.result(), sparse_f.result()

    by_id = {d["id"]: d for d in sparse}
    by_id.update({d["id"]: d for d in dense})
    fused = rrf([[d["id"] for d in dense], [d["id"] for d in sparse]])[:CANDIDATES]
    candidates = [{**by_id[doc_id], "rrf_score": score} for doc_id, score in fused]

    try:
        final = vector.rerank(query, candidates, FINAL_TOP)
        reranked = True
    except Exception:  # reranker unavailable -> fall back to RRF order
        final, reranked = candidates[:FINAL_TOP], False

    return {
        "chunks": final,
        "dense_ids": [d["id"] for d in dense],
        "sparse_ids": [d["id"] for d in sparse],
        "fused_ids": [c["id"] for c in candidates],
        "reranked": reranked,
    }
