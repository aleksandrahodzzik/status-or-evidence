"""Config loading and project-wide constants."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]

# The 12 BBBC021 MoA classes, exact strings as in MuseCell (run_started.moa_classes).
ALLOWED_MOAS = [
    "Actin disruptors", "Aurora kinase inhibitors", "Cholesterol-lowering", "DNA damage", "DNA replication",
    "Eg5 inhibitors", "Epithelial", "Kinase inhibitors", "Microtubule destabilizers", "Microtubule stabilizers",
    "Protein degradation", "Protein synthesis",
]

VARIANTS = ("with_nsc", "no_nsc")


@lru_cache
def load_config(path: str | None = None) -> dict[str, Any]:
    cfg = yaml.safe_load((Path(path) if path else ROOT / "config.yaml").read_text(encoding="utf-8"))
    if cfg["budget_cap_usd"] > cfg["hard_limit_usd"]:
        raise ValueError("budget_cap_usd may not exceed hard_limit_usd")
    return cfg


def model_entry(cfg: dict, which: str) -> dict:
    """`which` is 'primary', 'secondary', or a literal model id present in the config."""
    if which in cfg["models"]:
        return cfg["models"][which]
    for entry in cfg["models"].values():
        if entry["id"] == which:
            return entry
    raise KeyError(f"model '{which}' is not in config.yaml (no price, refusing to call it unmetered)")


def path(cfg: dict, key: str) -> Path:
    return ROOT / cfg["paths"][key]
