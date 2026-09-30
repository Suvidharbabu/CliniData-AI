from backend.app.services import gaps as G, graph_expand, guard, llm

from .conftest import subgraph_from_seed


def _check(sub):
    found = G.analyze(sub)
    report = llm.template_answer("q", sub, found)
    return report, guard.check(report["text"], graph_expand.known_ids(sub))


def test_rule_based_report_is_fully_grounded(full_subgraph):
    report, result = _check(full_subgraph)
    assert report["model"] == llm.RULE_BASED_MODEL
    assert result["unknown_ids"] == []
    assert result["uncited_units"] == 0 and result["passed"]
    assert "## Findings" in report["text"] and "## Recommended remediation" in report["text"]


def test_rule_based_report_without_gaps():
    report, result = _check(subgraph_from_seed(["OBL-HIPAA-312D"]))
    assert "No gaps were found" in report["text"] and result["passed"]


def test_rule_based_report_with_empty_scope():
    assert "No obligations" in llm.template_answer("q", subgraph_from_seed([]) | {"obligations": {}}, [])["text"]
