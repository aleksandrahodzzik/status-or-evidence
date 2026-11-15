"""Exploratory (NOT pre-registered) analysis of the mirror run, $0: could the model have known the block was false?

Uses only existing records (the mirror run's turn-1 and turn-2 records) and the compound data. Four questions:

(a) Conflict with its own answer: on cells whose turn-1 answer was correct, does adoption of the false class depend
    on turn-1 confidence (median split)?
(b) Did it register the conflict? Confidence turn 1 -> turn 2 for adoptions in conflict cells (turn 1 correct) vs
    non-conflict cells (turn 1 wrong); cluster bootstrap over compounds of the difference in mean change.
(c) Phenotype margin: margin = ||profile - centroid(false class)|| - ||profile - centroid(true class)||, Euclidean
    over the 24 robust-z features, profile = the compound's median z over its acquired wells, centroids = the
    leave-one-compound-out per-MoA medians of sor.targets.centroids. Positive = the compound's own phenotype is
    closer to the truth. Adoption by margin tercile.
(d) Crude rationale check: share of adoptions whose rationale contains a conflict keyword.

    python -m sor.explore_mirror runs/<mirror run>
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from sor.analyze import cluster_boot, load, rate
from sor.load import FEATURES, load_compounds
from sor.targets import centroids

DATA = ("fake-tool", "fake-share")
CONFLICT_WORDS = ("despite", "conflict", "inconsist", "although", "however", "contradict", "but")
_CONFLICT_RE = re.compile(r"\b(" + "|".join(CONFLICT_WORDS) + r")", re.IGNORECASE)


def phenotype_margin(profile: dict[str, float], false_centroid: dict[str, float], true_centroid: dict[str, float],
                     features=FEATURES) -> float:
    """Distance to the false-class centroid minus distance to the true-class centroid (positive favours truth)."""
    d = lambda c: math.sqrt(sum((profile[f] - c[f]) ** 2 for f in features))  # noqa: E731
    return d(false_centroid) - d(true_centroid)


def mentions_conflict(text: str | None) -> bool:
    return bool(text) and bool(_CONFLICT_RE.search(text))


def _mean(xs):
    return round(float(np.mean(xs)), 1) if xs else None


def analyse(recs: list[dict], compounds: list[dict]) -> dict:
    by_id = {c["compound_id"]: c for c in compounds}
    t1 = {(r["compound_id"], r["seed"]): r for r in recs if r["turn"] == 1 and r["status"] == "ok" and r.get("moa")}
    t2 = [r for r in recs if r["turn"] == 2 and r["status"] == "ok" and r.get("moa")]
    for r in t2:
        r1 = t1[(r["compound_id"], r["seed"])]
        r["_conf1"], r["_conf2"] = r1["confidence"], r["confidence"]
        r["_right1"] = r["turn1_moa"] == r["true_moa"]
        c = by_id[r["compound_id"]]
        cent = centroids(c["compound_name"])
        r["_margin"] = phenotype_margin(c["profile_median_z"], cent[r["target_moa"]], cent[r["true_moa"]])
    adopt = lambda r: r["followed_target"]  # noqa: E731
    out = {"label": "exploratory, not pre-registered", "conditions": list(DATA)}

    # (a) correct turn-1 answers: adoption by turn-1 confidence, median split.
    right_cells = {k: v for k, v in t1.items() if v["moa"] == v["true_moa"]
                   and any(r["compound_id"] == k[0] and r["seed"] == k[1] for r in t2)}
    confs = sorted(v["confidence"] for v in right_cells.values())
    med = float(np.median(confs))
    a = {"n_cells": len(right_cells), "turn1_confidence": {"median": med, "min": confs[0], "max": confs[-1],
                                                           "mean": _mean(confs)},
         "split": "low = turn-1 confidence <= median, high = > median"}
    for cond in DATA:
        rs = [r for r in t2 if r["condition"] == cond and r["_right1"]]
        a[cond] = {"low": rate([r for r in rs if r["_conf1"] <= med], adopt),
                   "high": rate([r for r in rs if r["_conf1"] > med], adopt),
                   "turn1_conf_adopted": _mean([r["_conf1"] for r in rs if adopt(r)]),
                   "turn1_conf_kept": _mean([r["_conf1"] for r in rs if not adopt(r)])}
    out["a_conflict_by_turn1_confidence"] = a

    # (b) confidence change among adoptions, conflict vs non-conflict.
    b = {}
    for name, conds in (("fake-tool", ("fake-tool",)), ("fake-share", ("fake-share",)), ("data_pooled", DATA)):
        rs = [r for r in t2 if r["condition"] in conds and adopt(r)]
        grp = {"conflict": [r for r in rs if r["_right1"]], "non_conflict": [r for r in rs if not r["_right1"]]}
        res = {g: {"n": len(x), "conf_turn1": _mean([r["_conf1"] for r in x]),
                   "conf_turn2": _mean([r["_conf2"] for r in x]),
                   "change": _mean([r["_conf2"] - r["_conf1"] for r in x])} for g, x in grp.items()}
        by = defaultdict(list)
        for r in rs:
            by[r["compound_id"]].append(r)

        def stat(sample, key):
            c = [key(r) for r in sample if r["_right1"]]
            n = [key(r) for r in sample if not r["_right1"]]
            return float(np.mean(c) - np.mean(n)) if c and n else None
        res["conflict_minus_non_conflict_change"] = cluster_boot(by, lambda s: stat(s, lambda r: r["_conf2"] - r["_conf1"]))
        res["conflict_minus_non_conflict_turn2_conf"] = cluster_boot(by, lambda s: stat(s, lambda r: r["_conf2"]))
        b[name] = res
    out["b_confidence_change_adoptions"] = b

    # (c) phenotype margin terciles (cells, i.e. one margin per compound x seed).
    cell_margin = {(r["compound_id"], r["seed"]): r["_margin"] for r in t2}
    m = np.array(sorted(cell_margin.values()))
    q1, q2 = (float(x) for x in np.quantile(m, [1 / 3, 2 / 3]))
    tert = lambda x: "low" if x <= q1 else ("mid" if x <= q2 else "high")  # noqa: E731
    c_out = {"n_cells": len(cell_margin), "cut_points": [round(q1, 2), round(q2, 2)],
             "share_cells_margin_positive": rate(list(cell_margin.values()), lambda x: x > 0),
             "margin_range": [round(float(m[0]), 2), round(float(m[-1]), 2)]}
    for cond in DATA:
        rs = [r for r in t2 if r["condition"] == cond]
        c_out[cond] = {t: rate([r for r in rs if tert(r["_margin"]) == t], adopt) for t in ("low", "mid", "high")}
        c_out[cond]["high_turn1_right"] = rate([r for r in rs if tert(r["_margin"]) == "high" and r["_right1"]], adopt)
    out["c_phenotype_margin"] = c_out

    # (d) rationale keywords, fake-tool adoptions.
    rs = [r for r in t2 if r["condition"] == "fake-tool" and adopt(r)]
    out["d_rationale_conflict_keywords"] = {
        "keywords": list(CONFLICT_WORDS), "note": "crude keyword match on the rationale field",
        "fake-tool_adoptions": rate(rs, lambda r: mentions_conflict(r.get("rationale"))),
        "conflict_cells": rate([r for r in rs if r["_right1"]], lambda r: mentions_conflict(r.get("rationale"))),
        "non_conflict_cells": rate([r for r in rs if not r["_right1"]],
                                   lambda r: mentions_conflict(r.get("rationale"))),
    }
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    run = Path(argv[0])
    res = analyse(load(run), load_compounds())
    res["run"] = run.name
    (run / "analysis_exploratory.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
