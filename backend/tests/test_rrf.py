from backend.app.services.retrieval import rrf


def test_document_in_both_lists_ranks_first():
    fused = rrf([["a", "b", "c"], ["c", "d", "a"]])
    ids = [doc_id for doc_id, _ in fused]
    assert ids[0] == "a"          # rank 1 + rank 3
    assert ids[1] == "c"          # rank 3 + rank 1 (ties broken by insertion order)
    assert set(ids) == {"a", "b", "c", "d"}


def test_scores_follow_formula():
    fused = dict(rrf([["x"], ["y", "x"]], k=60))
    assert fused["x"] == 1 / 61 + 1 / 62
    assert fused["y"] == 1 / 61


def test_empty_lists():
    assert rrf([[], []]) == []
