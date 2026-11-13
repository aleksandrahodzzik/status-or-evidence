"""Step 0.4: schema + row counts of MuseCell data tables (read-only; parquet metadata, small heads only)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

MUSECELL = Path(r"C:\Users\Oleksandra\OneDrive\Desktop\MuseCell")
DATA_DIR = Path.home() / "musecell-data"
PARQUETS = [MUSECELL / "data" / "index.parquet",
            DATA_DIR / "processed" / "atlas" / "wells.parquet",
            DATA_DIR / "processed" / "atlas" / "wells_norm.parquet",
            DATA_DIR / "processed" / "atlas" / "treatments.parquet",
            DATA_DIR / "processed" / "atlas" / "field_features.parquet",
            DATA_DIR / "processed" / "atlas_resnet50_tvn" / "wells.parquet",
            DATA_DIR / "processed" / "atlas_resnet50_tvn" / "treatments.parquet"]
JSONS = [DATA_DIR / "processed" / "atlas" / "reference.json", DATA_DIR / "processed" / "atlas_resnet50_tvn" / "meta.json"]
CSVS = [DATA_DIR / "metadata" / "BBBC021_v1_moa.csv", DATA_DIR / "metadata" / "BBBC021_v1_compound.csv",
        DATA_DIR / "metadata" / "BBBC021_v1_image.csv"]


def main() -> None:
    pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_colwidth", 30)
    for p in PARQUETS:
        meta = pq.ParquetFile(p)
        cols = meta.schema_arrow.names
        print(f"\n=== {p}  rows={meta.metadata.num_rows} cols={len(cols)}")
        print("columns:", cols if len(cols) <= 60 else cols[:30] + ["..."] + cols[-5:])
        head = meta.read_row_group(0, columns=cols[:40]).slice(0, 3).to_pandas()
        print(head.to_string()[:3000])
    for p in JSONS:
        print(f"\n=== {p}\n{p.read_text(encoding='utf-8')[:800]}")
    for p in CSVS:
        df = pd.read_csv(p, nrows=3)
        n = sum(1 for _ in open(p, encoding="utf-8")) - 1
        print(f"\n=== {p} rows={n}\n{df.to_string()[:1500]}")


if __name__ == "__main__":
    main()
