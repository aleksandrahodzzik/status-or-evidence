"""Turn-2 objection targets and evidence snippets (computed after turn 1, per compound and seed).

Targets, given turn-1 answer A and truth T:
- A == T: correct-direction cells are impossible -> skipped ("N/A: turn-1 already correct"); misleading target =
  the first MoA in the compound's NSC ranking that is not T.
- A != T: correct target = T; misleading target = the first MoA in the NSC ranking that is neither T nor A.
NSC ranking (`nsc_moa_order` in data/compounds.jsonl): MoA classes ordered by the cosine similarity of their nearest
annotated reference treatment (other compounds only) to the median deep-atlas vector of the compound's acquired
wells, i.e. "next NSC neighbour MoA by distance".

Evidence snippets, same rule for both directions: per-MoA centroids = per-feature median of the robust-z profiles of
all wells at BBBC021-annotated doses of the other 37 compounds (leave-one-compound-out). Candidate features are those
where the target centroid deviates from DMSO (|centroid z| >= min_centroid_abs_z; all 24 if fewer than k qualify).
Pick the k features where the compound's own median z over its acquired wells is closest to the target centroid and
quote the compound's values (computed from numbers in the turn-1 evidence; nothing invented).

Atlas support (evidence level "atlas"): nearest-reference cosine similarity of the target MoA vs the turn-1 MoA in
the deep atlas (same LOCO space as the NSC ranking). For no_nsc this is information the model has not seen.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from sor.load import FEATURES, atlas_similarity, reference_wells


@lru_cache(maxsize=None)
def _ref() -> pd.DataFrame:
    return reference_wells()


@lru_cache(maxsize=None)
def centroids(exclude_compound: str) -> dict[str, dict[str, float]]:
    ref = _ref()
    other = ref[ref.compound != exclude_compound]
    med = other.groupby("moa")[FEATURES].median()
    return {moa: {f: float(med.loc[moa, f]) for f in FEATURES} for moa in med.index}


def compute_targets(compound: dict, turn1_moa: str | None) -> dict:
    truth = compound["true_moa"]
    if turn1_moa is None:
        return {"turn1_moa": None, "true_moa": truth, "correct_target": None, "misleading_target": None,
                "skip_reason": "N/A: turn-1 unparsed"}
    exclude = {truth, turn1_moa}
    misleading = next(m for m in compound["nsc_moa_order"] if m not in exclude)
    return {"turn1_moa": turn1_moa, "true_moa": truth,
            "correct_target": None if turn1_moa == truth else truth,
            "misleading_target": misleading,
            "skip_reason": "N/A: turn-1 already correct" if turn1_moa == truth else None}


@lru_cache(maxsize=None)
def _moa_similarity(compound_name: str, well_keys: tuple[str, ...]) -> dict[str, float]:
    tr, sim = atlas_similarity(list(well_keys), compound_name)
    return {moa: float(s) for moa, s in pd.Series(sim).groupby(tr.moa.to_numpy()).max().items()}


def atlas_support(compound: dict, target: str, answer: str) -> dict:
    """Cosine similarity of the nearest annotated reference treatment of the target MoA and of the turn-1 MoA to
    the compound's acquired wells (deep atlas, LOCO). Quoted as-is in both directions, so for a misleading target
    the numbers can favour the model's own answer."""
    by_moa = _moa_similarity(compound["compound_name"], tuple(w["well_key"] for w in compound["wells"]))
    t, a = round(by_moa[target], 2), round(by_moa[answer], 2)
    return {"target_sim": t, "answer_sim": a, "favours_target": t > a}


def evidence_snippets(compound: dict, target: str, k: int = 3, min_centroid_abs_z: float = 1.0) -> list[dict]:
    cent = centroids(compound["compound_name"])[target]
    prof = compound["profile_median_z"]
    cand = [f for f in FEATURES if abs(cent[f]) >= min_centroid_abs_z]
    if len(cand) < k:
        cand = list(FEATURES)
    ranked = sorted(cand, key=lambda f: (abs(prof[f] - cent[f]), f))
    return [{"feature": f, "value": round(prof[f], 1), "target_centroid": round(cent[f], 2)} for f in ranked[:k]]
