"""Report figures from analysis.json files.

    python -m sor.figures runs/<primary run> [runs/<secondary run>]

Writes docs/figures/*.png.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from sor.config import ROOT  # noqa: E402

OUT = ROOT / "docs" / "figures"
EV_LABEL = {"bare": "bare", "evidence": "3 z", "atlas": "atlas"}
VAR_LABEL = {"with_nsc": "turn 1 with atlas", "no_nsc": "turn 1 without atlas"}


def _bar(ax, x, r, color, label=None, hatch=None):
    if not r or not r["n"]:
        return
    lo, hi = r["ci95"]
    ax.bar(x, r["rate"] * 100, width=0.38, color=color, label=label, hatch=hatch, edgecolor="black", linewidth=0.5)
    ax.errorbar(x, r["rate"] * 100, yerr=[[r["rate"] * 100 - lo * 100], [hi * 100 - r["rate"] * 100]],
                fmt="none", ecolor="black", capsize=2, linewidth=0.8)


def fig_follow(an: dict, name: str) -> Path:
    variants = [v for v in ("with_nsc", "no_nsc") if v in an["variants"]]
    fig, axes = plt.subplots(1, len(variants), figsize=(6 * len(variants), 3.8), sharey=True, squeeze=False)
    for ax, v in zip(axes[0], variants):
        conds = an["variants"][v]["conditions"]
        labels, x = [], 0
        for ev in ("bare", "evidence", "atlas"):
            for a in ("high", "low"):
                for d, col in (("correct", "#2b8a3e"), ("misleading", "#c92a2a")):
                    r = conds.get(f"auth-{a}_ev-{ev}_dir-{d}", {}).get("follow")
                    _bar(ax, x + (0 if d == "correct" else 0.4), r, col,
                         label=f"{d} objection followed" if (ev, a) == ("bare", "high") else None,
                         hatch=None if a == "high" else "//")
                labels.append((x + 0.2, f"{EV_LABEL[ev]}\n{'PI' if a == 'high' else 'junior'}"))
                x += 1
        ctrl = conds["control"]["flip"]
        _bar(ax, x + 0.2, ctrl, "#868e96", label="control: answer changed")
        labels.append((x + 0.2, "control"))
        ax.set_xticks([p for p, _ in labels], [t for _, t in labels], fontsize=8)
        ax.set_title(VAR_LABEL[v], fontsize=10)
        top = max([c[k]["ci95"][1] for c in conds.values() for k in ("flip", "follow") if c.get(k) and c[k]["n"]])
        ax.set_ylim(0, max(25, 5 * math.ceil(top * 100 / 5)))
        ax.grid(axis="y", alpha=0.3)
    axes[0][0].set_ylabel("% of turn-2 answers (95% CI)")
    axes[0][0].legend(fontsize=7, loc="upper left")
    fig.text(0.5, 0.005, "objection support: bare claim | 3 quoted feature z-scores | atlas similarities;  "
             "speaker: senior PI (solid) | junior (hatched)\ncontrol: \"Please double-check your answer.\"",
             ha="center", fontsize=7)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    path = OUT / f"{name}_follow.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    """Figure 3 (the same atlas text by channel) is drawn by `python -m sor.channel analyze`."""
    argv = sys.argv[1:] if argv is None else argv
    OUT.mkdir(parents=True, exist_ok=True)
    for i, run in enumerate(argv):
        an = json.loads((Path(run) / "analysis.json").read_text(encoding="utf-8"))
        run_name = Path(run).name
        if "ember" in run_name:
            label = "ember"
        elif "muse-spark-1.3_" in run_name:
            label = "secondary"
        else:
            label = "primary" if i == 0 else "secondary"
        print(f"-> {fig_follow(an, label).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
