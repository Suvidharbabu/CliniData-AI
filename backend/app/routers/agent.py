"""Authenticated demo endpoints: agent queries, run history, codebook feedback, profile."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .. import db
from ..auth import ROLES, User, current_user
from ..config import get_settings
from ..services import codebook, pipeline

log = logging.getLogger(__name__)
router = APIRouter(tags=["agent"])


class QueryIn(BaseModel):
    query: str = Field(min_length=5, max_length=500)


class FeedbackIn(BaseModel):
    run_id: str
    helpful: bool


class ProfileIn(BaseModel):
    role: str


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    used = db.fetch_one(
        "select count(*) as n from agent_runs where user_id = %s and started_at > now() - interval '24 hours'",
        (user.id,),
    )["n"]
    return {"id": user.id, "email": user.email, "role": user.role, "roles": ROLES,
            "queries_used": used, "query_limit": get_settings().daily_query_limit}


@router.patch("/me")
def update_me(body: ProfileIn, user: User = Depends(current_user)) -> dict:
    """Demo only: let a visitor switch role to try the approval workflow."""
    if body.role not in ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"role must be one of {', '.join(ROLES)}")
    db.execute("update profiles set role = %s where id = %s", (body.role, user.id))
    db.execute(
        "insert into audit_logs (user_id, action, entity_type, entity_id, detail) values (%s, 'profile.role', 'profile', %s, %s)",
        (user.id, user.id, Jsonb({"from": user.role, "to": body.role})),
    )
    return {"role": body.role}


@router.post("/agent/query")
def agent_query(body: QueryIn, user: User = Depends(current_user)) -> dict:
    limit = get_settings().daily_query_limit
    used = db.fetch_one(
        "select count(*) as n from agent_runs where user_id = %s and started_at > now() - interval '24 hours'",
        (user.id,),
    )["n"]
    if used >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Daily demo limit of {limit} queries reached.")
    try:
        return pipeline.run(user.id, body.query.strip())
    except Exception as exc:
        log.exception("agent run failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"The analysis pipeline failed: {type(exc).__name__}") from exc


@router.get("/agent/runs")
def list_runs(user: User = Depends(current_user)) -> list[dict]:
    return db.fetch_all(
        """
        select id, query_text, status, started_at, finished_at, model,
               (guard_report->>'passed')::boolean as guard_passed
        from agent_runs where user_id = %s order by started_at desc limit 20
        """,
        (user.id,),
    )


@router.get("/agent/runs/{run_id}")
def get_run(run_id: str, user: User = Depends(current_user)) -> dict:
    row = db.fetch_one(
        "select id, status, result, trace_log from agent_runs where id::text = %s and user_id = %s",
        (run_id, user.id),
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return row["result"] or {"run_id": str(row["id"]), "status": row["status"], "trace": row["trace_log"]}


@router.post("/codebook/feedback")
def feedback(body: FeedbackIn, user: User = Depends(current_user)) -> dict:
    try:
        updated = codebook.apply_feedback(body.run_id, user.id, body.helpful)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return {"updated": updated}
