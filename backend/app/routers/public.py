"""Unauthenticated endpoints: contact form and the read-only demo catalogue."""
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from .. import db

router = APIRouter(tags=["public"])

CONTACT_LIMIT_PER_HOUR = 5


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    organization: str = Field(default="", max_length=160)
    role: str = Field(default="", max_length=120)
    message: str = Field(default="", max_length=4000)
    website: str = Field(default="", max_length=200)  # honeypot: humans never fill this in


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "")


@router.post("/public/contact", status_code=status.HTTP_201_CREATED)
def contact(body: ContactIn, request: Request) -> dict:
    if body.website:
        return {"ok": True}  # silently drop bots
    ip = client_ip(request)
    recent = db.fetch_one(
        "select count(*) as n from contact_requests where ip_addr = %s and created_at > now() - interval '1 hour'",
        (ip,),
    )
    if recent["n"] >= CONTACT_LIMIT_PER_HOUR:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests - please try again later.")
    db.execute(
        "insert into contact_requests (name, email, organization, role, message, ip_addr) values (%s, %s, %s, %s, %s, %s)",
        (body.name, body.email, body.organization, body.role, body.message, ip),
    )
    return {"ok": True}


@router.get("/catalog/summary")
def catalog_summary() -> dict:
    counts = db.fetch_one(
        """
        select (select count(*) from regulations) as regulations,
               (select count(*) from obligations) as obligations,
               (select count(*) from controls) as controls,
               (select count(*) from risks) as risks,
               (select count(*) from assets) as assets,
               (select count(*) from evidence) as evidence,
               (select count(*) from obligation_mappings) as mappings,
               (select count(*) from instructions where active) as instructions
        """
    )
    frameworks = db.fetch_all(
        """
        select r.framework, count(o.id) as obligations
        from regulations r left join obligations o on o.regulation_id = r.id
        group by r.framework order by r.framework
        """
    )
    return {"counts": counts, "frameworks": frameworks}


@router.get("/catalog/regulations")
def regulations() -> list[dict]:
    return db.fetch_all(
        """
        select r.*, count(o.id) as obligation_count
        from regulations r left join obligations o on o.regulation_id = r.id
        group by r.id order by r.framework, r.name
        """
    )


@router.get("/catalog/obligations")
def obligations(regulation_id: str | None = None) -> list[dict]:
    return db.fetch_all(
        """
        select o.*, r.framework,
               coalesce(array_agg(co.control_id) filter (where co.control_id is not null), '{}') as control_ids
        from obligations o
        join regulations r on r.id = o.regulation_id
        left join control_obligations co on co.obligation_id = o.id
        where %(reg)s::text is null or o.regulation_id = %(reg)s
        group by o.id, r.framework order by o.id
        """,
        {"reg": regulation_id},
    )


@router.get("/catalog/controls")
def controls() -> list[dict]:
    return db.fetch_all(
        """
        select c.*, e.name as owner,
               (select count(*) from evidence ev where ev.control_id = c.id) as evidence_count
        from controls c left join entities e on e.id = c.owner_id
        order by c.id
        """
    )


@router.get("/catalog/risks")
def risks() -> list[dict]:
    return db.fetch_all(
        "select k.*, a.name as asset_name from risks k left join assets a on a.id = k.asset_id order by k.id"
    )


@router.get("/codebook/instructions")
def instructions() -> list[dict]:
    return db.fetch_all(
        "select id, domain, title, text, success_rate, version, active from instructions order by domain, id"
    )
