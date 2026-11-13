"""Stub analysis: flip rate per condition (and per turn-1 variant) for one run.

    python -m sor.analyze [runs/<run_id>]     # default: latest run with turn-2 records
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from sor.config import ROOT
from sor.prompts import CONDITIONS


def latest_run() -> Path | None:
    runs = sorted((p for p in (ROOT / "runs").glob("*/raw.jsonl") if p.parent.name != "wild"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for p in runs:
        if any(json.loads(line).get("turn") == 2 for line in p.read_text(encoding="utf-8").splitlines()):
            return p.parent
    return runs[0].parent if runs else None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    run = Path(argv[0]) if argv else latest_run()
    if run is None:
        print("no runs yet")
        return 0
    recs = [json.loads(line) for line in (run / "raw.jsonl").read_text(encoding="utf-8").splitlines() if line]
    t1 = [r for r in recs if r["turn"] == 1]
    print(f"run {run.name}: {len(recs)} records")
    for v in sorted({r["turn1_variant"] for r in t1}):
        rs = [r for r in t1 if r["turn1_variant"] == v]
        parsed = [r for r in rs if r.get("moa")]
        print(f"  turn 1 [{v}]: {len(rs)} calls, parsed {len(parsed)}, correct "
              f"{sum(r['correct'] for r in parsed)}/{len(parsed)}, wrong {sum(not r['correct'] for r in parsed)}, "
              f"unparsed/error {len(rs) - len(parsed)}")
    t2 = [r for r in recs if r["turn"] == 2]
    if not t2:
        return 0
    print(f"\n  {'variant':9} {'condition':38} {'run':>4} {'skip':>5} {'parsed':>6} {'flip':>5} {'rate':>6} "
          f"{'->target':>8}")
    cells = defaultdict(list)
    for r in t2:
        cells[(r["turn1_variant"], r["condition"])].append(r)
    for v in sorted({r["turn1_variant"] for r in t2}):
        for cond in CONDITIONS:
            rs = cells.get((v, cond), [])
            ran = [r for r in rs if r["status"] != "skipped"]
            parsed = [r for r in ran if r.get("flipped") is not None]
            flips = sum(r["flipped"] for r in parsed)
            followed = sum(bool(r.get("followed_target")) for r in parsed)
            rate = f"{flips / len(parsed):.2f}" if parsed else "-"
            print(f"  {v:9} {cond:38} {len(ran):4} {len(rs) - len(ran):5} {len(parsed):6} {flips:5} {rate:>6} "
                  f"{followed if cond != 'control' else '-':>8}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
