"""Load the demo dataset into Supabase Postgres, Neo4j AuraDB and Pinecone.

    python -m scripts.seed                 # all three stores
    python -m scripts.seed --only neo4j    # one store (postgres | neo4j | pinecone)

Idempotent: catalogue rows are upserted, graph nodes are rebuilt, and the
Pinecone namespaces are replaced. Codebook success rates survive a re-seed.
Run db/schema.sql in the Supabase SQL editor first.
"""
import argparse
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import db, graph, vector  # noqa: E402
from backend.app.config import get_settings  # noqa: E402
from scripts import seed_data as D  # noqa: E402

REG_BY_ID = {r["id"]: r for r in D.REGULATIONS}


def evidence_hash(e: dict) -> str:
    return hashlib.sha256(f'{e["id"]}|{e["document_ref"]}|{e["collected_at"]}'.encode()).hexdigest()


def chunks() -> list[dict]:
    out = []
    for o in D.OBLIGATIONS:
        reg = REG_BY_ID[o["regulation_id"]]
        deadline = f' Deadline: {o["deadline_label"]}.' if o.get("deadline_label") else ""
        out.append({"id": o["id"], "source_node_id": o["id"], "node_type": "Obligation", "framework": reg["framework"],
                    "text": f'{reg["name"]} ({reg["framework"]}) {o["article_ref"]} - {o["title"]}. {o["text"]}{deadline}'})
    for c in D.CONTROLS:
        out.append({"id": c["id"], "source_node_id": c["id"], "node_type": "Control", "framework": "Internal control",
                    "text": f'Internal control {c["name"]} (status: {c["implementation_status"].replace("_", " ")}). {c["description"]}'})
    for p in D.POLICY_CHUNKS:
        out.append({**p, "node_type": "Policy"})
    return out


# ---------------------------------------------------------------------------
def seed_postgres() -> None:
    with db.connection() as conn:
        with conn.transaction():
            for r in D.REGULATIONS:
                conn.execute(
                    """
                    insert into regulations (id, name, framework, jurisdiction, version, effective_date, source_url)
                    values (%(id)s, %(name)s, %(framework)s, %(jurisdiction)s, %(version)s, %(effective_date)s, %(source_url)s)
                    on conflict (id) do update set name = excluded.name, framework = excluded.framework,
                      jurisdiction = excluded.jurisdiction, version = excluded.version,
                      effective_date = excluded.effective_date, source_url = excluded.source_url
                    """, r)
            for o in D.OBLIGATIONS:
                conn.execute(
                    """
                    insert into obligations (id, regulation_id, article_ref, title, text, obligation_type, severity,
                                             deadline_hours, deadline_label)
                    values (%(id)s, %(regulation_id)s, %(article_ref)s, %(title)s, %(text)s, %(obligation_type)s,
                            %(severity)s, %(deadline_hours)s, %(deadline_label)s)
                    on conflict (id) do update set regulation_id = excluded.regulation_id, article_ref = excluded.article_ref,
                      title = excluded.title, text = excluded.text, obligation_type = excluded.obligation_type,
                      severity = excluded.severity, deadline_hours = excluded.deadline_hours,
                      deadline_label = excluded.deadline_label
                    """, {"deadline_hours": None, "deadline_label": None, **o})
            for e in D.ENTITIES:
                conn.execute(
                    """
                    insert into entities (id, name, entity_type, jurisdiction) values (%(id)s, %(name)s, %(entity_type)s, %(jurisdiction)s)
                    on conflict (id) do update set name = excluded.name, entity_type = excluded.entity_type,
                      jurisdiction = excluded.jurisdiction
                    """, e)
            for a in D.ASSETS:
                conn.execute(
                    """
                    insert into assets (id, name, asset_type, classification, owner_id, location)
                    values (%(id)s, %(name)s, %(asset_type)s, %(classification)s, %(owner_id)s, %(location)s)
                    on conflict (id) do update set name = excluded.name, asset_type = excluded.asset_type,
                      classification = excluded.classification, owner_id = excluded.owner_id, location = excluded.location
                    """, a)
            for c in D.CONTROLS:
                conn.execute(
                    """
                    insert into controls (id, name, description, control_type, owner_id, implementation_status,
                                          effectiveness, sla_hours, last_assessed)
                    values (%(id)s, %(name)s, %(description)s, %(control_type)s, %(owner_id)s, %(implementation_status)s,
                            %(effectiveness)s, %(sla_hours)s, %(last_assessed)s)
                    on conflict (id) do update set name = excluded.name, description = excluded.description,
                      control_type = excluded.control_type, owner_id = excluded.owner_id,
                      implementation_status = excluded.implementation_status, effectiveness = excluded.effectiveness,
                      sla_hours = excluded.sla_hours, last_assessed = excluded.last_assessed
                    """, {"sla_hours": None, **c})
            for k in D.RISKS:
                conn.execute(
                    """
                    insert into risks (id, name, category, likelihood, impact, asset_id)
                    values (%(id)s, %(name)s, %(category)s, %(likelihood)s, %(impact)s, %(asset_id)s)
                    on conflict (id) do update set name = excluded.name, category = excluded.category,
                      likelihood = excluded.likelihood, impact = excluded.impact, asset_id = excluded.asset_id
                    """, k)

            # Link tables and derived data are rebuilt from scratch.
            for table in ("control_obligations", "control_assets", "obligation_mappings", "risk_obligations",
                          "evidence", "doc_chunks"):
                conn.execute(f"delete from {table}")
            for c in D.CONTROLS:
                for o in c["satisfies"]:
                    conn.execute("insert into control_obligations values (%s, %s)", (c["id"], o))
                for a in c["assets"]:
                    conn.execute("insert into control_assets values (%s, %s)", (c["id"], a))
            for a, b, why in D.MAPPINGS:
                conn.execute("insert into obligation_mappings values (%s, %s, %s)", (a, b, why))
            for k in D.RISKS:
                for o in k["threatens"]:
                    conn.execute("insert into risk_obligations values (%s, %s)", (k["id"], o))
            for e in D.EVIDENCE:
                conn.execute(
                    """
                    insert into evidence (id, control_id, document_ref, collected_at, verified_by, doc_hash)
                    values (%(id)s, %(control_id)s, %(document_ref)s, %(collected_at)s, %(verified_by)s, %(doc_hash)s)
                    """, {**e, "doc_hash": evidence_hash(e)})
            for ch in chunks():
                conn.execute(
                    "insert into doc_chunks (id, source_node_id, node_type, framework, text) values (%(id)s, %(source_node_id)s, %(node_type)s, %(framework)s, %(text)s)",
                    ch)
            for i in D.INSTRUCTIONS:
                conn.execute(
                    """
                    insert into instructions (id, domain, title, text) values (%(id)s, %(domain)s, %(title)s, %(text)s)
                    on conflict (id) do update set domain = excluded.domain, title = excluded.title, text = excluded.text
                    """, i)
    print(f"postgres: {len(D.REGULATIONS)} regulations, {len(D.OBLIGATIONS)} obligations, {len(D.CONTROLS)} controls, "
          f"{len(D.RISKS)} risks, {len(D.EVIDENCE)} evidence, {len(chunks())} chunks, {len(D.INSTRUCTIONS)} instructions")


# ---------------------------------------------------------------------------
LABELS = ["Regulation", "Obligation", "Control", "Risk", "Asset", "Entity", "Evidence"]


def seed_neo4j() -> None:
    for label in LABELS:
        graph.run(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")
    graph.run("MATCH (n) WHERE any(l IN labels(n) WHERE l IN $labels) DETACH DELETE n", labels=LABELS)

    graph.run("UNWIND $rows AS r CREATE (n:Regulation) SET n = r", rows=D.REGULATIONS)
    graph.run("UNWIND $rows AS r CREATE (n:Entity) SET n = r",
              rows=[{k: v for k, v in e.items() if v is not None} for e in D.ENTITIES])
    graph.run(
        """
        UNWIND $rows AS r
        MATCH (reg:Regulation {id: r.regulation_id})
        CREATE (o:Obligation) SET o = r
        CREATE (reg)-[:HAS_OBLIGATION]->(o)
        """,
        rows=[{k: v for k, v in o.items() if v is not None} for o in D.OBLIGATIONS],
    )
    graph.run(
        """
        UNWIND $rows AS r
        CREATE (a:Asset) SET a = r
        WITH a, r MATCH (e:Entity {id: r.owner_id}) CREATE (a)-[:OWNED_BY]->(e)
        """,
        rows=D.ASSETS,
    )
    control_rows = [{k: v for k, v in c.items() if k not in ("satisfies", "assets") and v is not None} for c in D.CONTROLS]
    graph.run(
        """
        UNWIND $rows AS r
        CREATE (c:Control) SET c = r
        WITH c, r MATCH (e:Entity {id: r.owner_id}) CREATE (c)-[:OWNED_BY]->(e)
        """,
        rows=control_rows,
    )
    graph.run(
        """
        UNWIND $rows AS r
        MATCH (o:Obligation {id: r.obligation}), (c:Control {id: r.control})
        CREATE (o)-[:SATISFIED_BY]->(c)
        """,
        rows=[{"obligation": o, "control": c["id"]} for c in D.CONTROLS for o in c["satisfies"]],
    )
    graph.run(
        """
        UNWIND $rows AS r
        MATCH (c:Control {id: r.control}), (a:Asset {id: r.asset})
        CREATE (c)-[:PROTECTS]->(a)
        """,
        rows=[{"control": c["id"], "asset": a} for c in D.CONTROLS for a in c["assets"]],
    )
    graph.run(
        """
        UNWIND $rows AS r
        MATCH (a:Obligation {id: r.a}), (b:Obligation {id: r.b})
        CREATE (a)-[:MAPS_TO {rationale: r.why}]->(b)
        """,
        rows=[{"a": a, "b": b, "why": why} for a, b, why in D.MAPPINGS],
    )
    graph.run(
        """
        UNWIND $rows AS r
        CREATE (e:Evidence) SET e = r.props
        WITH e, r MATCH (c:Control {id: r.control}) CREATE (c)-[:EVIDENCED_BY]->(e)
        """,
        rows=[{"control": e["control_id"], "props": {**{k: v for k, v in e.items() if k != "control_id"},
                                                     "hash": evidence_hash(e)}} for e in D.EVIDENCE],
    )
    graph.run(
        """
        UNWIND $rows AS r
        CREATE (k:Risk) SET k = r.props
        WITH k, r
        MATCH (a:Asset {id: r.asset}) CREATE (k)-[:AFFECTS]->(a)
        WITH k, r
        UNWIND r.threatens AS oid
        MATCH (o:Obligation {id: oid}) CREATE (k)-[:THREATENS]->(o)
        """,
        rows=[{"props": {k: v for k, v in r.items() if k not in ("threatens", "asset_id")},
               "asset": r["asset_id"], "threatens": r["threatens"]} for r in D.RISKS],
    )
    counts = graph.run("MATCH (n) WHERE any(l IN labels(n) WHERE l IN $labels) RETURN count(n) AS n", labels=LABELS)
    rels = graph.run("MATCH ()-[r]->() RETURN count(r) AS n")
    print(f"neo4j: {counts[0]['n']} nodes, {rels[0]['n']} relationships")


# ---------------------------------------------------------------------------
def seed_pinecone() -> None:
    pc, name = vector.client(), get_settings().pinecone_index
    if not pc.has_index(name):
        print(f"pinecone: creating index '{name}' with integrated embedding {vector.EMBED_MODEL} ...")
        pc.create_index_for_model(
            name=name, cloud="aws", region="us-east-1",
            embed={"model": vector.EMBED_MODEL, "field_map": {"text": vector.TEXT_FIELD}},
        )
        while not pc.describe_index(name).status.ready:
            time.sleep(2)
    idx = vector.index()

    doc_records = [{"_id": c["id"], vector.TEXT_FIELD: c["text"], "node_id": c["source_node_id"],
                    "node_type": c["node_type"], "framework": c["framework"] or ""} for c in chunks()]
    codebook_records = [{"_id": i["id"], vector.TEXT_FIELD: f'{i["title"]}. {i["text"]}', "domain": i["domain"],
                         "title": i["title"]} for i in D.INSTRUCTIONS]

    for namespace, records in ((vector.DOCS_NS, doc_records), (vector.CODEBOOK_NS, codebook_records)):
        try:
            idx.delete(delete_all=True, namespace=namespace)
        except Exception:
            pass  # namespace does not exist yet
        for start in range(0, len(records), 90):  # integrated-embedding upserts take up to 96 records
            idx.upsert_records(namespace=namespace, records=records[start:start + 90])
        print(f"pinecone: upserted {len(records)} records into '{namespace}'")
    time.sleep(5)  # records become searchable after a short indexing delay


STORES = {"postgres": seed_postgres, "neo4j": seed_neo4j, "pinecone": seed_pinecone}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=list(STORES))
    args = parser.parse_args()
    for store_name, fn in STORES.items():
        if args.only in (None, store_name):
            fn()
    print("done")
