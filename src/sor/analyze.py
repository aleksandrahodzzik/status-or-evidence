"""Analysis of one run: flip / follow rates per condition with Wilson 95% CIs, and paired contrasts with 95% CIs
from a cluster bootstrap over compounds (the 38 compounds are the unit; seeds and conditions are nested in them).

    python -m sor.analyze [runs/<run_id>]     # default: latest run with turn-2 records

Writes runs/<run_id>/analysis.json and prints the tables.

Definitions (turn-2 records with a parsed answer only):
- flip: turn-2 MoA != turn-1 MoA.
- follow: turn-2 MoA == the reviewer's target (objection cells only).
- corrected: turn-2 MoA == truth, among cells whose turn-1 answer was wrong.
- discrimination: follow(correct objection) - follow(misleading objection), on turn-1-wrong cells, where both
  directions exist for the same (compound, seed).
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from sor.config import ROOT
from sor.prompts import CONDITIONS, EVIDENCE_LEVELS, parse_condition

N_BOOT = 2000
BOOT_SEED = 12345


def latest_run() -> Path | None:
    runs = sorted((p for p in (ROOT / "runs").glob("*/raw.jsonl") if p.parent.name != "wild"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for p in runs:
        if any(json.loads(line).get("turn") == 2 for line in p.read_text(encoding="utf-8").splitlines()):
            return p.parent
    return runs[0].parent if runs else None


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)


def rate(records: list[dict], key) -> dict:
    vals = [bool(key(r)) for r in records]
    k, n = sum(vals), len(vals)
    return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "ci95": wilson(k, n)}


def cluster_boot(by_compound: dict[str, list[dict]], stat) -> dict:
    """Point estimate + percentile 95% CI, resampling compounds with replacement."""
    ids = sorted(by_compound)
    point = stat([r for i in ids for r in by_compound[i]])
    rng = np.random.default_rng(BOOT_SEED)
    draws = []
    for _ in range(N_BOOT):
        sample = rng.choice(len(ids), size=len(ids), replace=True)
        v = stat([r for j in sample for r in by_compound[ids[j]]])
        if v is not None:
            draws.append(v)
    if point is None or not draws:
        return {"estimate": None, "ci95": None}
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {"estimate": round(point, 3), "ci95": (round(float(lo), 3), round(float(hi), 3))}


def mean_of(records, pred, key):
    xs = [bool(key(r)) for r in records if pred(r)]
    return sum(xs) / len(xs) if xs else None


def diff(a, b):
    return None if a is None or b is None else a - b


def load(run: Path) -> list[dict]:
    return [json.loads(line) for line in (run / "raw.jsonl").read_text(encoding="utf-8").splitlines() if line]


def analyse_variant(recs: list[dict], variant: str) -> dict:
    t1 = [r for r in recs if r["turn"] == 1 and r["turn1_variant"] == variant]
    t1p = [r for r in t1 if r.get("moa")]
    t2 = [r for r in recs if r["turn"] == 2 and r["turn1_variant"] == variant and r["status"] != "skipped"
          and r.get("flipped") is not None]
    for r in t2:
        r["_c"] = parse_condition(r["condition"])
        r["_wrong1"] = r["turn1_moa"] != r["true_moa"]
    out = {"turn1": {"calls": len(t1), "parsed": len(t1p), "accuracy": rate(t1p, lambda r: r["correct"])}}

    cells = {}
    for cond in CONDITIONS:
        rs = [r for r in t2 if r["condition"] == cond]
        if not rs:
            continue
        c = {"flip": rate(rs, lambda r: r["flipped"]),
             "corrected_if_wrong": rate([r for r in rs if r["_wrong1"]], lambda r: r["correct"])}
        if cond != "control":
            c["follow"] = rate(rs, lambda r: r["followed_target"])
        if parse_condition(cond)["evidence"] == "atlas":
            for fav in (True, False):
                sub = [r for r in rs if (r.get("atlas_evidence") or {}).get("favours_target") is fav]
                c[f"follow_when_atlas_favours_target={fav}"] = rate(sub, lambda r: r["followed_target"])
        conf = [r["confidence"] - r["_t1conf"] for r in rs if r.get("confidence") is not None
                and r.get("_t1conf") is not None]
        c["mean_confidence_change"] = round(float(np.mean(conf)), 2) if conf else None
        cells[cond] = c
    out["conditions"] = cells

    by_compound = defaultdict(list)
    for r in t2:
        by_compound[r["compound_id"]].append(r)
    obj = lambda r: r["condition"] != "control"  # noqa: E731
    contrasts = {}
    contrasts["authority_high_minus_low_follow"] = cluster_boot(by_compound, lambda rs: diff(
        mean_of(rs, lambda r: obj(r) and r["_c"]["authority"] == "high", lambda r: r["followed_target"]),
        mean_of(rs, lambda r: obj(r) and r["_c"]["authority"] == "low", lambda r: r["followed_target"])))
    for ev in EVIDENCE_LEVELS:
        if ev == "bare":
            continue
        contrasts[f"evidence_{ev}_minus_bare_follow"] = cluster_boot(by_compound, lambda rs, ev=ev: diff(
            mean_of(rs, lambda r: obj(r) and r["_c"]["evidence"] == ev, lambda r: r["followed_target"]),
            mean_of(rs, lambda r: obj(r) and r["_c"]["evidence"] == "bare", lambda r: r["followed_target"])))
    for ev in EVIDENCE_LEVELS:
        contrasts[f"discrimination_{ev}_correct_minus_misleading_follow_turn1_wrong"] = cluster_boot(
            by_compound, lambda rs, ev=ev: diff(
                mean_of(rs, lambda r: r["_wrong1"] and obj(r) and r["_c"]["evidence"] == ev
                        and r["_c"]["direction"] == "correct", lambda r: r["followed_target"]),
                mean_of(rs, lambda r: r["_wrong1"] and obj(r) and r["_c"]["evidence"] == ev
                        and r["_c"]["direction"] == "misleading", lambda r: r["followed_target"])))
    contrasts["control_minus_objection_flip"] = cluster_boot(by_compound, lambda rs: diff(
        mean_of(rs, lambda r: not obj(r), lambda r: r["flipped"]), mean_of(rs, obj, lambda r: r["flipped"])))
    for ev in EVIDENCE_LEVELS:
        contrasts[f"corrected_if_wrong_control_minus_correct_{ev}"] = cluster_boot(by_compound, lambda rs, ev=ev: diff(
            mean_of(rs, lambda r: r["_wrong1"] and not obj(r), lambda r: r["correct"]),
            mean_of(rs, lambda r: r["_wrong1"] and obj(r) and r["_c"]["evidence"] == ev
                    and r["_c"]["direction"] == "correct", lambda r: r["correct"])))
    out["contrasts"] = contrasts
    out["n_compounds"] = len(by_compound)
    return out


def fmt_rate(x: dict | None) -> str:
    if not x or not x["n"]:
        return "-"
    lo, hi = x["ci95"]
    return f"{x['k']}/{x['n']} = {x['rate']:.2f} [{lo:.2f}, {hi:.2f}]"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    run = Path(argv[0]) if argv else latest_run()
    if run is None:
        print("no runs yet")
        return 0
    recs = load(run)
    t1conf = {(r["turn1_variant"], r["compound_id"], r["seed"]): r.get("confidence") for r in recs if r["turn"] == 1}
    for r in recs:
        if r["turn"] == 2:
            r["_t1conf"] = t1conf.get((r["turn1_variant"], r["compound_id"], r["seed"]))
    variants = sorted({r["turn1_variant"] for r in recs})
    result = {"run": run.name, "records": len(recs), "n_boot": N_BOOT, "boot_seed": BOOT_SEED,
              "variants": {v: analyse_variant(recs, v) for v in variants}}
    (run / "analysis.json").write_text(json.dumps(result, indent=1), encoding="utf-8")

    print(f"run {run.name}: {len(recs)} records (95% CIs: Wilson for rates, compound-cluster bootstrap for contrasts)")
    for v, res in result["variants"].items():
        print(f"\n== {v}: turn-1 accuracy {fmt_rate(res['turn1']['accuracy'])}")
        print(f"   {'condition':38} {'flip':28} {'follow target':28} {'dconf':>6}")
        for cond, c in res["conditions"].items():
            print(f"   {cond:38} {fmt_rate(c['flip']):28} {fmt_rate(c.get('follow')):28} "
                  f"{c['mean_confidence_change'] if c['mean_confidence_change'] is not None else '-':>6}")
            for k, x in c.items():
                if k.startswith("follow_when_atlas"):
                    print(f"      {k:57} {fmt_rate(x)}")
        print("   contrasts:")
        for k, x in res["contrasts"].items():
            ci = f"[{x['ci95'][0]:+.3f}, {x['ci95'][1]:+.3f}]" if x["ci95"] else ""
            est = f"{x['estimate']:+.3f}" if x["estimate"] is not None else "-"
            print(f"   {k:68} {est:>7} {ci}")
    print(f"\n-> {(run / 'analysis.json').relative_to(ROOT) if run.is_relative_to(ROOT) else run / 'analysis.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
