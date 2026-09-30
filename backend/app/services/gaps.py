"""Deterministic gap analysis over an expanded subgraph.

Each function mirrors one specialist agent from the ECRIP design:
Gap Mapper -> Constraint Verifier -> Cross-Reference Agent -> Risk Scorer.
They are plain functions (no LLM) so every finding is reproducible and
traceable to graph nodes before Claude writes the narrative.
"""
SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
APPROVAL_SEVERITIES = {"CRITICAL", "HIGH"}


def lower(severity: str, steps: int = 1) -> str:
    return SEVERITIES[max(0, SEVERITIES.index(severity) - steps)]


def _controls_for(sub: dict, obligation_id: str) -> list[dict]:
    return [sub["controls"][c] for o, c in sub["satisfied_by"] if o == obligation_id and c in sub["controls"]]


def _gap(obl: dict, gap_type: str, severity: str, summary: str, detail: str, controls: list[dict]) -> dict:
    return {
        "obligation_id": obl["id"],
        "framework": obl["framework"],
        "article_ref": obl["article_ref"],
        "title": obl["title"],
        "gap_type": gap_type,
        "severity": severity,
        "summary": summary,
        "detail": detail,
        "control_ids": [c["id"] for c in controls],
        "compound_with": [],
        "risk_ids": [],
        "risk_score": 0.0,
    }


def map_gaps(sub: dict) -> list[dict]:
    """Gap Mapper: coverage and evidence of every in-scope obligation."""
    gaps = []
    for obl in sub["obligations"].values():
        controls = _controls_for(sub, obl["id"])
        implemented = [c for c in controls if c["implementation_status"] == "implemented"]
        others = [c for c in controls if c["implementation_status"] != "implemented"]
        ref = f'{obl["framework"]} {obl["article_ref"]}'

        if not controls:
            gaps.append(_gap(obl, "NO_CONTROL", obl["severity"],
                             f"No control is mapped to {ref} ({obl['title']}).",
                             "The obligation has no SATISFIED_BY edge in the knowledge graph.", []))
            continue
        if not implemented:
            states = ", ".join(f'{c["id"]} is {c["implementation_status"].replace("_", " ")}' for c in controls)
            gaps.append(_gap(obl, "CONTROL_NOT_EFFECTIVE", obl["severity"],
                             f"No implemented control satisfies {ref}.", states + ".", controls))
            continue
        if not any(c.get("evidence") for c in implemented):
            gaps.append(_gap(obl, "MISSING_EVIDENCE", lower(obl["severity"]),
                             f"{ref} is covered by implemented controls, but no audit evidence is on file.",
                             ", ".join(c["id"] for c in implemented) + " has no EVIDENCED_BY record.", implemented))
        if others:
            gaps.append(_gap(obl, "PARTIAL_COVERAGE", lower(obl["severity"]),
                             f"{ref} is only partly covered.",
                             "; ".join(f'{c["id"]} ({c["name"]}) is {c["implementation_status"].replace("_", " ")}'
                                       for c in others) + ".", others))
    return gaps


def _fmt_hours(hours: int) -> str:
    return f"{hours} h ({hours // 24} days)" if hours >= 48 else f"{hours} h"


def verify_constraints(sub: dict) -> list[dict]:
    """Constraint Verifier: committed SLAs vs. statutory deadlines."""
    gaps = []
    for obl in sub["obligations"].values():
        limit = obl.get("deadline_hours")
        if not limit:
            continue
        timed = [c for c in _controls_for(sub, obl["id"])
                 if c["implementation_status"] == "implemented" and c.get("sla_hours")]
        if not timed or min(c["sla_hours"] for c in timed) <= limit:
            continue
        best = min(timed, key=lambda c: c["sla_hours"])
        gaps.append(_gap(
            obl, "DEADLINE_VIOLATION", obl["severity"],
            f'{best["id"]} commits to {_fmt_hours(best["sla_hours"])}, but {obl["framework"]} '
            f'{obl["article_ref"]} requires {obl.get("deadline_label") or _fmt_hours(limit)}.',
            f'Committed {best["sla_hours"]} h > allowed {limit} h, a shortfall of {best["sla_hours"] - limit} h.',
            timed,
        ))
    return gaps


def cross_reference(sub: dict, gaps: list[dict]) -> list[dict]:
    """Cross-Reference Agent: gaps that exist only because two frameworks
    disagree - the control satisfies one obligation but not its equivalent."""
    gap_keys = {(g["obligation_id"], g["gap_type"]) for g in gaps}
    neighbours: dict[str, set[str]] = {}
    for a, b, _ in sub["maps_to"]:
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
    for g in gaps:
        satisfied_peers = [p for p in sorted(neighbours.get(g["obligation_id"], ()))
                           if (p, g["gap_type"]) not in gap_keys and p in sub["obligations"]]
        if satisfied_peers and g["gap_type"] in ("DEADLINE_VIOLATION", "NO_CONTROL", "CONTROL_NOT_EFFECTIVE"):
            g["compound_with"] = satisfied_peers
            refs = ", ".join(f'{sub["obligations"][p]["framework"]} {sub["obligations"][p]["article_ref"]}'
                             for p in satisfied_peers)
            g["detail"] += f" Compound obligation: the equivalent {refs} is met, so single-framework review would miss this."
    return gaps


def score_risk(sub: dict, gaps: list[dict]) -> list[dict]:
    """Risk Scorer: residual = likelihood x impact x (1 - best control effectiveness)."""
    for g in gaps:
        effectiveness = max((float(c.get("effectiveness") or 0) for c in _controls_for(sub, g["obligation_id"])
                             if c["implementation_status"] == "implemented"), default=0.0)
        risk_ids = [k for k, o in sub["threatens"] if o == g["obligation_id"]]
        residuals = [sub["risks"][k]["likelihood"] * sub["risks"][k]["impact"] * (1 - effectiveness)
                     for k in risk_ids]
        g["risk_ids"] = risk_ids
        g["risk_score"] = round(max(residuals, default=0.0), 2)
    gaps.sort(key=lambda g: (-SEVERITIES.index(g["severity"]), -g["risk_score"], g["obligation_id"]))
    return gaps


def analyze(sub: dict) -> list[dict]:
    gaps = map_gaps(sub) + verify_constraints(sub)
    return score_risk(sub, cross_reference(sub, gaps))


def required_role(severity: str) -> str | None:
    return {"CRITICAL": "cco", "HIGH": "compliance_manager"}.get(severity)
