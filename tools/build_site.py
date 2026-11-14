"""Build the interactive results site: site/data.js from the committed runs (no API calls).

    .venv\\Scripts\\python.exe tools/build_site.py

site/explorer.html is hand-written and reads window.SOR_DATA from site/data.js, so it opens from disk (file://).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = {
    "contributor": ROOT / "runs" / "full_muse-spark-1.3-contributor_both_20261113T201055-203204Z",
    "spark13": ROOT / "runs" / "full_muse-spark-1.3_with_nsc_20261113T204207-234323Z",
}
FOLLOWUP = ROOT / "runs" / "channel_muse-spark-1.3-contributor_no_nsc_20261114T083827-999243Z"
MODEL_LABEL = {"contributor": "muse-spark-1.3-contributor", "spark13": "muse-spark-1.3"}
REVIEWER_RE = re.compile(r'^Reviewer comment from (.+?):\n"(.*)"\n\nGive your answer again\.', re.S)


def evidence_of(turn1_user: str) -> str:
    body = turn1_user.split("Evidence from the blinded screen:\n\n", 1)[1]
    return body.split("\n\nAllowed MoA classes", 1)[0]


def compact(r: dict) -> dict:
    out = {"v": r["turn1_variant"], "c": r["compound_id"], "s": r["seed"], "k": r["condition"],
           "moa": r.get("moa"), "conf": r.get("confidence"), "why": r.get("rationale"), "ok": r.get("correct")}
    if r["turn"] == 2:
        m = REVIEWER_RE.match(r["messages"][-1]["content"])
        out.update({"t1": r.get("turn1_moa"), "tgt": r.get("target_moa"), "flip": r.get("flipped"),
                    "fol": r.get("followed_target"), "who": m.group(1) if m else None,
                    "say": m.group(2) if m else r["messages"][-1]["content"], "atlas": r.get("atlas_evidence")})
    return out


def build_model(key: str, run: Path) -> dict:
    recs = [json.loads(line) for line in (run / "raw.jsonl").read_text(encoding="utf-8").splitlines() if line]
    evidence, turn1, turn2 = {}, [], []
    for r in recs:
        if r["status"] == "skipped":
            continue
        if r["turn"] == 1:
            evidence.setdefault(f"{r['compound_id']}|{r['turn1_variant']}", evidence_of(r["messages"][1]["content"]))
            turn1.append(compact(r))
        else:
            turn2.append(compact(r))
    analysis = json.loads((run / "analysis.json").read_text(encoding="utf-8"))
    truth = {r["compound_id"]: r["true_moa"] for r in recs}
    return {"label": MODEL_LABEL[key], "run": run.name, "truth": truth, "evidence": evidence, "turn1": turn1,
            "turn2": turn2, "analysis": analysis}


def add_followup(model: dict, run: Path) -> None:
    """Follow-up turn-2 answers join the primary run's no-atlas turn-1 answers, which they reuse from the cache."""
    t1 = {(r["v"], r["c"], r["s"]): r for r in model["turn1"]}
    n = 0
    for line in (run / "raw.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line) if line else None
        if not r or r["turn"] != 2 or r["status"] == "skipped":
            continue
        first = t1[(r["turn1_variant"], r["compound_id"], r["seed"])]
        if first["moa"] != r["turn1_moa"]:
            raise SystemExit(f"follow-up turn 1 differs from the primary run: {r['compound_id']} seed {r['seed']}")
        c = compact(r)
        c["k"] = "followup-" + r["condition"]
        model["turn2"].append(c)
        n += 1
    analysis = json.loads((run / "analysis.json").read_text(encoding="utf-8"))
    model["followup"] = {"run": run.name, "n": n, "turn1_data_correct": analysis["turn1_data_correct"],
                         "conditions": {k: v["primary_correct"] for k, v in analysis["conditions"].items()},
                         "contrasts": analysis["contrasts"]}


def main() -> int:
    data = {k: build_model(k, run) for k, run in RUNS.items()}
    add_followup(data["contributor"], FOLLOWUP)
    out = ROOT / "site" / "data.js"
    out.parent.mkdir(exist_ok=True)
    out.write_text("window.SOR_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    n = sum(len(d["turn1"]) + len(d["turn2"]) for d in data.values())
    print(f"-> {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB, {n} answers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
