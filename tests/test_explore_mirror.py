import math

import pytest

from sor.explore_mirror import mentions_conflict, phenotype_margin
from sor.load import FEATURES


def test_margin_sign_and_value():
    feats = ("f1", "f2")
    true_c, false_c = {"f1": 0.0, "f2": 0.0}, {"f1": 3.0, "f2": 4.0}
    # profile on the true centroid: distance 0 to truth, 5 to the false class -> +5 (phenotype favours truth)
    assert phenotype_margin(true_c, false_c, true_c, feats) == pytest.approx(5.0)
    # swapping the two centroids flips the sign
    assert phenotype_margin(true_c, true_c, false_c, feats) == pytest.approx(-5.0)
    # equidistant profile -> 0
    assert phenotype_margin({"f1": 1.5, "f2": 2.0}, false_c, true_c, feats) == pytest.approx(0.0)


def test_margin_uses_all_24_features_by_default():
    assert len(FEATURES) == 24
    zero = {f: 0.0 for f in FEATURES}
    one = {f: 1.0 for f in FEATURES}
    assert phenotype_margin(zero, one, zero) == pytest.approx(math.sqrt(24))


def test_conflict_keywords_are_word_starts():
    assert mentions_conflict("Despite the nuclear phenotype, the atlas ranks X first")
    assert mentions_conflict("inconsistent with turn 1")
    assert not mentions_conflict("attributed to tubulin")  # 'but' inside a word does not count
    assert not mentions_conflict(None)
