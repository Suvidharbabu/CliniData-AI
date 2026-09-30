"""The agentic gap-analysis pipeline.

Steps are named after the ECRIP agents they implement; each one is timed and
recorded in agent_runs.trace_log so the run is fully auditable and replayable.
"""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

from psycopg.types.json import Jsonb

from .. import db
from ..config import get_settings
from . import codebook, gaps as gap_rules, graph_expand, guard, llm, retrieval


class Trace:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    def record(self, agent: str, action: str, started: float, **detail) -> None:
        self.steps.append({"agent": agent, "action": action,
                           "ms": round((time.perf_counter() - started) * 1000), **detail})


def _safe_hyde(query: str) -> tuple[str, str | None]:
    if not get_settings().llm_enabled:
        return "", "skipped: no ANTHROPIC_API_KEY configured, dense search uses the raw question"
    try:
        return llm.hyde(query), None
    except Exception as exc:  # HyDE is an optimisation; fall back to the raw query
        return "", f"{type(exc).__name__}: {exc}"


def run(user_id: str, query: str) -> dict:
    row = db.fetch_one("insert into agent_runs (user_id, query_text) values (%s, %s) returning id", (user_id, query))
    run_id = str(row["id"])
    trace = Trace()
    try:
        result = _execute(run_id, user_id, query, trace)
    except Exception as exc:
        trace.steps.append({"agent": "Orchestrator", "action": "failed", "ms": 0, "error": f"{type(exc).__name__}: {exc}"})
        db.execute("update agent_runs set status = 'failed', finished_at = now(), trace_log = %s where id = %s",
                   (Jsonb(trace.steps), run_id))
        raise
    return result


def _execute(run_id: str, user_id: str, query: str, trace: Trace) -> dict:
    # 1. Orchestrator: scope the query, route codebook instructions, and write the HyDE passage in parallel.
    t = time.perf_counter()
    scope = graph_expand.extract_scope(query)
    with ThreadPoolExecutor(max_workers=2) as pool:
        instructions_f = pool.submit(codebook.route, query)
        hyde_f = pool.submit(_safe_hyde, query)
        instructions = instructions_f.result()
        hyde_text, hyde_error = hyde_f.result()
    trace.record("Orchestrator", "Planned scope and selected codebook instructions", t,
                 scope=scope, instructions=[i["id"] for i in instructions])
    trace.record("Retriever", "HyDE query expansion", t,
                 hyde=hyde_text[:600], **({"error": hyde_error} if hyde_error else {}))

    # 2. Hybrid retrieval: dense + sparse -> RRF -> rerank
    t = time.perf_counter()
    ret = retrieval.hybrid_retrieve(query, hyde_text)
    chunks = ret["chunks"]
    trace.record("Retriever", "Dense (Pinecone) + sparse (Postgres FTS) -> RRF k=60 -> rerank", t,
                 dense=len(ret["dense_ids"]), sparse=len(ret["sparse_ids"]), fused=len(ret["fused_ids"]),
                 reranked=ret["reranked"], top=[c["id"] for c in chunks])

    # 3. Graph traversal
    t = time.perf_counter()
    sub = graph_expand.expand([c["node_id"] for c in chunks if c.get("node_id")], scope)
    trace.record("Graph Traversal", "Multi-hop expansion in Neo4j", t,
                 obligations=len(sub["obligations"]), controls=len(sub["controls"]),
                 risks=len(sub["risks"]), maps_to=len(sub["maps_to"]))

    # 4-7. Deterministic specialist agents
    t = time.perf_counter()
    found = gap_rules.map_gaps(sub)
    trace.record("Gap Mapper", "Checked control coverage and evidence", t, gaps=len(found))
    t = time.perf_counter()
    constraint_gaps = gap_rules.verify_constraints(sub)
    found += constraint_gaps
    trace.record("Constraint Verifier", "Compared committed SLAs with statutory deadlines", t,
                 violations=len(constraint_gaps))
    t = time.perf_counter()
    found = gap_rules.cross_reference(sub, found)
    trace.record("Cross-Reference Agent", "Detected compound obligations across frameworks", t,
                 compound=sum(1 for g in found if g["compound_with"]))
    t = time.perf_counter()
    found = gap_rules.score_risk(sub, found)
    trace.record("Risk Scorer", "Residual risk = likelihood x impact x (1 - control effectiveness)", t)

    # 8. Regulatory Reporter (Claude)
    t = time.perf_counter()
    if get_settings().llm_enabled:
        report = llm.answer(query, llm.build_context(sub, found, chunks), instructions)
        action = "Wrote the cited analysis with Claude"
    else:
        report = llm.template_answer(query, sub, found)
        action = "Wrote the cited analysis with the rule-based reporter (Claude not configured)"
    trace.record("Regulatory Reporter", action, t,
                 model=report["model"], stop_reason=report["stop_reason"], usage=report["usage"])
    answer_text = report["text"] or (
        "The model declined to answer this request. The deterministic findings below are still valid."
    )

    # 9. Hallucination guard
    t = time.perf_counter()
    known = graph_expand.known_ids(sub) | {c["id"] for c in chunks}
    guard_report = guard.check(answer_text, known)
    trace.record("Hallucination Guard", "Validated citations against the retrieved subgraph", t,
                 passed=guard_report["passed"], unknown=guard_report["unknown_ids"])

    # 10. Human approval gate
    t = time.perf_counter()
    saved = _save_gaps(run_id, user_id, found)
    trace.record("Approval Gate", "Routed CRITICAL/HIGH gaps to human approvers", t,
                 approvals=sum(1 for g in saved if g.get("approval_id")))

    view = graph_expand.to_view(sub, found)
    result = {
        "run_id": run_id,
        "query": query,
        "answer": answer_text,
        "model": report["model"],
        "guard": guard_report,
        "gaps": saved,
        "graph": view,
        "chunks": [{"id": c["id"], "node_id": c.get("node_id"), "node_type": c.get("node_type"),
                    "framework": c.get("framework"), "text": c["text"][:400],
                    "rrf_score": round(c.get("rrf_score", 0), 4), "rerank_score": c.get("rerank_score")}
                   for c in chunks],
        "instructions": [{k: i[k] for k in ("id", "domain", "title", "text", "success_rate", "score")}
                         for i in instructions],
        "scope": scope,
        "trace": trace.steps,
    }
    db.execute(
        """
        update agent_runs set status = 'completed', finished_at = now(), trace_log = %s,
               instructions_used = %s, answer = %s, guard_report = %s, result = %s, model = %s, response_hash = %s
        where id = %s
        """,
        (Jsonb(trace.steps), Jsonb(result["instructions"]), answer_text, Jsonb(guard_report),
         Jsonb(json.loads(json.dumps(result, default=str))), report["model"],
         hashlib.sha256(answer_text.encode()).hexdigest(), run_id),
    )
    db.execute(
        "insert into audit_logs (user_id, action, entity_type, entity_id, detail) values (%s, %s, %s, %s, %s)",
        (user_id, "agent.query", "agent_run", run_id,
         Jsonb({"model": report["model"], "gaps": len(saved), "guard_passed": guard_report["passed"]})),
    )
    return result


def _save_gaps(run_id: str, user_id: str, found: list[dict]) -> list[dict]:
    saved = []
    with db.connection() as conn:
        for g in found:
            gap_id = conn.execute(
                """
                insert into gaps (user_id, run_id, obligation_id, gap_type, severity, summary, detail, risk_score)
                values (%s, %s, %s, %s, %s, %s, %s, %s) returning id
                """,
                (user_id, run_id, g["obligation_id"], g["gap_type"], g["severity"], g["summary"], g["detail"],
                 g["risk_score"]),
            ).fetchone()["id"]
            item = {**g, "gap_id": str(gap_id), "approval_id": None}
            role = gap_rules.required_role(g["severity"])
            if role:
                confidence = 0.9 if g["gap_type"] in ("NO_CONTROL", "DEADLINE_VIOLATION") else 0.8
                approval = conn.execute(
                    """
                    insert into approval_requests (user_id, gap_id, required_role, confidence)
                    values (%s, %s, %s, %s) returning id
                    """,
                    (user_id, gap_id, role, confidence),
                ).fetchone()
                item["approval_id"] = str(approval["id"])
                item["required_role"] = role
            saved.append(item)
    return saved
