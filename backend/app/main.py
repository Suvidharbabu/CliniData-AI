"""CliniData AI API."""
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db, graph, vector
from .config import get_settings
from .routers import agent, approvals, public

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="CliniData AI API", version="1.0.0", docs_url="/api/docs", redoc_url=None,
              openapi_url="/api/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origins,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)

for r in (public.router, agent.router, approvals.router):
    app.include_router(r, prefix="/api/v1")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


def _check(name: str, fn) -> tuple[str, str]:
    try:
        fn()
        return name, "ok"
    except Exception as exc:
        return name, f"error: {type(exc).__name__}: {str(exc)[:200]}"


@app.get("/api/ready")
def ready() -> JSONResponse:
    checks = {
        "postgres": lambda: db.fetch_one("select 1"),
        "neo4j": lambda: graph.driver().verify_connectivity(),
        "pinecone": lambda: vector.index().describe_index_stats(),
    }
    with ThreadPoolExecutor(max_workers=len(checks)) as pool:
        results = dict(pool.map(lambda kv: _check(*kv), checks.items()))
    ok = all(v == "ok" for v in results.values())
    results["anthropic"] = "ok" if get_settings().llm_enabled else "not configured (rule-based reporter in use)"
    return JSONResponse({"ready": ok, "checks": results}, status_code=200 if ok else 503)
