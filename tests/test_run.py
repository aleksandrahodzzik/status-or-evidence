"""End-to-end with a fake API: schema, skipped cells, rerun at $0, kill switch mid-run."""

import json
from pathlib import Path

import yaml

from conftest import FakeTransport
from sor import run as runmod

REQUIRED = {"run_id", "timestamp", "model", "turn1_variant", "seed", "compound_id", "true_moa", "turn", "condition",
            "target_moa", "evidence_snippets", "messages", "raw_text", "moa", "confidence", "parse_status",
            "flipped", "correct", "tokens", "cost_usd", "cached", "status"}


def read_run(cfg):
    runs = sorted(Path(cfg["paths"]["runs"]).glob("*/raw.jsonl"), key=lambda p: p.stat().st_mtime)
    p = runs[-1]
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()], \
        json.loads((p.parent / "meta.json").read_text(encoding="utf-8"))


def test_no_yes_sends_nothing(cfg, cfg_file):
    fake = FakeTransport()
    assert runmod.main(["pilot", "--config", cfg_file], transport=fake) == 0
    assert fake.calls == [] and not Path(cfg["paths"]["runs"]).exists()


def test_dryrun_end_to_end_and_rerun_free(cfg, cfg_file, compounds):
    fake = FakeTransport("Microtubule stabilizers")
    assert runmod.main(["dryrun", "--turn1-variant", "no_nsc", "--yes", "--config", cfg_file], transport=fake) == 0
    recs, meta = read_run(cfg)
    assert meta["status"] == "done"
    truth = {c["compound_id"]: c["true_moa"] for c in compounds}
    t1 = [r for r in recs if r["turn"] == 1]
    assert len(t1) == 3
    for r in t1:
        assert REQUIRED <= set(r) and r["targets"]["misleading_target"] not in (r["true_moa"], r["turn1_moa"])
    for r in recs:
        if r["status"] != "skipped":
            assert REQUIRED <= set(r)
    for r in t1:
        t2 = [x for x in recs if x["turn"] == 2 and x["compound_id"] == r["compound_id"]]
        ran = [x for x in t2 if x["status"] != "skipped"]
        skipped = [x for x in t2 if x["status"] == "skipped"]
        if r["turn1_moa"] == truth[r["compound_id"]]:
            assert len(ran) == 7 and len(skipped) == 6
            assert all(x["skip_reason"] == "N/A: turn-1 already correct" for x in skipped)
            assert all("dir-correct" in x["condition"] for x in skipped)
        else:
            assert len(ran) == 13 and not skipped
        for x in ran:
            assert x["messages"][2]["content"] == r["raw_text"]  # the model's actual turn-1 answer
            if x["condition"] != "control":
                assert x["followed_target"] is True and x["flipped"] is True  # the fake always follows
            else:
                assert x["flipped"] is False
    n_calls = len(fake.calls)
    ledger = Path(cfg["paths"]["ledger"]).read_text(encoding="utf-8")
    assert runmod.main(["dryrun", "--turn1-variant", "no_nsc", "--config", cfg_file], transport=fake) == 0
    assert len(fake.calls) == n_calls  # rerun: all cached, no --yes needed, $0
    assert Path(cfg["paths"]["ledger"]).read_text(encoding="utf-8") == ledger
    recs2, meta2 = read_run(cfg)
    assert meta2["cost_usd_this_run"] == 0 and all(r.get("cached") or r["status"] == "skipped" for r in recs2)


def test_dryrun_includes_wrong_compound(cfg, client_factory, compounds):
    chosen, _ = runmod.choose_dryrun(compounds, client_factory(FakeTransport()), "muse-spark-1.3-contributor",
                                     ["with_nsc"], 0.7)
    assert len(chosen) == 3 and any(not c["source_first_correct"] for c in chosen)


def test_kill_switch_stops_run_cleanly(cfg, tmp_path):
    cfg["models"]["primary"]["price_in_per_m"] = 1000.0  # fake usage 1000 in-tokens -> $1/call; 38 calls > $18 cap
    cfg_file = tmp_path / "cfg_expensive.yaml"
    cfg_file.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    fake = FakeTransport()
    code = runmod.main(["pilot", "--turn1-variant", "with_nsc", "--yes", "--config", str(cfg_file)], transport=fake)
    assert code == 2
    recs, meta = read_run(cfg)
    assert meta["status"].startswith("stopped") and "kill switch" in meta["status"]
    ledger = [json.loads(x) for x in Path(cfg["paths"]["ledger"]).read_text(encoding="utf-8").splitlines()]
    assert sum(x["cost_usd"] for x in ledger) <= cfg["budget_cap_usd"]
    assert len(recs) == len(fake.calls) == len(ledger) < 38


def test_max_spend_stops_run_below_cap(cfg, tmp_path):
    cfg["models"]["primary"]["price_in_per_m"] = 1000.0  # $1/call
    cfg_file = tmp_path / "cfg_expensive.yaml"
    cfg_file.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    fake = FakeTransport()
    code = runmod.main(["pilot", "--turn1-variant", "with_nsc", "--max-spend", "10", "--yes", "--config",
                        str(cfg_file)], transport=fake)
    assert code == 2
    ledger = [json.loads(x) for x in Path(cfg["paths"]["ledger"]).read_text(encoding="utf-8").splitlines()]
    assert 0 < len(ledger) < 38 and sum(x["cost_usd"] for x in ledger) <= 10
