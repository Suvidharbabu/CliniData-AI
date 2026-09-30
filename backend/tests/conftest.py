import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import seed_data as D  # noqa: E402


def subgraph_from_seed(obligation_ids: list[str] | None = None) -> dict:
    """Build the same structure graph_expand.expand() returns, straight from the seed data."""
    regs = {r["id"]: r for r in D.REGULATIONS}
    wanted = set(obligation_ids or [o["id"] for o in D.OBLIGATIONS])
    obligations = {
        o["id"]: {**o, "regulation_name": regs[o["regulation_id"]]["name"],
                  "framework": regs[o["regulation_id"]]["framework"]}
        for o in D.OBLIGATIONS if o["id"] in wanted
    }
    evidence: dict[str, list[dict]] = {}
    for e in D.EVIDENCE:
        evidence.setdefault(e["control_id"], []).append(e)
    controls, satisfied_by = {}, []
    for c in D.CONTROLS:
        hits = [o for o in c["satisfies"] if o in wanted]
        if hits:
            controls[c["id"]] = {**c, "evidence": evidence.get(c["id"], []), "asset_ids": c["assets"]}
            satisfied_by += [(o, c["id"]) for o in hits]
    risks, threatens = {}, []
    for k in D.RISKS:
        hits = [o for o in k["threatens"] if o in wanted]
        if hits:
            risks[k["id"]] = k
            threatens += [(k["id"], o) for o in hits]
    return {
        "seed_ids": list(wanted),
        "obligations": obligations,
        "regulations": {o["regulation_id"]: regs[o["regulation_id"]] for o in obligations.values()},
        "controls": controls,
        "assets": {},
        "risks": risks,
        "satisfied_by": satisfied_by,
        "threatens": threatens,
        "maps_to": [(a, b, why) for a, b, why in D.MAPPINGS if a in wanted and b in wanted],
    }


@pytest.fixture
def full_subgraph() -> dict:
    return subgraph_from_seed()
