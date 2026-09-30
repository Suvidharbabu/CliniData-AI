"""Multi-hop expansion over the compliance knowledge graph.

Retrieved chunks name the graph nodes they came from. Those nodes seed a
traversal that pulls in every node needed to reason about coverage:

    Regulation -HAS_OBLIGATION-> Obligation -SATISFIED_BY-> Control -EVIDENCED_BY-> Evidence
                                  |  ^                        |-PROTECTS-> Asset
                         MAPS_TO  |  | THREATENS              '-OWNED_BY-> Entity
                                  v  |
                            Obligation  Risk -AFFECTS-> Asset
"""
import re

from .. import graph

MAX_OBLIGATIONS = 28

FRAMEWORK_KEYWORDS = {
    "hipaa": "HIPAA",
    "gdpr": "GDPR",
    "part 11": "21 CFR Part 11",
    "21 cfr": "21 CFR Part 11",
    "e-signature": "21 CFR Part 11",
    "ich": "ICH GCP",
    "gcp": "ICH GCP",
    "e2a": "ICH GCP",
    "susar": "ICH GCP",
    "pharmacovigilance": "ICH GCP",
    "dpdp": "DPDP",
    "iso": "ISO 27001",
    "27001": "ISO 27001",
}

# "§164.312", "164.312(b)", "11.10(e)"  |  "Art. 33", "Article 9"  |  "A.8.24"  |  "Section 8(6)"
_SECTION_RE = re.compile(r"(?<![\w.])(\d{2,3}\.\d{1,3}(?:\([a-z0-9]+\))*)", re.I)
_ARTICLE_RE = re.compile(r"\bart(?:icle)?\.?\s*(\d{1,3})\b", re.I)
_ANNEX_RE = re.compile(r"\bA\.(\d{1,2}\.\d{1,2})\b")
_DPDP_SECTION_RE = re.compile(r"\bsection\s+(\d{1,2}(?:\(\d+\))?)", re.I)


def extract_scope(query: str) -> dict:
    """Orchestrator planning: which frameworks and articles does the query name?"""
    q = query.lower()
    frameworks = sorted({fw for kw, fw in FRAMEWORK_KEYWORDS.items() if kw in q})
    refs = [f"§{m}" for m in _SECTION_RE.findall(query)]
    refs += [f"Art. {m}" for m in _ARTICLE_RE.findall(query)]
    refs += [f"A.{m}" for m in _ANNEX_RE.findall(query)]
    refs += [f"Section {m}" for m in _DPDP_SECTION_RE.findall(query)]
    wants_all = bool(re.search(r"\b(all|every|entire|full)\b", q))
    return {"frameworks": frameworks, "article_refs": refs, "framework_wide": wants_all and not refs}


def _scoped_obligation_ids(scope: dict) -> list[str]:
    ids: list[str] = []
    for ref in scope["article_refs"]:
        # "§164.312" should match "§164.312(a)(1)", "Art. 3" must not match "Art. 33"
        rows = graph.run(
            """
            MATCH (r:Regulation)-[:HAS_OBLIGATION]->(o:Obligation)
            WHERE (o.article_ref = $ref OR o.article_ref STARTS WITH $ref + '(' OR o.article_ref STARTS WITH $ref + ' ')
              AND (size($frameworks) = 0 OR r.framework IN $frameworks)
            RETURN o.id AS id ORDER BY o.id
            """,
            ref=ref, frameworks=scope["frameworks"],
        )
        ids += [r["id"] for r in rows]
    if scope["framework_wide"] and scope["frameworks"]:
        rows = graph.run(
            """
            MATCH (r:Regulation)-[:HAS_OBLIGATION]->(o:Obligation)
            WHERE r.framework IN $frameworks RETURN o.id AS id ORDER BY o.id
            """,
            frameworks=scope["frameworks"],
        )
        ids += [r["id"] for r in rows]
    return ids


def _dedupe(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in ids if i))


def expand(chunk_node_ids: list[str], scope: dict) -> dict:
    """Traverse from retrieved nodes to the full compliance context."""
    retrieved_obls = [i for i in chunk_node_ids if i.startswith("OBL-")]
    retrieved_ctls = [i for i in chunk_node_ids if i.startswith("CTL-")]

    # Hop: controls found by retrieval -> the obligations they satisfy
    via_controls = graph.run(
        "MATCH (o:Obligation)-[:SATISFIED_BY]->(c:Control) WHERE c.id IN $ids RETURN DISTINCT o.id AS id",
        ids=retrieved_ctls,
    ) if retrieved_ctls else []

    seeds = _dedupe(_scoped_obligation_ids(scope) + retrieved_obls + [r["id"] for r in via_controls])

    # Hop: cross-framework equivalents (MAPS_TO, either direction)
    maps = graph.run(
        """
        MATCH (a:Obligation)-[m:MAPS_TO]-(b:Obligation)
        WHERE a.id IN $ids
        RETURN DISTINCT a.id AS a, b.id AS b, m.rationale AS rationale
        """,
        ids=seeds,
    ) if seeds else []
    obligation_ids = _dedupe(seeds + [m["b"] for m in maps])[:MAX_OBLIGATIONS]
    in_scope = set(obligation_ids)

    obligations: dict[str, dict] = {}
    regulations: dict[str, dict] = {}
    for row in graph.run(
        """
        MATCH (r:Regulation)-[:HAS_OBLIGATION]->(o:Obligation) WHERE o.id IN $ids
        RETURN properties(o) AS o, properties(r) AS r
        """,
        ids=obligation_ids,
    ):
        obligations[row["o"]["id"]] = {**row["o"], "regulation_id": row["r"]["id"],
                                       "regulation_name": row["r"]["name"], "framework": row["r"]["framework"]}
        regulations[row["r"]["id"]] = row["r"]

    controls: dict[str, dict] = {}
    satisfied_by: list[tuple[str, str]] = []
    assets: dict[str, dict] = {}
    for row in graph.run(
        """
        MATCH (o:Obligation)-[:SATISFIED_BY]->(c:Control) WHERE o.id IN $ids
        OPTIONAL MATCH (c)-[:EVIDENCED_BY]->(e:Evidence)
        OPTIONAL MATCH (c)-[:OWNED_BY]->(owner:Entity)
        RETURN o.id AS obligation_id, properties(c) AS c, owner.name AS owner,
               [x IN collect(DISTINCT properties(e)) WHERE x.id IS NOT NULL] AS evidence
        """,
        ids=obligation_ids,
    ):
        cid = row["c"]["id"]
        controls[cid] = {**row["c"], "owner": row["owner"], "evidence": row["evidence"]}
        satisfied_by.append((row["obligation_id"], cid))

    for row in graph.run(
        "MATCH (c:Control)-[:PROTECTS]->(a:Asset) WHERE c.id IN $ids RETURN c.id AS control_id, properties(a) AS a",
        ids=list(controls),
    ) if controls else []:
        assets[row["a"]["id"]] = row["a"]
        controls[row["control_id"]].setdefault("asset_ids", []).append(row["a"]["id"])

    risks: dict[str, dict] = {}
    threatens: list[tuple[str, str]] = []
    for row in graph.run(
        """
        MATCH (k:Risk)-[:THREATENS]->(o:Obligation) WHERE o.id IN $ids
        OPTIONAL MATCH (k)-[:AFFECTS]->(a:Asset)
        RETURN o.id AS obligation_id, properties(k) AS k, properties(a) AS a
        """,
        ids=obligation_ids,
    ):
        risks[row["k"]["id"]] = {**row["k"], "asset_id": row["a"]["id"] if row["a"] else None}
        threatens.append((row["k"]["id"], row["obligation_id"]))
        if row["a"]:
            assets[row["a"]["id"]] = row["a"]

    return {
        "seed_ids": seeds,
        "obligations": obligations,
        "regulations": regulations,
        "controls": controls,
        "assets": assets,
        "risks": risks,
        "satisfied_by": satisfied_by,
        "threatens": threatens,
        "maps_to": [(m["a"], m["b"], m["rationale"]) for m in maps if m["a"] in in_scope and m["b"] in in_scope],
    }


def known_ids(sub: dict) -> set[str]:
    ids = set(sub["obligations"]) | set(sub["regulations"]) | set(sub["controls"])
    ids |= set(sub["risks"]) | set(sub["assets"])
    ids |= {e["id"] for c in sub["controls"].values() for e in c.get("evidence", [])}
    return ids


def to_view(sub: dict, gaps: list[dict]) -> dict:
    """Nodes and edges for the frontend graph view."""
    gap_severity: dict[str, str] = {}
    for g in gaps:
        gap_severity.setdefault(g["obligation_id"], g["severity"])
    nodes = []
    for r in sub["regulations"].values():
        nodes.append({"id": r["id"], "type": "Regulation", "label": r["name"]})
    for o in sub["obligations"].values():
        nodes.append({"id": o["id"], "type": "Obligation", "label": f'{o["framework"]} {o["article_ref"]}',
                      "title": o["title"], "gap": gap_severity.get(o["id"])})
    for c in sub["controls"].values():
        nodes.append({"id": c["id"], "type": "Control", "label": c["name"], "status": c["implementation_status"]})
        for e in c.get("evidence", []):
            nodes.append({"id": e["id"], "type": "Evidence", "label": e["document_ref"].split("/")[-1]})
    for k in sub["risks"].values():
        nodes.append({"id": k["id"], "type": "Risk", "label": k["name"]})
    # Only assets at risk are drawn; protected-asset links would clutter the view.
    risk_assets = {k.get("asset_id") for k in sub["risks"].values()}
    for a in sub["assets"].values():
        if a["id"] in risk_assets:
            nodes.append({"id": a["id"], "type": "Asset", "label": a["name"]})

    edges = [{"source": o["regulation_id"], "target": o["id"], "type": "HAS_OBLIGATION"} for o in sub["obligations"].values()]
    edges += [{"source": o, "target": c, "type": "SATISFIED_BY"} for o, c in sub["satisfied_by"]]
    edges += [{"source": c["id"], "target": e["id"], "type": "EVIDENCED_BY"}
              for c in sub["controls"].values() for e in c.get("evidence", [])]
    edges += [{"source": k, "target": o, "type": "THREATENS"} for k, o in sub["threatens"]]
    edges += [{"source": k["id"], "target": k["asset_id"], "type": "AFFECTS"} for k in sub["risks"].values() if k.get("asset_id")]
    edges += [{"source": a, "target": b, "type": "MAPS_TO"} for a, b, _ in sub["maps_to"]]

    seen, unique_nodes = set(), []
    for n in nodes:
        if n["id"] not in seen:
            seen.add(n["id"])
            unique_nodes.append(n)
    return {"nodes": unique_nodes, "edges": edges}
