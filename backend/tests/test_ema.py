from pytest import approx

from backend.app.services.codebook import blend, ema


def test_ema_moves_toward_outcome():
    assert ema(0.7, 1.0) == 0.76
    assert ema(0.7, 0.0) == 0.56


def test_ema_converges_after_repeated_negative_feedback():
    rate = 0.7
    for _ in range(10):
        rate = ema(rate, 0.0)
    assert rate < 0.1


def test_blend_prefers_higher_success_at_equal_similarity():
    assert blend(0.8, 0.9) > blend(0.8, 0.3)
    assert blend(0.8, 1.0) == approx(0.8)
