from backend.app.services import gaps as G
from backend.app.services.graph_expand import extract_scope

from .conftest import subgraph_from_seed


def _find(found, obligation_id, gap_type):
    return next((g for g in found if g["obligation_id"] == obligation_id and g["gap_type"] == gap_type), None)


def test_breach_notification_is_a_compound_deadline_gap(full_subgraph):
    found = G.analyze(full_subgraph)
    gdpr = _find(found, "OBL-GDPR-33", "DEADLINE_VIOLATION")
    assert gdpr is not None and gdpr["severity"] == "CRITICAL"
    assert "OBL-HIPAA-BN-IND" in gdpr["compound_with"]           # HIPAA's 60 days is met
    assert _find(found, "OBL-DPDP-8-6", "DEADLINE_VIOLATION")      # DPDP 72 h also fails
    assert _find(found, "OBL-HIPAA-BN-IND", "DEADLINE_VIOLATION") is None


def test_fatal_susar_track_violates_seven_days(full_subgraph):
    found = G.analyze(full_subgraph)
    assert _find(found, "OBL-E2A-FATAL", "DEADLINE_VIOLATION")
    assert _find(found, "OBL-E2A-OTHER", "DEADLINE_VIOLATION") is None


def test_uncovered_and_ineffective_obligations(full_subgraph):
    found = G.analyze(full_subgraph)
    assert _find(found, "OBL-HIPAA-312A2III", "NO_CONTROL")            # automatic logoff
    assert _find(found, "OBL-DPDP-9", "NO_CONTROL")                    # children's data
    assert _find(found, "OBL-HIPAA-RA", "CONTROL_NOT_EFFECTIVE")       # failed risk analysis
    assert _find(found, "OBL-GDPR-35", "CONTROL_NOT_EFFECTIVE")        # DPIA not started


def test_missing_evidence_and_partial_coverage(full_subgraph):
    found = G.analyze(full_subgraph)
    audit = _find(found, "OBL-P11-AUDIT", "MISSING_EVIDENCE")
    assert audit is not None and audit["severity"] == "HIGH"           # CRITICAL lowered by one
    assert _find(found, "OBL-HIPAA-312A2IV", "PARTIAL_COVERAGE")       # laptops not yet encrypted


def test_well_covered_obligation_has_no_gap(full_subgraph):
    found = G.analyze(full_subgraph)
    assert not [g for g in found if g["obligation_id"] == "OBL-HIPAA-312D"]


def test_risk_scores_and_ordering(full_subgraph):
    found = G.analyze(full_subgraph)
    logoff = _find(found, "OBL-HIPAA-312A2III", "NO_CONTROL")
    assert logoff["risk_ids"] == ["RSK-06"] and logoff["risk_score"] == 9.0   # 3 x 3 x (1 - 0)
    order = [G.SEVERITIES.index(g["severity"]) for g in found]
    assert order == sorted(order, reverse=True)


def test_scope_limits_analysis():
    found = G.analyze(subgraph_from_seed(["OBL-HIPAA-312A2III", "OBL-HIPAA-312D"]))
    assert [g["obligation_id"] for g in found] == ["OBL-HIPAA-312A2III"]


def test_required_roles():
    assert G.required_role("CRITICAL") == "cco"
    assert G.required_role("HIGH") == "compliance_manager"
    assert G.required_role("MEDIUM") is None


def test_extract_scope():
    s = extract_scope("Show all HIPAA §164.312 gaps")
    assert s["frameworks"] == ["HIPAA"] and s["article_refs"] == ["§164.312"] and not s["framework_wide"]
    s = extract_scope("List every GDPR gap")
    assert s["framework_wide"] and s["frameworks"] == ["GDPR"]
    s = extract_scope("Is GDPR Article 33 met?")
    assert s["article_refs"] == ["Art. 33"]
