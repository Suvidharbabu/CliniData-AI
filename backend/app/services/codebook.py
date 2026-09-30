"""Adaptive instruction codebook: semantic routing + EMA success tracking."""
from .. import db, vector

TOP_N = 5
CANDIDATES = 8
EMA_ALPHA = 0.2
REVIEW_THRESHOLD = 0.4


def ema(current: float, outcome: float, alpha: float = EMA_ALPHA) -> float:
    """Exponential moving average: new = (1 - alpha) * current + alpha * outcome."""
    return round((1 - alpha) * current + alpha * outcome, 3)


def blend(similarity: float, success_rate: float) -> float:
    """Routing score: semantic fit, nudged by how well the instruction has performed."""
    return similarity * (0.7 + 0.3 * success_rate)


def route(query: str) -> list[dict]:
    hits = vector.search(vector.CODEBOOK_NS, query, CANDIDATES, fields=["domain", "title"])
    if not hits:
        return []
    rows = db.fetch_all(
        "select id, domain, title, text, success_rate, version from instructions where active and id = any(%s)",
        ([h["id"] for h in hits],),
    )
    by_id = {r["id"]: r for r in rows}
    ranked = []
    for h in hits:
        row = by_id.get(h["id"])
        if row:
            sr = float(row["success_rate"])
            ranked.append({**row, "success_rate": sr, "similarity": round(h["score"], 4),
                           "score": round(blend(h["score"], sr), 4)})
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked[:TOP_N]


def apply_feedback(run_id: str, user_id: str, helpful: bool) -> list[dict]:
    """Update each instruction used in the run. One vote per user per run."""
    run = db.fetch_one("select instructions_used from agent_runs where id = %s and user_id = %s", (run_id, user_id))
    if run is None:
        raise LookupError("run not found")
    inserted = db.fetch_one(
        """
        insert into instruction_feedback (run_id, user_id, helpful) values (%s, %s, %s)
        on conflict (run_id, user_id) do nothing returning id
        """,
        (run_id, user_id, helpful),
    )
    if inserted is None:
        raise ValueError("feedback already recorded for this run")

    ids = [i["id"] for i in run["instructions_used"]]
    updated = []
    with db.connection() as conn:
        for row in conn.execute("select id, success_rate from instructions where id = any(%s)", (ids,)).fetchall():
            new_rate = ema(float(row["success_rate"]), 1.0 if helpful else 0.0)
            conn.execute("update instructions set success_rate = %s where id = %s", (new_rate, row["id"]))
            updated.append({"id": row["id"], "old": float(row["success_rate"]), "new": new_rate,
                            "needs_review": new_rate < REVIEW_THRESHOLD})
    return updated
