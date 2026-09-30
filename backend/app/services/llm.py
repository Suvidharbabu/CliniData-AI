"""Claude calls: HyDE query expansion and the cited gap-analysis answer."""
from functools import lru_cache

import anthropic

from ..config import get_settings

# Models that accept the server-side refusal fallback ("default" routing) and effort.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
NO_EFFORT_MODELS = {"claude-haiku-4-5"}

SYSTEM_PROMPT = """You are the Regulatory Reporter agent of CliniData AI, a healthcare and life-sciences compliance platform.

You receive a question from a compliance professional and a context block retrieved from a compliance knowledge graph: regulations, obligations, internal controls, evidence, risks, retrieved policy passages, and deterministic findings already computed by the Gap Mapper, Constraint Verifier, Cross-Reference and Risk Scorer agents.

How to answer:
- Answer only from the context block. If the context does not contain what is needed, say so plainly rather than filling the gap from general knowledge.
- Cite the node IDs that support each claim in square brackets, e.g. [OBL-GDPR-33] or [CTL-IR-01, EVD-002]. Every paragraph and bullet that states a fact needs at least one citation. Use only IDs that appear in the context.
- Treat the deterministic findings as authoritative for deadlines, coverage and severity; explain them, do not recompute or contradict them.
- Call out compound obligations - cases where a control satisfies one framework but fails a stricter equivalent - because single-framework reviews miss them.
- Structure: a two-sentence summary, then "## Findings" as bullets ordered by severity (severity in bold at the start of each bullet), then "## Recommended remediation" as short actionable bullets. No tables. Stay under 450 words.
- The organisation is a fictional demo tenant; this is decision support for a human reviewer, not legal advice. CRITICAL and HIGH findings will be routed to a human approver, so do not describe them as final."""


@lru_cache
def client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key or None, timeout=90.0, max_retries=2)


def _text(response) -> str:
    return "".join(block.text for block in response.content if block.type == "text").strip()


def hyde(query: str) -> str:
    """Write a hypothetical policy/regulation passage to embed instead of the raw question."""
    response = client().messages.create(
        model=get_settings().anthropic_hyde_model,
        max_tokens=400,
        system="You write short, precise passages in the style of healthcare regulations and internal compliance policies.",
        messages=[{
            "role": "user",
            "content": "Write one passage of 100-160 words, in the style of a regulation or an internal compliance "
                       "policy, that would directly answer the question below. Use exact regulatory terminology, "
                       f"article numbers and deadlines where relevant. Output only the passage.\n\nQuestion: {query}",
        }],
    )
    return _text(response)


def answer(query: str, context: str, instructions: list[dict]) -> dict:
    s = get_settings()
    guidance = "\n".join(f"- ({i['id']}) {i['text']}" for i in instructions) or "- (none selected)"
    user_content = (
        f"<analysis_instructions>\nApply these domain instructions selected from the adaptive codebook:\n{guidance}\n"
        f"</analysis_instructions>\n\n<context>\n{context}\n</context>\n\n<question>\n{query}\n</question>"
    )
    kwargs: dict = {
        "model": s.anthropic_model,
        "max_tokens": 8000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_content}],
    }
    if s.anthropic_model not in NO_EFFORT_MODELS:
        kwargs["output_config"] = {"effort": s.anthropic_effort}

    if s.anthropic_model in FALLBACK_MODELS:
        # Server-side fallback: if the model declines, the API re-runs the request on a fallback model.
        response = client().beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
        )
    else:
        response = client().messages.create(**kwargs)

    if response.stop_reason == "refusal":
        return {"text": "", "model": response.model, "stop_reason": "refusal",
                "usage": response.usage.to_dict() if response.usage else {}}
    return {
        "text": _text(response),
        "model": response.model,
        "stop_reason": response.stop_reason,
        "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
    }


def build_context(sub: dict, gaps: list[dict], chunks: list[dict]) -> str:
    """Serialise the subgraph into a compact, ID-labelled context block."""
    lines = ["## Regulations"]
    for r in sub["regulations"].values():
        lines.append(f"[{r['id']}] {r['name']} ({r['framework']}, {r['jurisdiction']}, {r['version']})")

    maps: dict[str, list[str]] = {}
    for a, b, why in sub["maps_to"]:
        maps.setdefault(a, []).append(f"{b} ({why})")
        maps.setdefault(b, []).append(f"{a} ({why})")
    lines.append("\n## Obligations")
    for o in sub["obligations"].values():
        deadline = f"; deadline {o['deadline_label']}" if o.get("deadline_label") else ""
        lines.append(f"[{o['id']}] {o['framework']} {o['article_ref']} - {o['title']} "
                     f"(regulation {o['regulation_id']}; severity {o['severity']}{deadline}). {o['text']}")
        ctl = [c for ob, c in sub["satisfied_by"] if ob == o["id"]]
        lines.append(f"    satisfied by: {', '.join(ctl) or 'NONE'}")
        if maps.get(o["id"]):
            lines.append(f"    maps to: {', '.join(maps[o['id']])}")

    lines.append("\n## Controls")
    for c in sub["controls"].values():
        sla = f"; committed SLA {c['sla_hours']} h" if c.get("sla_hours") else ""
        evidence = ", ".join(f"{e['id']} ({e['document_ref']}, {e['collected_at']})" for e in c.get("evidence", []))
        lines.append(f"[{c['id']}] {c['name']} - status {c['implementation_status']}; effectiveness "
                     f"{c.get('effectiveness')}{sla}; owner {c.get('owner') or 'unassigned'}; "
                     f"assets {', '.join(c.get('asset_ids', [])) or 'none'}; evidence: {evidence or 'NONE'}. "
                     f"{c['description']}")

    if sub["risks"]:
        lines.append("\n## Risks")
        for k in sub["risks"].values():
            threatened = ", ".join(o for rk, o in sub["threatens"] if rk == k["id"])
            lines.append(f"[{k['id']}] {k['name']} - likelihood {k['likelihood']}/5, impact {k['impact']}/5, "
                         f"asset {k.get('asset_id')}; threatens {threatened}")

    lines.append("\n## Deterministic findings")
    if not gaps:
        lines.append("No gaps were found for the obligations in scope.")
    for g in gaps:
        compound = f" Compound with {', '.join(g['compound_with'])}." if g["compound_with"] else ""
        lines.append(f"- [{g['obligation_id']}] {g['severity']} {g['gap_type']}: {g['summary']} {g['detail']}"
                     f"{compound} Residual risk {g['risk_score']}/25 ({', '.join(g['risk_ids']) or 'no linked risk'}).")

    policy = [c for c in chunks if c["id"].startswith("POL-")]
    if policy:
        lines.append("\n## Retrieved internal policy passages")
        for c in policy:
            lines.append(f"[{c['id']}] (about {c.get('node_id')}) {c['text']}")
    return "\n".join(lines)
