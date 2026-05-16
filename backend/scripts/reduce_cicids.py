#!/usr/bin/env python3
"""Create a lightweight CICIDS2017 subset for Chromebook/Crostini use.

This script streams the large cleaned dataset in chunks, keeps a uniform
reservoir sample of 3000 rows, shuffles the final subset, and writes the
result to backend/data/cicids_subset.csv.

Only pandas plus the Python standard library are used.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "cicids2017_cleaned.csv"
OUTPUT = ROOT / "data" / "cicids_subset.csv"
TARGET_ROWS = 3000
CHUNK_SIZE = 100_000
RANDOM_SEED = 42


def reservoir_sample_csv(source_path: Path, target_rows: int, chunk_size: int, seed: int) -> pd.DataFrame:
    """Sample `target_rows` uniformly from a CSV without loading it all at once."""
    rng = random.Random(seed)
    reservoir: list[tuple] = []
    columns: list[str] | None = None
    seen = 0

    for chunk in pd.read_csv(source_path, chunksize=chunk_size):
        if columns is None:
            columns = list(chunk.columns)

        for row in chunk.itertuples(index=False, name=None):
            seen += 1
            if len(reservoir) < target_rows:
                reservoir.append(row)
                continue

            replace_at = rng.randint(1, seen)
            if replace_at <= target_rows:
                reservoir[replace_at - 1] = row

    if columns is None:
        raise ValueError(f"No data found in {source_path}")

    if not reservoir:
        raise ValueError(f"Dataset {source_path} did not yield any rows")

    sample_df = pd.DataFrame(reservoir, columns=columns)
    if len(sample_df) > target_rows:
        sample_df = sample_df.iloc[:target_rows].copy()
    return sample_df


def main() -> int:
    if not SOURCE.exists():
        raise FileNotFoundError(f"Source dataset not found: {SOURCE}")

    subset = reservoir_sample_csv(
        source_path=SOURCE,
        target_rows=TARGET_ROWS,
        chunk_size=CHUNK_SIZE,
        seed=RANDOM_SEED,
    )

    subset = subset.sample(frac=1.0, random_state=RANDOM_SEED).reset_index(drop=True)
    subset.to_csv(OUTPUT, index=False)

    loaded = pd.read_csv(OUTPUT)
    file_size = os.path.getsize(OUTPUT)
    label_column = "Attack Type" if "Attack Type" in loaded.columns else loaded.columns[-1]
    label_distribution = loaded[label_column].value_counts(dropna=False).to_dict()

    print(f"Final shape: {loaded.shape}")
    print(f"Label distribution ({label_column}): {label_distribution}")
    print(f"Output file size: {file_size} bytes")
    print(f"Output file: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
