from sor.analyze import channel_effect, cluster_boot, rate, wilson


def test_wilson_known_values():
    assert wilson(0, 0) is None
    assert wilson(0, 139) == (0.0, 0.027)
    assert wilson(49, 70) == (0.585, 0.795)
    lo, hi = wilson(5, 10)
    assert lo < 0.5 < hi and abs((0.5 - lo) - (hi - 0.5)) < 1e-3


def test_rate_counts_truthy():
    r = rate([{"x": True}, {"x": False}, {"x": None}], lambda r: r["x"])
    assert (r["k"], r["n"], r["rate"]) == (1, 3, 0.333)


def test_cluster_boot_deterministic_and_brackets_estimate():
    groups = {f"c{i}": [{"v": i % 2}] * 3 for i in range(10)}
    stat = lambda rs: sum(r["v"] for r in rs) / len(rs)  # noqa: E731
    a, b = cluster_boot(groups, stat), cluster_boot(groups, stat)
    assert a == b and a["estimate"] == 0.5 and a["ci95"][0] <= 0.5 <= a["ci95"][1]


def _t1(variant, cid, seed, correct):
    return {"turn": 1, "turn1_variant": variant, "compound_id": cid, "seed": seed, "moa": "M", "correct": correct}


def _t2(cid, seed, auth, correct, favours=True):
    return {"turn": 2, "turn1_variant": "no_nsc", "compound_id": cid, "seed": seed, "status": "ok", "moa": "M",
            "condition": f"auth-{auth}_ev-atlas_dir-correct", "correct": correct,
            "atlas_evidence": {"favours_target": favours}}


def test_channel_effect_pairs_by_compound_and_seed():
    recs = [_t1("with_nsc", "a", 0, True), _t1("with_nsc", "b", 0, False), _t1("with_nsc", "c", 0, True),
            _t2("a", 0, "high", False), _t2("a", 0, "low", True), _t2("b", 0, "high", False),
            _t2("c", 0, "high", True, favours=False)]
    ch = channel_effect(recs)
    assert ch["cells"] == 2 and ch["compounds"] == 2  # c excluded: atlas does not favour the truth
    assert (ch["atlas_as_turn1_data_correct"]["k"], ch["atlas_as_turn1_data_correct"]["n"]) == (1, 2)
    assert (ch["atlas_from_reviewer_corrected"]["k"], ch["atlas_from_reviewer_corrected"]["n"]) == (1, 3)
    assert ch["atlas_from_reviewer_corrected_by_authority"]["low"]["k"] == 1
