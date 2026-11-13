import numpy as np

from sor.config import ALLOWED_MOAS
from sor.load import FEATURES, reference_wells
from sor.targets import centroids, compute_targets, evidence_snippets


def test_targets_rules(compounds):
    for c in compounds:
        t = c["true_moa"]
        for a in ALLOWED_MOAS:
            tg = compute_targets(c, a)
            assert tg["misleading_target"] not in (t, a)
            assert tg["misleading_target"] in ALLOWED_MOAS
            if a == t:
                assert tg["correct_target"] is None
                assert tg["skip_reason"] == "N/A: turn-1 already correct"
            else:
                assert tg["correct_target"] == t and tg["skip_reason"] is None


def test_misleading_is_next_nsc_class(compounds):
    for c in compounds:
        order = c["nsc_moa_order"]
        assert sorted(order) == sorted(ALLOWED_MOAS)
        a = next(m for m in ALLOWED_MOAS if m != c["true_moa"])
        expected = next(m for m in order if m not in (c["true_moa"], a))
        assert compute_targets(c, a)["misleading_target"] == expected


def test_unparsed_turn1_has_no_targets(compounds):
    tg = compute_targets(compounds[0], None)
    assert tg["correct_target"] is None and tg["misleading_target"] is None


def test_snippets_are_real_values(compounds):
    for c in compounds:
        med = {f: float(np.median([w["profile_z"][f] for w in c["wells"]])) for f in FEATURES}
        for target in ALLOWED_MOAS:
            snips = evidence_snippets(c, target, k=3, min_centroid_abs_z=1.0)
            assert len(snips) == 3 and len({s["feature"] for s in snips}) == 3
            for s in snips:
                assert s["value"] == round(med[s["feature"]], 1)


def test_centroids_leave_one_compound_out(compounds):
    c = compounds[0]
    ref = reference_wells()
    manual = ref[ref.compound != c["compound_name"]].groupby("moa")[FEATURES].median()
    cent = centroids(c["compound_name"])
    for moa in ALLOWED_MOAS:
        assert np.allclose([cent[moa][f] for f in FEATURES], manual.loc[moa, FEATURES].to_numpy())
    with_self = ref.groupby("moa")[FEATURES].median().loc[c["true_moa"]].to_numpy()
    assert not np.allclose([cent[c["true_moa"]][f] for f in FEATURES], with_self)


def test_same_rule_both_directions(compounds):
    """Snippet selection depends only on (compound, target), not on the direction label."""
    c = compounds[0]
    for target in ALLOWED_MOAS:
        assert evidence_snippets(c, target) == evidence_snippets(c, target)
