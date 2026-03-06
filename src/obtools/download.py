"""
Dataset and collection download.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pybis import Openbis

from .auth import load

DEFAULT_DOWNLOAD_DIR = load().get("OBTOOLS_DOWNLOAD_DIR", str(Path.home() / "data" / "openbis"))


def download_dataset(
    o: Openbis,
    dataset_code: str,
    output_dir: str = DEFAULT_DOWNLOAD_DIR,
    *,
    list_only: bool = False,
    force: bool = False,
) -> None:
    """Download a single dataset to output_dir."""
    out = Path(output_dir)

    try:
        dataset = o.get_dataset(dataset_code)
    except Exception as exc:
        print(f"❌ Dataset not found: {dataset_code} ({exc})")
        sys.exit(1)

    files = dataset.file_list
    if not files:
        print(f"  ℹ️  No files in dataset {dataset_code}")
        return

    print(f"  📂 {len(files)} file(s) in {dataset_code}")
    for f in files:
        print(f"    • {f}")

    if list_only:
        return

    out.mkdir(parents=True, exist_ok=True)
    dataset_dir = out / dataset_code
    dataset_dir.mkdir(exist_ok=True)

    print(f"  ⬇️  Downloading to {dataset_dir} ...")
    try:
        dataset.download(destination=str(dataset_dir), wait_until_finished=True)
        print(f"  ✅ Done: {dataset_dir}")
    except Exception as exc:
        print(f"  ❌ Download failed: {exc}")
        sys.exit(1)


def download_collection(
    o: Openbis,
    collection_path: str,
    output_dir: str = DEFAULT_DOWNLOAD_DIR,
    *,
    list_only: bool = False,
    limit: int | None = None,
    force: bool = False,
) -> None:
    """Download all datasets in an OpenBIS collection."""
    print(f"  🔍 Fetching datasets in {collection_path} ...")
    try:
        datasets = o.get_datasets(experiment=collection_path)
    except Exception as exc:
        print(f"❌ Could not fetch collection: {exc}")
        sys.exit(1)

    if datasets is None or len(datasets) == 0:
        print("  ℹ️  No datasets found.")
        return

    codes = []
    if hasattr(datasets, "itertuples"):
        for row in datasets.itertuples():
            codes.append(getattr(row, "permId", None) or getattr(row, "code", None))
    else:
        for ds in datasets:
            codes.append(getattr(ds, "permId", None) or getattr(ds, "code", None))
    codes = [c for c in codes if c]

    if limit:
        codes = codes[:limit]

    print(f"  📦 {len(codes)} dataset(s) found")
    for code in codes:
        print(f"    • {code}")

    if list_only:
        return

    for code in codes:
        print(f"\n  ⬇️  {code}")
        download_dataset(o, code, output_dir, force=force)
