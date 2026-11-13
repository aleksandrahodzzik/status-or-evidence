"""Step 0 inventory: index rows vs transcripts available under MuseCell (read-only).

Usage: python tools/inventory.py  -> prints coverage tables, writes docs/inventory.json
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

MUSECELL = Path(r"C:\Users\Oleksandra\OneDrive\Desktop\MuseCell")
TRANSCRIPT_DIRS = [MUSECELL / "runs" / "eval", MUSECELL / "runs" / "eval_open_world", MUSECELL / "runs",
                   MUSECELL / "demo" / "runs"]
INDEX_FILES = [MUSECELL / "eval" / "agent_runs.jsonl", MUSECELL / "eval" / "open_world_runs.jsonl"]
OUT = Path(__file__).resolve().parents[1] / "docs" / "inventory.json"


def agent_version(row: dict) -> str:
    return row.get("models", {}).get("agent") or "v1-v4 (no agent field)"


def main() -> None:
    transcripts: dict[str, list[Path]] = defaultdict(list)
    for d in TRANSCRIPT_DIRS:
        for p in sorted(d.glob("run_*.jsonl")):
            transcripts[p.stem].append(p)

    rows = []
    for f in INDEX_FILES:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                r["_index"] = f.name
                rows.append(r)

    cov: dict[tuple, Counter] = defaultdict(Counter)
    compounds_with = defaultdict(set)
    for r in rows:
        key = (r["_index"], agent_version(r), r["models"]["scientist"], r.get("budget"))
        has = r["run_id"] in transcripts
        cov[key]["rows"] += 1
        cov[key]["with_transcript"] += has
        cov[key]["finished"] += r.get("status") == "finished"
        if has and r.get("status") == "finished":
            compounds_with["any"].add(r["compound"])
            compounds_with[(agent_version(r), r["models"]["scientist"])].add(r["compound"])

    print(f"transcript files: {sum(len(v) for v in transcripts.values())}, unique run ids: {len(transcripts)}")
    indexed = {r["run_id"] for r in rows}
    orphans = sorted(set(transcripts) - indexed)
    print(f"index rows: {len(rows)}, unique run ids: {len(indexed)}, transcripts not in any index: {len(orphans)}")
    print(f"\n{'index':24} {'agent':24} {'scientist':28} {'budget':>6} {'rows':>5} {'trans':>5} {'fin':>5}")
    table = []
    for key in sorted(cov, key=lambda k: tuple(str(x) for x in k)):
        c = cov[key]
        print(f"{key[0]:24} {key[1]:24} {key[2]:28} {str(key[3]):>6} {c['rows']:5} {c['with_transcript']:5} "
              f"{c['finished']:5}")
        table.append({"index": key[0], "agent": key[1], "scientist": key[2], "budget": key[3], **c})
    all_compounds = sorted({r["compound"] for r in rows})
    print(f"\ncompounds in index: {len(all_compounds)}; with >=1 finished transcript: {len(compounds_with['any'])}")
    per_group = {f"{k[0]} | {k[1]}": len(v) for k, v in compounds_with.items() if k != "any"}
    for k, v in sorted(per_group.items()):
        print(f"  {k}: {v} compounds")
    moas = sorted({r["truth_moa"] for r in rows})
    print(f"\nMoA classes ({len(moas)}): {moas}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"coverage": table, "orphans": orphans, "compounds_with_transcript":
                               len(compounds_with["any"]), "per_group_compounds": per_group, "moas": moas,
                               "n_compounds": len(all_compounds)}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
