"""Human-in-the-loop approvals and the remediation tasks they create."""
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .. import db
from ..auth import User, current_user

router = APIRouter(tags=["approvals"])

# Which roles may decide a request that requires `required_role`
AUTHORIZED = {
    "compliance_manager": {"compliance_manager", "cco"},
    "cco": {"cco"},
}
REMEDIATION_DAYS = {"CRITICAL": 30, "HIGH": 60, "MEDIUM": 90, "LOW": 120}

TEMPLATES = {
    "DEADLINE_VIOLATION": (
        "Amend {controls} so the committed timeline meets {ref} ({deadline}). Update the SOP clock-start "
        "definition to the regulator's trigger (awareness/first knowledge), add an escalation path that can "
        "meet the shortest applicable deadline, and run a tabletop exercise to evidence it."
    ),
    "NO_CONTROL": (
        "Design and implement a control for {ref} - {title}. Assign an accountable owner, document the "
        "procedure, map it to the obligation in the control registry, and collect initial evidence."
    ),
    "CONTROL_NOT_EFFECTIVE": (
        "Bring {controls} to an implemented state for {ref}. Agree a delivery plan with the owner, track "
        "milestones weekly, and collect evidence of operation once live."
    ),
    "MISSING_EVIDENCE": (
        "Collect and verify audit evidence for {controls} ({ref}): the approved procedure, records of its "
        "operation during the review period, and reviewer sign-off. Store hashes in the evidence register."
    ),
    "PARTIAL_COVERAGE": (
        "Close the remaining coverage for {ref}: complete {controls}, confirm every in-scope asset is covered, "
        "and document any accepted residual risk."
    ),
}


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    comments: str = Field(default="", max_length=2000)


def _escalate_overdue(user_id: str) -> None:
    """Overdue requests escalate to the CCO (lazy, evaluated on read)."""
    db.execute(
        """
        update approval_requests set status = 'escalated', required_role = 'cco'
        where user_id = %s and status = 'pending' and deadline < now()
        """,
        (user_id,),
    )


@router.get("/approvals")
def list_approvals(state: str | None = None, user: User = Depends(current_user)) -> list[dict]:
    _escalate_overdue(user.id)
    return db.fetch_all(
        """
        select a.id, a.status, a.required_role, a.confidence, a.deadline, a.decision, a.comments,
               a.decided_at, a.approver_role, a.created_at,
               g.id as gap_id, g.gap_type, g.severity, g.summary, g.detail, g.risk_score, g.run_id,
               o.id as obligation_id, o.article_ref, o.title, r.framework, ar.query_text
        from approval_requests a
        join gaps g on g.id = a.gap_id
        join obligations o on o.id = g.obligation_id
        join regulations r on r.id = o.regulation_id
        join agent_runs ar on ar.id = g.run_id
        where a.user_id = %(uid)s and (%(state)s::text is null or a.status = %(state)s)
        order by (a.status in ('pending', 'escalated')) desc,
                 case g.severity when 'CRITICAL' then 0 when 'HIGH' then 1 else 2 end, a.created_at desc
        limit 100
        """,
        {"uid": user.id, "state": state},
    )


@router.patch("/approvals/{approval_id}")
def decide(approval_id: str, body: DecisionIn, user: User = Depends(current_user)) -> dict:
    row = db.fetch_one(
        """
        select a.id, a.status, a.required_role, g.id as gap_id, g.gap_type, g.severity, o.article_ref, o.title,
               o.deadline_label, r.framework,
               (select string_agg(co.control_id, ', ') from control_obligations co where co.obligation_id = o.id) as controls
        from approval_requests a
        join gaps g on g.id = a.gap_id
        join obligations o on o.id = g.obligation_id
        join regulations r on r.id = o.regulation_id
        where a.id::text = %s and a.user_id = %s
        """,
        (approval_id, user.id),
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval request not found")
    if row["status"] not in ("pending", "escalated"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Already {row['status']}; decisions are immutable")
    if user.role not in AUTHORIZED.get(row["required_role"], set()):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"This {row['severity']} gap needs a {row['required_role'].replace('_', ' ')} to decide; "
            f"you are signed in as {user.role.replace('_', ' ')}.",
        )

    task = None
    with db.connection() as conn:
        conn.execute(
            """
            update approval_requests set status = %s, decision = %s, comments = %s, approver_id = %s,
                   approver_role = %s, decided_at = now()
            where id = %s
            """,
            (body.decision, body.decision, body.comments, user.id, user.role, row["id"]),
        )
        if body.decision == "approved":
            ref = f"{row['framework']} {row['article_ref']}"
            template = TEMPLATES.get(row["gap_type"], TEMPLATES["NO_CONTROL"]).format(
                ref=ref, title=row["title"], controls=row["controls"] or "the mapped controls",
                deadline=row["deadline_label"] or "the statutory timeline",
            )
            deadline = date.today() + timedelta(days=REMEDIATION_DAYS[row["severity"]])
            task = conn.execute(
                """
                insert into remediation_tasks (user_id, gap_id, title, priority, deadline, policy_template)
                values (%s, %s, %s, %s, %s, %s) returning id, title, priority, deadline, policy_template, status
                """,
                (user.id, row["gap_id"], f"Remediate {ref}: {row['title']}", row["severity"], deadline, template),
            ).fetchone()
        conn.execute(
            "insert into audit_logs (user_id, action, entity_type, entity_id, detail) values (%s, %s, 'approval_request', %s, %s)",
            (user.id, f"approval.{body.decision}", str(row["id"]),
             Jsonb({"role": user.role, "severity": row["severity"], "comments": body.comments})),
        )
    return {"status": body.decision, "remediation_task": task}


class TaskUpdateIn(BaseModel):
    status: Literal["open", "in_progress", "complete"]


@router.get("/remediations")
def list_remediations(user: User = Depends(current_user)) -> list[dict]:
    return db.fetch_all(
        """
        select t.*, g.obligation_id, g.gap_type from remediation_tasks t join gaps g on g.id = t.gap_id
        where t.user_id = %s order by (t.status = 'complete'), t.deadline
        """,
        (user.id,),
    )


@router.patch("/remediations/{task_id}")
def update_remediation(task_id: str, body: TaskUpdateIn, user: User = Depends(current_user)) -> dict:
    row = db.fetch_one(
        """
        update remediation_tasks set status = %s,
               completed_at = case when %s = 'complete' then now() else null end
        where id::text = %s and user_id = %s returning id, status
        """,
        (body.status, body.status, task_id, user.id),
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return row
