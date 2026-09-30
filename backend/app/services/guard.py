"""Hallucination guard: every claim in the answer must trace to a node in the
retrieved subgraph.

- Citations are node IDs in square brackets, e.g. [OBL-GDPR-33] or [CTL-IR-01, EVD-002].
- A cited ID that is not in the subgraph is flagged as unknown (fabricated).
- A substantive paragraph or bullet with no citation at all is flagged as uncited.
"""
import re

ID_RE = re.compile(r"\b(?:OBL|CTL|REG|RSK|AST|EVD|ENT|POL)-[A-Z0-9][A-Z0-9-]*\b")
BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")
MIN_CLAIM_CHARS = 40
PASS_RATIO = 0.6


def cited_ids(text: str) -> list[str]:
    ids: list[str] = []
    for group in BRACKET_RE.findall(text):
        ids += ID_RE.findall(group)
    return ids


def _claim_units(answer: str) -> list[str]:
    units = []
    for line in answer.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("|") or stripped.startswith("---"):
            continue
        body = re.sub(r"^([-*+]|\d+\.)\s+", "", stripped)
        # A bold label on its own ("**Summary**") is a heading, not a claim.
        if len(re.sub(r"[*_`]", "", body)) >= MIN_CLAIM_CHARS:
            units.append(body)
    return units


def check(answer: str, known: set[str]) -> dict:
    ids = cited_ids(answer)
    unknown = sorted({i for i in ids if i not in known})
    units = _claim_units(answer)
    uncited = [u for u in units if not cited_ids(u)]
    ratio = (len(units) - len(uncited)) / len(units) if units else 0.0
    return {
        "cited_ids": sorted(set(ids) - set(unknown)),
        "unknown_ids": unknown,
        "claim_units": len(units),
        "uncited_units": len(uncited),
        "uncited_examples": [u[:160] for u in uncited[:3]],
        "grounding_ratio": round(ratio, 2),
        "passed": not unknown and ratio >= PASS_RATIO,
    }
