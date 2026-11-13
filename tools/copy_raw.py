"""Copy the inputs this project needs from MuseCell (read-only) into data/raw/ and write data/PROVENANCE.md.

Only reads from MuseCell and DATA_DIR; never writes there. Transcripts: every run id listed in the two index files;
when a run id exists in several MuseCell folders the first folder in TRANSCRIPT_DIRS wins (duplicates are checked
for byte identity and reported).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

MUSECELL = Path(r"C:\Users\Oleksandra\OneDrive\Desktop\MuseCell")
MUSECELL_COMMIT = "313e7f5"  # as stated by the project owner; git is never run inside MuseCell
DATA_DIR = Path.home() / "musecell-data"  # backend/.env DATA_DIR=~/musecell-data
TRANSCRIPT_DIRS = [MUSECELL / "runs" / "eval", MUSECELL / "runs" / "eval_open_world", MUSECELL / "runs",
                   MUSECELL / "demo" / "runs"]
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

FILES = {  # source -> destination (relative to data/raw)
    MUSECELL / "eval" / "agent_runs.jsonl": "index/agent_runs.jsonl",
    MUSECELL / "eval" / "open_world_runs.jsonl": "index/open_world_runs.jsonl",
    DATA_DIR / "processed" / "atlas" / "wells_norm.parquet": "atlas/wells_norm.parquet",
    DATA_DIR / "processed" / "atlas" / "treatments.parquet": "atlas/treatments.parquet",
    DATA_DIR / "processed" / "atlas_resnet50_tvn" / "wells.parquet": "atlas_resnet50_tvn/wells.parquet",
    DATA_DIR / "processed" / "atlas_resnet50_tvn" / "treatments.parquet": "atlas_resnet50_tvn/treatments.parquet",
    DATA_DIR / "processed" / "atlas_resnet50_tvn" / "meta.json": "atlas_resnet50_tvn/meta.json",
    DATA_DIR / "metadata" / "BBBC021_v1_moa.csv": "metadata/BBBC021_v1_moa.csv",
    DATA_DIR / "metadata" / "BBBC021_v1_compound.csv": "metadata/BBBC021_v1_compound.csv",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    copied: list[tuple[str, str, str]] = []
    for src, rel in FILES.items():
        dst = RAW / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        copied.append((str(src), rel, sha256(dst)))

    run_ids = []
    for name in ("agent_runs.jsonl", "open_world_runs.jsonl"):
        for line in (RAW / "index" / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                run_ids.append(json.loads(line)["run_id"])

    duplicates, missing = [], []
    for rid in run_ids:
        found = [d / f"{rid}.jsonl" for d in TRANSCRIPT_DIRS if (d / f"{rid}.jsonl").exists()]
        if not found:
            missing.append(rid)
            continue
        if len(found) > 1:
            same = len({sha256(p) for p in found}) == 1
            duplicates.append((rid, [str(p) for p in found], same))
        dst = RAW / "transcripts" / f"{rid}.jsonl"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(found[0], dst)
        copied.append((str(found[0]), f"transcripts/{rid}.jsonl", sha256(dst)))

    lines = [
        "# Provenance of data/raw/",
        "",
        f"Copied {datetime.now(timezone.utc).isoformat(timespec='seconds')} by `tools/copy_raw.py` (read-only access "
        "to the sources; nothing written there).",
        "",
        f"- MuseCell repo: `{MUSECELL}` at commit `{MUSECELL_COMMIT}` (commit as stated by the project owner; "
        "git was not run inside MuseCell).",
        f"- MuseCell DATA_DIR: `{DATA_DIR}` (from the `DATA_DIR` line of MuseCell `backend/.env`; nothing else read "
        "from that file).",
        f"- Transcripts: {len(run_ids) - len(missing)} of {len(run_ids)} indexed run ids found; missing: "
        f"{missing or 'none'}.",
        f"- Run ids present in more than one MuseCell folder: {len(duplicates)}"
        + ("".join(f"\n  - `{r}` identical={s}: {', '.join(p)}" for r, p, s in duplicates) if duplicates else ""),
        "",
        "| destination (data/raw/...) | sha256 | source |",
        "|---|---|---|",
    ]
    lines += [f"| `{rel}` | `{h}` | `{src}` |" for src, rel, h in copied]
    (ROOT / "data" / "PROVENANCE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"copied {len(copied)} files; transcripts missing: {len(missing)}; duplicates: {len(duplicates)} "
          f"(all identical: {all(s for _, _, s in duplicates)})")


if __name__ == "__main__":
    main()
