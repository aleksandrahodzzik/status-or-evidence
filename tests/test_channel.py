"""Follow-up experiment (sor.channel): identical atlas text across messengers, no leakage, fake-API end to end."""

import json
import re
from pathlib import Path

import pandas as pd
import yaml

from conftest import FakeTransport
from sor import channel
from sor import run as runmod
from sor.config import ROOT
from sor.load import evidence_text
from sor.prompts import AUTHORITY


def test_every_compound_has_the_with_nsc_atlas_block(compounds):
    for c in compounds:
        parts = [b["text"] for b in c["evidence_blocks"] if b["kind"] == "atlas"]
        assert parts and channel.atlas_block(c) == "\n\n".join(parts)
        assert all(p in evidence_text(c, "with_nsc") and p not in evidence_text(c, "no_nsc") for p in parts)


def test_same_block_through_every_messenger(compounds):
    c = compounds[0]
    block = channel.atlas_block(c)
    msgs = {k: channel.message(k, block, c["true_moa"]) for k in channel.CONDITIONS}
    for m in msgs.values():
        assert m.count(block) == 1
    assert "Reviewer" not in msgs["tool"] and "I think the MoA" not in msgs["tool"]
    assert AUTHORITY["high"] in msgs["share"] and "I think the MoA" not in msgs["share"]
    assert AUTHORITY["high"] in msgs["dispute-high"] and AUTHORITY["low"] in msgs["dispute-low"]
    for k in ("dispute-high", "dispute-low"):
        assert f"I think the MoA is {c['true_moa']}." in msgs[k]
    stripped = {k: m.replace(block, "") for k, m in msgs.items()}
    assert stripped["dispute-high"].replace(AUTHORITY["high"], AUTHORITY["low"]) == stripped["dispute-low"]


def test_no_compound_names_in_messages(compounds):
    names = pd.read_csv(ROOT / "data" / "raw" / "metadata" / "BBBC021_v1_compound.csv").compound.dropna()
    names = sorted({n for n in names if n.lower() not in ("dmso", "unknown")}, key=len, reverse=True)
    pat = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in names) + r")(?![\w-])", re.I)
    for c in compounds:
        block = channel.atlas_block(c)
        for k in channel.CONDITIONS:
            assert not pat.search(channel.message(k, block, c["true_moa"])), (c["compound_id"], k)


def _seed0(cfg, tmp_path):
    cfg = {**cfg, "seeds": [0]}
    p = tmp_path / "config_seed0.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return cfg, str(p)


def test_needs_cached_turn1_and_yes(cfg, tmp_path):
    cfg, f = _seed0(cfg, tmp_path)
    fake = FakeTransport()
    assert channel.main(["--config", f], transport=fake) == 1  # turn 1 not cached: refuses
    assert fake.calls == []
    assert runmod.main(["pilot", "--turn1-variant", "no_nsc", "--yes", "--config", f], transport=fake) == 0
    n = len(fake.calls)
    assert channel.main(["--config", f], transport=fake) == 0  # no --yes: plan only
    assert len(fake.calls) == n


def test_end_to_end_with_fake_api(cfg, tmp_path, compounds):
    cfg, f = _seed0(cfg, tmp_path)
    fake = FakeTransport("Microtubule stabilizers")
    assert runmod.main(["pilot", "--turn1-variant", "no_nsc", "--yes", "--config", f], transport=fake) == 0
    n_pilot = len(fake.calls)
    assert channel.main(["--yes", "--config", f], transport=fake) == 0
    assert len(fake.calls) - n_pilot == sum(2 if c["true_moa"] == "Microtubule stabilizers" else 4
                                            for c in compounds)  # turn 1 served from cache
    run = sorted(Path(cfg["paths"]["runs"]).glob("channel_*/raw.jsonl"))[-1]
    recs = [json.loads(x) for x in run.read_text(encoding="utf-8").splitlines()]
    t2 = [r for r in recs if r["turn"] == 2 and r["status"] != "skipped"]
    for r in t2:
        t1 = next(x for x in recs if x["turn"] == 1 and x["compound_id"] == r["compound_id"])
        assert r["messages"][2]["content"] == t1["raw_text"]
        if r["condition"].startswith("dispute"):
            assert r["target_moa"] == r["true_moa"] and r["correct"] is True  # the fake follows
        else:
            assert r["target_moa"] is None and r["flipped"] is False
    res = channel.analyse(recs)
    assert res["conditions"]["dispute-high"]["turn1_wrong_correct"]["rate"] == 1.0
    assert res["conditions"]["tool"]["turn1_wrong_correct"]["rate"] == 0.0
