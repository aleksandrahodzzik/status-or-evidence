"""Mirror experiment (sor.mirror): the falsified atlas block is an exact, symmetric label swap that favours the
misleading target; prompts are Section 4.7's; fake-API end to end."""

import json
import re
from pathlib import Path

import pandas as pd
import pytest
import yaml

from conftest import FakeTransport
from sor import channel, mirror
from sor import run as runmod
from sor.config import ALLOWED_MOAS, ROOT
from sor.prompts import AUTHORITY
from sor.targets import compute_targets


def _targets(c):
    """Every misleading target the primary rule can produce for this compound (one per possible turn-1 answer)."""
    return sorted({compute_targets(c, a)["misleading_target"] for a in ALLOWED_MOAS})


def _mask(text):
    return mirror._CLASS_RE.sub("<CLASS>", text)


def test_swap_handles_nested_class_names():
    s = "Aurora kinase inhibitors 3/10, Kinase inhibitors 2/10, Cholesterol-lowering 1/10"
    assert mirror.swap_labels(s, "Kinase inhibitors", "DNA damage") == \
        "Aurora kinase inhibitors 3/10, DNA damage 2/10, Cholesterol-lowering 1/10"
    assert mirror.swap_labels(s, "Aurora kinase inhibitors", "Kinase inhibitors") == \
        "Kinase inhibitors 3/10, Aurora kinase inhibitors 2/10, Cholesterol-lowering 1/10"
    with pytest.raises(ValueError):
        mirror.swap_labels(s, "DNA damage", "DNA damage")


def test_swap_is_exact_and_symmetric(compounds):
    for c in compounds:
        block = channel.atlas_block(c)
        truth = c["true_moa"]
        for t in _targets(c):
            fake = mirror.swap_labels(block, truth, t)
            assert fake == mirror.swap_labels(block, t, truth)                 # symmetric
            assert mirror.swap_labels(fake, truth, t) == block                 # involution: nothing else changed
            assert _mask(fake) == _mask(block)                                 # every number and word in place
            m = {truth: t, t: truth}
            assert mirror.class_mentions(fake) == [m.get(x, x) for x in mirror.class_mentions(block)]
            assert mirror.class_mentions(block).count(truth) == mirror.class_mentions(fake).count(t)


def test_falsified_block_names_the_target_as_winner_never_the_truth(compounds):
    n = 0
    for c in compounds:
        truth = c["true_moa"]
        for t in _targets(c):
            if mirror.ineligible_reason(c, t):
                continue
            n += 1
            real, fake = channel.atlas_block(c), mirror.falsified_block(c, t)
            assert truth not in mirror.vote_winners(fake), (c["compound_id"], t)
            assert [t if w == truth else w for w in mirror.vote_winners(real)] == mirror.vote_winners(fake)
            assert t in mirror.vote_winners(fake)
    assert n > 0


def test_eligibility_rule(compounds):
    off = {c["compound_id"] for c in compounds if c["nsc_moa_order"][0] != c["true_moa"]}
    assert len(off) == 7
    for c in compounds:
        for t in _targets(c):
            r = mirror.ineligible_reason(c, t)
            if c["compound_id"] in off:
                assert r is not None
            elif r is not None:
                assert t in mirror.vote_winners(channel.atlas_block(c))


def test_prompts_are_section_4_7_with_the_falsified_block(compounds):
    c = next(c for c in compounds if c["nsc_moa_order"][0] == c["true_moa"])
    t = _targets(c)[0]
    fake = mirror.falsified_block(c, t)
    for k in mirror.CONDITIONS:
        m = mirror.message(k, fake, t)
        assert m == channel.message(mirror.TRUE_OF[k], fake, t)
        assert m.count(fake) == 1 and channel.atlas_block(c) not in m
    assert "I think the MoA" not in mirror.message("fake-tool", fake, t)
    assert "I think the MoA" not in mirror.message("fake-share", fake, t)
    assert AUTHORITY["high"] in mirror.message("fake-share", fake, t)
    assert f"I think the MoA is {t}." in mirror.message("fake-dispute-senior", fake, t)
    assert AUTHORITY["high"] in mirror.message("fake-dispute-senior", fake, t)
    assert AUTHORITY["low"] in mirror.message("fake-dispute-junior", fake, t)


def test_no_compound_names_in_falsified_messages(compounds):
    names = pd.read_csv(ROOT / "data" / "raw" / "metadata" / "BBBC021_v1_compound.csv").compound.dropna()
    names = sorted({n for n in names if n.lower() not in ("dmso", "unknown")}, key=len, reverse=True)
    pat = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in names) + r")(?![\w-])", re.I)
    for c in compounds:
        for t in _targets(c):
            fake = mirror.falsified_block(c, t)
            for k in mirror.CONDITIONS:
                assert not pat.search(mirror.message(k, fake, t)), (c["compound_id"], t, k)


def _seed0(cfg, tmp_path):
    cfg = {**cfg, "seeds": [0]}
    p = tmp_path / "config_seed0.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return cfg, str(p)


def test_needs_cached_turn1_and_yes(cfg, tmp_path):
    cfg, f = _seed0(cfg, tmp_path)
    fake = FakeTransport()
    assert mirror.main(["--config", f], transport=fake) == 1
    assert fake.calls == []
    assert runmod.main(["pilot", "--turn1-variant", "no_nsc", "--yes", "--config", f], transport=fake) == 0
    n = len(fake.calls)
    assert mirror.main(["--config", f], transport=fake) == 0
    assert len(fake.calls) == n


def test_end_to_end_with_fake_api(cfg, tmp_path, compounds):
    cfg, f = _seed0(cfg, tmp_path)
    answer = "Microtubule stabilizers"
    fake = FakeTransport(answer)
    assert runmod.main(["pilot", "--turn1-variant", "no_nsc", "--yes", "--config", f], transport=fake) == 0
    n_pilot = len(fake.calls)
    assert mirror.main(["--yes", "--config", f], transport=fake) == 0
    eligible = [c for c in compounds
                if not mirror.ineligible_reason(c, compute_targets(c, answer)["misleading_target"])]
    assert len(fake.calls) - n_pilot == 4 * len(eligible)
    run = sorted(Path(cfg["paths"]["runs"]).glob("mirror_*/raw.jsonl"))[-1]
    recs = [json.loads(x) for x in run.read_text(encoding="utf-8").splitlines()]
    t2 = [r for r in recs if r["turn"] == 2 and r["status"] != "skipped"]
    assert len(t2) == 4 * len(eligible)
    assert sum(r["status"] == "skipped" for r in recs) == 4 * (len(compounds) - len(eligible))
    for r in t2:
        c = next(x for x in compounds if x["compound_id"] == r["compound_id"])
        t = compute_targets(c, answer)["misleading_target"]
        assert r["target_moa"] == t and r["atlas_evidence"]["swapped"] == [c["true_moa"], t]
        assert mirror.falsified_block(c, t) in r["messages"][-1]["content"]
        assert r["followed_target"] is r["condition"].startswith("fake-dispute")  # the fake follows disputes only
    res = mirror.analyse(recs)
    assert res["conditions"]["fake-dispute-senior"]["follow"]["rate"] == 1.0
    assert res["conditions"]["fake-tool"]["follow"]["rate"] == 0.0
    assert res["contrasts"]["fake-dispute_minus_fake-tool"]["estimate"] == 1.0


def test_analysis_pairs_true_and_falsified_blocks():
    def r(cid, cond, t1, moa, truth="T", target="X"):
        return {"turn": 2, "status": "ok", "compound_id": cid, "seed": 0, "condition": cond, "turn1_moa": t1,
                "true_moa": truth, "moa": moa, "target_moa": target, "followed_target": moa == target,
                "correct": moa == truth, "flipped": moa != t1, "turn1_variant": "no_nsc"}
    fake = [r("a", "fake-tool", "W", "X"), r("b", "fake-tool", "W", "W"), r("c", "fake-tool", "T", "T"),
            r("a", "fake-dispute-senior", "W", "W"), r("b", "fake-dispute-junior", "W", "W"),
            r("c", "fake-share", "T", "X")]
    true = [r("a", "tool", "W", "T", target=None), r("b", "tool", "W", "T", target=None),
            r("z", "tool", "W", "T", target=None)]  # z is not an eligible cell
    res = mirror.analyse(fake, channel_recs=true)
    assert res["conditions"]["fake-tool"]["follow"]["k"] == 1 and res["conditions"]["fake-tool"]["follow"]["n"] == 3
    assert res["conditions"]["fake-share"]["right_to_wrong"]["k"] == 1
    tv = res["true_vs_fake"]["tool"]
    assert (tv["true_uptake"]["k"], tv["true_uptake"]["n"]) == (2, 2)
    assert (tv["fake_uptake"]["k"], tv["fake_uptake"]["n"]) == (1, 2)
    assert tv["true_minus_fake"]["estimate"] == 0.5


MIRROR = ROOT / "runs" / "mirror_muse-spark-1.3-contributor_no_nsc_20261114T123235-661520Z"
CHANNEL = ROOT / "runs" / "channel_muse-spark-1.3-contributor_no_nsc_20261114T083827-999243Z"
FULL = ROOT / "runs" / "full_muse-spark-1.3-contributor_both_20261113T201055-203204Z"


def _load(run):
    return [json.loads(x) for x in (run / "raw.jsonl").read_text(encoding="utf-8").splitlines() if x]


def test_mirror_numbers_in_the_report():
    """Locked to the committed mirror run: every number of Section 4.8."""
    res = mirror.analyse(_load(MIRROR), _load(CHANNEL), _load(FULL))
    assert "warning_targets" not in res
    assert (res["cells"], res["compounds"], res["turn1_wrong_cells"], res["unparsed"]) == (91, 31, 64, 6)
    kn = lambda r: (r["k"], r["n"])  # noqa: E731
    c = res["conditions"]
    assert [kn(c[k]["follow"]) for k in mirror.CONDITIONS] == [(76, 91), (84, 91), (43, 85), (39, 91)]
    assert [kn(c[k]["right_to_wrong"]) for k in mirror.CONDITIONS] == [(23, 27), (25, 27), (13, 25), (11, 27)]
    assert kn(res["objection_follow_same_cells"]) == (3, 546)
    assert kn(res["objection_follow_turn1_wrong"]) == (3, 384)
    assert kn(res["objection_right_to_wrong"]) == (0, 162)
    x = res["contrasts"]
    assert x["fake-tool_minus_objection"] == {"estimate": 0.83, "ci95": (0.725, 0.923)}
    assert x["fake-share_minus_objection"] == {"estimate": 0.918, "ci95": (0.844, 0.977)}
    assert x["fake-dispute_minus_fake-tool"] == {"estimate": -0.369, "ci95": (-0.485, -0.261)}
    tv = res["true_vs_fake"]
    assert [(kn(tv[k]["true_uptake"]), kn(tv[k]["fake_uptake"])) for k in ("tool", "share", "dispute")] == \
        [((50, 64), (53, 64)), ((56, 64), (59, 64)), ((57, 126), (58, 124))]
    assert [tv[k]["true_minus_fake"]["estimate"] for k in ("tool", "share", "dispute")] == [-0.047, -0.047, -0.015]
    assert [tv[k]["true_minus_fake"]["ci95"] for k in ("tool", "share", "dispute")] == \
        [(-0.191, 0.094), (-0.109, 0.016), (-0.16, 0.12)]


def test_mirror_every_changed_answer_names_the_false_class():
    recs = _load(MIRROR)
    t2 = [r for r in recs if r["turn"] == 2 and r["status"] != "skipped"]
    moved = [r for r in t2 if r.get("moa") and r["moa"] != r["turn1_moa"]]
    assert len(moved) == 76 + 84 + 43 + 39 and all(r["moa"] == r["target_moa"] for r in moved)
    unparsed = [r for r in t2 if not r.get("moa")]
    assert len(unparsed) == 6 and {(r["condition"], r["finish_reason"]) for r in unparsed} == \
        {("fake-dispute-senior", "length")}
    assert sum(r["status"] == "skipped" for r in recs) == 4 * 23


def test_mirror_post_hoc_spread_and_confidence():
    """Section 4.8 post-hoc counts: compounds moved per channel and mean confidence (locked to committed runs)."""
    t2 = [r for r in _load(MIRROR) if r["turn"] == 2 and r["status"] == "ok" and r.get("moa")]
    by = {}
    for r in t2:
        by.setdefault(r["condition"], {}).setdefault(r["compound_id"], []).append(r["followed_target"])
    moved = {k: sum(any(v) for v in d.values()) for k, d in by.items()}
    assert (moved["fake-tool"], moved["fake-share"], len(by["fake-tool"])) == (30, 31, 31)
    keys = {(r["compound_id"], r["seed"]) for r in t2}
    obj = [r for r in _load(FULL) if r["turn"] == 2 and r["turn1_variant"] == "no_nsc" and r["status"] == "ok"
           and r.get("moa") and r["condition"].endswith("_dir-misleading") and (r["compound_id"], r["seed"]) in keys]
    assert {r["compound_id"] for r in obj if r["followed_target"]} == {"s_bb3b52891e"}
    fol = [r["confidence"] for r in t2 if r["condition"] == "fake-tool" and r["followed_target"]]
    true = [r["confidence"] for r in _load(CHANNEL) if r["turn"] == 2 and r["status"] == "ok" and r.get("moa")
            and r["condition"] == "tool" and r["turn1_moa"] != r["true_moa"] and r["correct"]
            and (r["compound_id"], r["seed"]) in keys]
    assert round(sum(fol) / len(fol)) == 82 and round(sum(true) / len(true)) == 81
