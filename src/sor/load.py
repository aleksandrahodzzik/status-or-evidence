"""Turn-1 evidence from recorded MuseCell transcripts (Plan A) -> data/compounds.jsonl.

Source rule (one transcript per compound, fixed): among finished runs in agent_runs.jsonl with agent "v5",
scientist "muse-spark-1.3" and budget 4 that have a transcript, take the one whose run_started event is latest.
If a compound has none, take the latest finished run with a transcript from any index file (not needed: all 38
compounds have a v5 run).

Kept: tool_result events strictly before the first `conclusion` event and before any `unblinded` event, for
acquire_well (feature z-scores), describe_phenotype (Microscopist report), dose_response and, in the with_nsc
variant only, compare_to_reference_atlas with kind == "atlas" (reference compound names stripped).
Dropped: everything else (thinking, tool calls/rationales, search_literature, update_hypotheses,
submit_conclusion, protocol_call, image/field ids).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from sor.config import ALLOWED_MOAS, ROOT, VARIANTS

RAW = ROOT / "data" / "raw"
FEATURES = ["nuc_area", "nuc_dna_integrated", "nuc_dna_mean", "nuc_eccentricity", "nuc_solidity",
            "nuc_form_factor", "nuc_major_axis", "cell_area", "cell_nuc_area_ratio", "cell_roundness",
            "cell_eccentricity", "cell_solidity", "cell_major_axis", "tub_mean", "tub_std", "tub_glcm_contrast",
            "act_mean", "act_std", "act_glcm_contrast", "act_tub_ratio", "cell_count", "frac_mitotic_like",
            "frac_large_nucleus", "frac_multinucleate_proxy"]
NSC_PATTERN = re.compile(r"atlas|\bNSC\b|neighbou?r|nearest|reference|similarity|1-NN|k-neighbour", re.I)
KEEP_TOOLS = {"acquire_well", "describe_phenotype", "dose_response", "compare_to_reference_atlas"}

EVIDENCE_HEADER = ("Specimen: one unknown compound applied to MCF-7 breast cancer cells (BBBC021 cell painting: "
                   "DNA, tubulin and actin stains), several doses. Feature z-scores are robust z-scores against "
                   "same-plate DMSO control wells (0 = like DMSO).")


# --- index + transcripts ---------------------------------------------------------------------------

def read_index() -> list[dict]:
    rows = []
    for name in ("agent_runs.jsonl", "open_world_runs.jsonl"):
        for line in (RAW / "index" / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append({**json.loads(line), "_index": name})
    return rows


def read_transcript(run_id: str) -> list[dict] | None:
    p = RAW / "transcripts" / f"{run_id}.jsonl"
    if not p.exists():
        return None
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _started(events: list[dict]) -> str:
    return next((e["ts"] for e in events if e["type"] == "run_started"), events[0]["ts"])


def choose_source(rows: list[dict]) -> tuple[dict, list[dict], str]:
    """Rows of one compound -> (index row, transcript events, rule used)."""
    def finished_with_transcript(cands):
        out = []
        for r in cands:
            ev = read_transcript(r["run_id"]) if r.get("status") == "finished" else None
            if ev and any(e["type"] == "conclusion" for e in ev):
                out.append((r, ev))
        return sorted(out, key=lambda x: _started(x[1]), reverse=True)

    preferred = [r for r in rows if r["_index"] == "agent_runs.jsonl" and r["models"].get("agent") == "v5"
                 and r["models"]["scientist"] == "muse-spark-1.3" and r.get("budget") == 4]
    hits = finished_with_transcript(preferred)
    if hits:
        return hits[0][0], hits[0][1], "v5+muse-spark-1.3+budget4 (latest)"
    hits = finished_with_transcript(rows)
    if hits:
        return hits[0][0], hits[0][1], "fallback: latest finished run"
    raise LookupError(f"no usable transcript for {rows[0]['compound']}")


# --- evidence blocks -------------------------------------------------------------------------------

def _fmt_z(v: float) -> str:
    return f"{v:+.2f}"


def _conc(c: float) -> str:
    return f"{c:g} µM"


class Redactor:
    """Replaces any BBBC021 compound name with [compound]; counts hits. "DMSO" (the control) and "unknown"
    (a BBBC021 compound-table entry that is also the Microscopist's 'unknown' mechanism) are not names."""

    NOT_NAMES = {"dmso", "unknown"}

    def __init__(self, names: list[str]):
        names = sorted({n for n in names if n and n.lower() not in self.NOT_NAMES}, key=len, reverse=True)
        self.pattern = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in names) + r")(?![\w-])", re.I)
        self.hits: list[str] = []

    def __call__(self, text: str) -> str:
        def sub(m):
            self.hits.append(m.group(0))
            return "[compound]"
        return self.pattern.sub(sub, text)


def extract_blocks(events: list[dict], redact: Redactor) -> tuple[list[dict], list[dict]]:
    """Transcript -> (evidence blocks, acquired wells with profile_z). Uses only events before the first
    `conclusion` and before `unblinded`."""
    cut = next(i for i, e in enumerate(events) if e["type"] in ("conclusion", "unblinded"))
    labels: dict[str, str] = {}   # well_id -> W1..
    field_to_well: dict[str, str] = {}
    blocks, wells = [], []

    def clean(text: str) -> str:
        """Compound names out; field / well ids (they appear in Microscopist prose) -> well labels."""
        text = re.sub(r"\bf_[0-9a-f]{12}\b", lambda m: f"a {field_to_well[m.group(0)]} field"
                      if m.group(0) in field_to_well else "a field", text)
        text = re.sub(r"\bw_[0-9a-f]{10}\b", lambda m: labels.get(m.group(0), "a well"), text)
        return redact(text)

    for e in events[:cut]:
        if e["type"] != "tool_result":
            continue
        d = e["data"]
        if d["name"] not in KEEP_TOOLS or not d.get("ok"):
            continue
        data = d["data"]
        if d["name"] == "acquire_well":
            label = labels.setdefault(data["well_id"], f"W{len(labels) + 1}")
            for f in data.get("field_ids", []):
                field_to_well[f] = label
            pz = {f: data["profile_z"][f] for f in FEATURES}
            n = data["segmentation"]["cells_measured"]
            top = sorted(FEATURES, key=lambda f: -abs(pz[f]))[:3]
            text = (f"[Well {label}] dose {_conc(data['concentration_uM'])}, replicate {data['replicate']}, "
                    f"{n} cells measured. Largest deviations: "
                    + ", ".join(f"{f} z={_fmt_z(pz[f])}" for f in top)
                    + ".\nAll feature z-scores vs DMSO: " + ", ".join(f"{f} {_fmt_z(pz[f])}" for f in FEATURES))
            blocks.append({"kind": "well", "variants": list(VARIANTS), "text": clean(text)})
            wells.append({"label": label, "concentration_uM": data["concentration_uM"],
                          "replicate": data["replicate"], "cells_measured": n, "profile_z": pz})
        elif d["name"] == "describe_phenotype":
            rep = data["report"]
            on = sorted({field_to_well.get(f, "?") for f in data["field_ids"]})
            lines = [f"[Microscopist report on wells {', '.join(on)} ({len(data['field_ids'])} image field(s)), "
                     f"compared with a same-plate DMSO field] Cell density vs DMSO: {rep.get('cell_density')}."]
            for o in rep.get("observations", []):
                agree = "agrees with measurements" if o.get("agrees_with_measurements") else \
                    "not covered by / disagrees with measurements"
                lines.append(f"- {o.get('channel')}: {o.get('finding')} ({agree})")
            cands = rep.get("candidate_mechanisms", [])
            if cands:
                lines.append("Microscopist's candidate mechanisms: "
                             + "; ".join(f"{c['moa']} ({c.get('why', '').strip()})" for c in cands))
            if rep.get("uncertainty"):
                lines.append(f"Microscopist's uncertainty: {rep['uncertainty']}")
            blocks.append({"kind": "phenotype", "variants": list(VARIANTS), "text": clean("\n".join(lines))})
        elif d["name"] == "dose_response":
            pts = "; ".join(f"{_conc(p['concentration_uM'])}: median z {p['median']:+.2f} (n={p['n_wells']})"
                            for p in data["points"])
            rho = data.get("spearman_rho")
            stat = f"Spearman rho={rho:+.2f} (p={data.get('p_value'):.2g})" if rho is not None else "rho n/a"
            note = f" Note: {data['note']}" if data.get("note") else ""
            text = f"[Dose response of {data['feature']} over {data['n_wells']} wells] {pts}. {stat}.{note}"
            blocks.append({"kind": "dose_response", "variants": list(VARIANTS), "text": clean(text)})
        elif d["name"] == "compare_to_reference_atlas" and d.get("kind") == "atlas":
            wl = [labels.get(w, "?") for w in data["well_ids"]]
            lines = [f"[Reference atlas comparison: annotated reference treatments of OTHER compounds, "
                     f"{data.get('similarity')}; query wells {', '.join(wl)}, k={data['k']}]"]
            nsc = data.get("nsc")
            if nsc and nsc.get("wells"):
                per = "; ".join(f"{labels.get(p['well_id'], '?')} ({_conc(p['concentration_uM'])}) -> "
                                f"{p['nearest_moa']} (sim {p['similarity']:.3f})" for p in nsc["per_well"])
                tally = ", ".join(f"{t['moa']} {t['votes']}" for t in nsc["tally"])
                lines.append(f"NSC vote (1-NN per acquired well, majority): {nsc['moa']} "
                             f"({nsc['votes']}/{nsc['wells']}). Per well: {per}. Tally: {tally}.")
            nb = "; ".join(f"{n['moa']} at {_conc(n['concentration_uM'])} (sim {n['similarity']:.3f})"
                           for n in data["neighbors"])
            lines.append(f"Nearest reference treatments (compound names withheld): {nb}.")
            if data.get("moa_summary"):
                lines.append("Classes among neighbours: " + ", ".join(
                    f"{m['moa']} {m['neighbors']}/{data['k']} (mean sim {m['mean_similarity']:.3f})"
                    for m in data["moa_summary"]))
            blocks.append({"kind": "atlas", "variants": ["with_nsc"], "text": clean("\n".join(lines))})
    return blocks, wells


def evidence_text(compound: dict, variant: str) -> str:
    if variant not in VARIANTS:
        raise ValueError(variant)
    parts = [EVIDENCE_HEADER] + [b["text"] for b in compound["evidence_blocks"] if variant in b["variants"]]
    return "\n\n".join(parts)


# --- NSC neighbours in code (MuseCell's deep atlas space, leave-one-compound-out) --------------------

def all_wells() -> pd.DataFrame:
    """All 1228 wells (treated + DMSO), robust z vs same-plate DMSO (= the `profile_z` the agent saw)."""
    return pd.read_parquet(RAW / "atlas" / "wells_norm.parquet")


def reference_wells() -> pd.DataFrame:
    """Treated wells at BBBC021-annotated concentrations (the 38 compounds)."""
    wn = all_wells()
    return wn[(wn.role == "treated") & wn.moa_annotated_conc.astype(bool)].reset_index(drop=True)


def compound_profile(wells: list[dict]) -> dict[str, float]:
    """Per-feature median over the acquired wells shown in the turn-1 evidence."""
    return {f: float(np.median([w["profile_z"][f] for w in wells])) for f in FEATURES}


def match_well_keys(wells: list[dict], compound: str, table: pd.DataFrame, tol: float = 0.011) -> list[str]:
    """Each acquired well -> its atlas well_key, by the exact z-profile (transcripts round to 2 decimals)."""
    cand = table[table.compound == compound]
    m = cand[FEATURES].to_numpy()
    keys = []
    for w in wells:
        err = np.abs(m - np.array([w["profile_z"][f] for f in FEATURES])).max(axis=1)
        i = int(np.argmin(err))
        if err[i] > tol or (err < tol).sum() != 1:
            raise LookupError(f"{compound} {w['label']}: no unique atlas well (min err {err[i]:.4f})")
        keys.append(cand.well_key.iloc[i])
    return keys


def nsc_neighbours(well_keys: list[str], compound: str) -> tuple[list[dict], list[str]]:
    """MuseCell's atlas query in its own space: median ResNet50+TVN vector of the acquired wells, cosine to every
    annotated reference treatment of the other compounds (LOCO). Returns (top-20 neighbours, no names;
    MoA order by first appearance over the full ranking)."""
    dims = [f"d{i:03d}" for i in range(212)]
    wv = pd.read_parquet(RAW / "atlas_resnet50_tvn" / "wells.parquet").set_index("well_key")
    tr = pd.read_parquet(RAW / "atlas_resnet50_tvn" / "treatments.parquet")
    tr = tr[tr.moa_annotated_conc.astype(bool) & (tr.compound != compound)].reset_index(drop=True)
    q = np.median(wv.loc[well_keys, dims].to_numpy(), axis=0)
    m = tr[dims].to_numpy()
    sim = m @ q / (np.linalg.norm(m, axis=1) * np.linalg.norm(q) + 1e-12)
    order = np.argsort(-sim)
    neighbours = [{"moa": tr.moa.iloc[i], "concentration_uM": float(tr.concentration_uM.iloc[i]),
                   "similarity": round(float(sim[i]), 4)} for i in order]
    return neighbours[:20], list(dict.fromkeys(n["moa"] for n in neighbours))


# --- build -----------------------------------------------------------------------------------------

def build(out: Path | None = None) -> list[dict]:
    rows = read_index()
    names = pd.read_csv(RAW / "metadata" / "BBBC021_v1_compound.csv").compound.dropna().tolist()
    table = all_wells()
    by_compound: dict[str, list[dict]] = {}
    for r in rows:
        by_compound.setdefault(r["compound"], []).append(r)
    compounds = []
    for name in sorted(by_compound):
        row, events, rule = choose_source(by_compound[name])
        redact = Redactor(names)
        blocks, wells = extract_blocks(events, redact)
        profile = compound_profile(wells)
        keys = match_well_keys(wells, name, table)
        for w, k in zip(wells, keys):
            w["well_key"] = k
        neighbours, moa_order = nsc_neighbours(keys, name)
        truth = row["truth_moa"]
        assert truth in ALLOWED_MOAS, truth
        compounds.append({
            "compound_id": row["specimen_id"], "true_moa": truth, "source_run_id": row["run_id"],
            "source_rule": rule, "source_models": row["models"],
            "source_first_moa": row.get("first_moa"), "source_first_correct": row.get("first_correct"),
            "evidence_blocks": blocks, "wells": wells, "profile_median_z": profile,
            "nsc_neighbours": neighbours, "nsc_moa_order": moa_order,
            "redactions": len(redact.hits), "compound_name": name,  # name: bookkeeping only, never in prompts
        })
    out = out or ROOT / "data" / "compounds.jsonl"
    out.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in compounds), encoding="utf-8")
    return compounds


def load_compounds(path: Path | None = None) -> list[dict]:
    p = path or ROOT / "data" / "compounds.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    compounds = build()
    print(f"{len(compounds)} compounds -> data/compounds.jsonl")
    for c in compounds:
        kinds = {}
        for b in c["evidence_blocks"]:
            kinds[b["kind"]] = kinds.get(b["kind"], 0) + 1
        nsc_hits = [b["kind"] for b in c["evidence_blocks"] if "no_nsc" in b["variants"]
                    and NSC_PATTERN.search(b["text"])]
        print(f"{c['compound_id']} {c['true_moa']:26} {c['source_run_id']} {kinds} redactions={c['redactions']}"
              + (f" NSC-WORDS-IN-no_nsc:{nsc_hits}" if nsc_hits else ""))


if __name__ == "__main__":
    main()
