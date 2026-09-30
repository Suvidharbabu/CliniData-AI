from backend.app.services.guard import check, cited_ids

KNOWN = {"OBL-GDPR-33", "CTL-IR-01", "EVD-002"}


def test_extracts_ids_from_grouped_citations():
    assert cited_ids("Late notice [CTL-IR-01, EVD-002] and [OBL-GDPR-33].") == ["CTL-IR-01", "EVD-002", "OBL-GDPR-33"]


def test_ids_outside_brackets_are_not_citations():
    assert cited_ids("CTL-IR-01 is mentioned but not cited.") == []


def test_unknown_id_fails_guard():
    answer = "- **CRITICAL** The procedure misses the 72-hour window [OBL-GDPR-33, CTL-FAKE-99]."
    report = check(answer, KNOWN)
    assert report["unknown_ids"] == ["CTL-FAKE-99"]
    assert report["passed"] is False


def test_uncited_claims_lower_grounding():
    answer = "\n".join([
        "## Findings",
        "- **CRITICAL** SOP-SEC-014 commits to 30 days, exceeding GDPR's 72 hours [CTL-IR-01, OBL-GDPR-33].",
        "- The organisation should also review its vendor contracts every single year.",
        "- Evidence of the procedure is on file from January 2026 [EVD-002].",
    ])
    report = check(answer, KNOWN)
    assert report["claim_units"] == 3
    assert report["uncited_units"] == 1
    assert report["grounding_ratio"] == 0.67
    assert report["passed"] is True


def test_headings_and_short_lines_are_not_claims():
    report = check("## Summary\n**Findings**\nOK.", KNOWN)
    assert report["claim_units"] == 0
