"""
Dataset and collection download.
"""

from __future__ import annotations

import concurrent.futures
import shutil
import sys
import zipfile
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

    if not force and dataset_dir.exists() and any(dataset_dir.iterdir()):
        print(f"  ⏭️  Skipping {dataset_code} (already downloaded; use --force to re-download)")
        return

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


def _extract_one_zip(zip_path: Path, extract_to: Path, force: bool) -> None:
    """Extract a single Bruker .zip directly into a .d folder in extract_to.

    Mirrors: unzip -oq file.zip -d name.d
    So file.zip containing data/ → name.d/data/
    """
    name = zip_path.stem  # e.g. "Sample01" from "Sample01.zip"
    out_d = extract_to / f"{name}.d"

    if not force and out_d.exists():
        print(f"  ⏭️  Skipping {zip_path.name} (.d already exists)")
        return

    if force and out_d.exists():
        shutil.rmtree(out_d)

    out_d.mkdir(parents=True, exist_ok=True)
    print(f"  📦 Extracting {zip_path.name} ...")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(out_d)
        print(f"  ✅ {zip_path.name} → {out_d.name}")
    except Exception:
        shutil.rmtree(out_d, ignore_errors=True)
        raise


def extract_bruker_zips(
    download_dir: Path,
    extract_to: Path,
    *,
    jobs: int = 4,
    force: bool = False,
) -> None:
    """Extract all Bruker .zip files in download_dir to .d folders in extract_to."""
    zips = sorted(download_dir.rglob("*.zip"))
    if not zips:
        print(f"  ℹ️  No .zip files found in {download_dir}")
        return

    extract_to.mkdir(parents=True, exist_ok=True)
    print(f"  🗜️  {len(zips)} .zip file(s) — extracting with {jobs} parallel job(s) ...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(_extract_one_zip, z, extract_to, force): z for z in zips}
        for fut in concurrent.futures.as_completed(futures):
            exc = fut.exception()
            if exc:
                print(f"  ❌ Error extracting {futures[fut].name}: {exc}")

    print(f"  ✅ Extraction complete → {extract_to}")


def download_bruker(
    o: Openbis,
    codes: list[str],
    output_dir: str = DEFAULT_DOWNLOAD_DIR,
    *,
    collection: str | None = None,
    list_only: bool = False,
    limit: int | None = None,
    force: bool = False,
    extract_to: str | None = None,
    jobs: int = 4,
) -> None:
    """Download Bruker .zip datasets and optionally extract to .d folders."""
    if collection:
        download_collection(
            o, collection, output_dir,
            list_only=list_only, limit=limit, force=force,
        )
    else:
        if limit:
            codes = codes[:limit]
        for code in codes:
            print(f"\n  ⬇️  {code}")
            download_dataset(o, code, output_dir, list_only=list_only, force=force)

    if list_only or not extract_to:
        return

    extract_bruker_zips(Path(output_dir), Path(extract_to), jobs=jobs, force=force)
