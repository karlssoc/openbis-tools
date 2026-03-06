"""
Raw MS data ingestion into OpenBIS.

Discovers Thermo .raw files and Bruker .d directories in a source path,
optionally archives Bruker directories as .zip, then for each file:
  1. Creates a BIOL_DDB sample in the target collection
  2. Uploads the raw file / archive as a dataset linked to that sample

Bruker archiving uses Python's stdlib zipfile — no external tools needed,
works identically on Windows, macOS, and Linux. macOS metadata files
(__MACOSX/, .DS_Store, ._* resource forks) are excluded automatically.

Usage:
    obtools ingest /path/to/rawfiles --collection /DDB/CK/E_MySepsis2025
    obtools ingest /data/runs/ --collection /DDB/CK/E_MyStudy --create-collection
    obtools ingest /data/ --dry-run
"""

from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterator

from pybis import Openbis

# ---------------------------------------------------------------------------
# macOS metadata patterns to exclude from Bruker zip archives
# ---------------------------------------------------------------------------
_MAC_EXCLUSIONS = {"__macosx", ".ds_store", ".fseventsd", ".spotlight-v100"}


def _is_mac_metadata(path: Path) -> bool:
    """Return True if any component of path is macOS metadata."""
    for part in path.parts:
        if part.lower() in _MAC_EXCLUSIONS or part.startswith("._"):
            return True
    return False


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

class RawFile:
    """Represents a single raw MS acquisition (file or directory)."""

    def __init__(self, path: Path, vendor: str):
        self.path = path
        self.vendor = vendor          # "thermo" | "bruker"
        self.name = path.stem         # basename without extension / suffix
        self.is_dir = path.is_dir()

    def __repr__(self):
        return f"<RawFile {self.vendor} {self.path.name}>"


def discover(source: str | Path) -> list[RawFile]:
    """
    Find all .raw files and .d directories directly under `source`.

    Does not recurse — expects a flat directory of acquisitions.
    """
    source = Path(source)
    if not source.is_dir():
        print(f"❌ Source path is not a directory: {source}")
        sys.exit(1)

    found: list[RawFile] = []
    for entry in sorted(source.iterdir()):
        if entry.is_file() and entry.suffix.lower() == ".raw":
            found.append(RawFile(entry, "thermo"))
        elif entry.is_dir() and entry.suffix.lower() == ".d":
            found.append(RawFile(entry, "bruker"))

    return found


# ---------------------------------------------------------------------------
# Bruker .d → .zip archiving
# ---------------------------------------------------------------------------

def zip_bruker_dir(d_dir: Path, dest_dir: Path) -> Path:
    """
    Compress a Bruker .d directory into a .zip archive in dest_dir.

    Excludes macOS metadata. Uses deflate compression.
    Returns the path of the created archive.
    """
    archive_path = dest_dir / f"{d_dir.name}.zip"
    written = 0

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(d_dir.rglob("*")):
            rel = item.relative_to(d_dir.parent)   # keep .d dir as root in archive
            if _is_mac_metadata(rel):
                continue
            if item.is_file():
                zf.write(item, rel)
                written += 1

    size_mb = archive_path.stat().st_size / 1_048_576
    print(f"    📦 {d_dir.name}.zip  ({written} files, {size_mb:.1f} MB)")
    return archive_path


# ---------------------------------------------------------------------------
# OpenBIS helpers
# ---------------------------------------------------------------------------

def _get_or_create_collection(
    o: Openbis,
    collection_path: str,
    collection_type: str,
    create: bool,
    dry_run: bool,
) -> bool:
    """
    Verify collection exists, or create it if --create-collection is set.

    collection_path must be /SPACE/PROJECT/EXPERIMENT_CODE.
    Returns True if ready to use.
    """
    try:
        o.get_experiment(collection_path)
        print(f"  ✅ Collection exists: {collection_path}")
        return True
    except Exception:
        pass

    if not create:
        print(f"  ❌ Collection not found: {collection_path}")
        print(f"     Use --create-collection to create it automatically.")
        return False

    # Parse /SPACE/PROJECT/CODE
    parts = [p for p in collection_path.strip("/").split("/") if p]
    if len(parts) != 3:
        print(f"  ❌ Cannot parse collection path '{collection_path}'.")
        print(f"     Expected format: /SPACE/PROJECT/EXPERIMENT_CODE")
        return False

    space, project_code, exp_code = parts
    project_path = f"/{space}/{project_code}"

    if dry_run:
        print(f"  [DRY RUN] Would create collection: {collection_path}  (type: {collection_type})")
        return True

    try:
        exp = o.new_experiment(
            type=collection_type,
            project=project_path,
            code=exp_code,
        )
        exp.save()
        print(f"  ✅ Created collection: {collection_path}")
        return True
    except Exception as exc:
        print(f"  ❌ Failed to create collection: {exc}")
        return False


def _create_sample(
    o: Openbis,
    collection_path: str,
    name: str,
    sample_type: str,
    dry_run: bool,
) -> str | None:
    """Create a sample in the collection. Returns permId or None on failure."""
    if dry_run:
        print(f"    [DRY RUN] Would create sample: {name}  (type: {sample_type})")
        return f"DRY-RUN-{name}"

    try:
        sample = o.new_sample(
            type=sample_type,
            experiment=collection_path,
            props={"$name": name},
        )
        sample.save()
        return sample.permId
    except Exception as exc:
        print(f"    ❌ Sample creation failed for {name}: {exc}")
        return None


def _upload_dataset(
    o: Openbis,
    collection_path: str,
    file_path: Path,
    dataset_type: str,
    sample_id: str | None,
    dry_run: bool,
) -> str | None:
    """Upload a file as a dataset. Returns permId or None on failure."""
    size_mb = file_path.stat().st_size / 1_048_576
    print(f"    ⬆️  {file_path.name}  ({size_mb:.1f} MB)")

    if dry_run:
        print(f"    [DRY RUN] Would upload dataset  (type: {dataset_type})")
        return f"DRY-RUN-DS-{file_path.stem}"

    try:
        ds = o.new_dataset(
            type=dataset_type,
            experiment=collection_path,
            files=[str(file_path)],
        )
        if sample_id:
            try:
                ds.sample = sample_id
            except Exception:
                pass   # not all pybis versions support this — skip gracefully
        ds.save()
        return ds.permId
    except Exception as exc:
        print(f"    ❌ Upload failed for {file_path.name}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Main ingest workflow
# ---------------------------------------------------------------------------

def ingest(
    o: Openbis,
    source: str,
    collection_path: str,
    *,
    create_collection: bool = False,
    collection_type: str = "MS_EXPERIMENT",
    dataset_type: str = "RAW_DATA",
    sample_type: str = "BIOL_DDB",
    prefix: str | None = None,
    skip_samples: bool = False,
    dry_run: bool = False,
) -> None:
    """
    Full ingest workflow: discover → archive Bruker dirs → create samples → upload datasets.
    """
    source_path = Path(source)

    # 1. Discover raw files
    print(f"\n🔍 Scanning: {source_path}")
    files = discover(source_path)

    if not files:
        print("  ℹ️  No .raw files or .d directories found.")
        return

    thermo = [f for f in files if f.vendor == "thermo"]
    bruker = [f for f in files if f.vendor == "bruker"]
    print(f"  Found {len(files)} acquisition(s): "
          f"{len(thermo)} Thermo .raw, {len(bruker)} Bruker .d")
    for f in files:
        print(f"    • {f.path.name}")

    # 2. Verify / create collection
    print(f"\n📂 Collection: {collection_path}")
    if not _get_or_create_collection(
        o, collection_path, collection_type, create_collection, dry_run
    ):
        sys.exit(1)

    # 3. Archive Bruker .d directories into a temp directory
    temp_dir = None
    upload_files: dict[RawFile, Path] = {}   # raw file → path to upload

    if bruker:
        print(f"\n📦 Archiving {len(bruker)} Bruker .d director{'y' if len(bruker)==1 else 'ies'}...")
        if not dry_run:
            temp_dir = tempfile.mkdtemp(prefix="obtools_bruker_")
            temp_path = Path(temp_dir)
        else:
            temp_path = Path("/tmp/obtools_bruker_dryrun")

    for f in files:
        if f.vendor == "bruker":
            if dry_run:
                print(f"    [DRY RUN] Would zip: {f.path.name}")
                upload_files[f] = Path(f"/tmp/{f.name}.zip")
            else:
                archive = zip_bruker_dir(f.path, temp_path)
                upload_files[f] = archive
        else:
            upload_files[f] = f.path

    # 4. Per-file: create sample + upload dataset
    print(f"\n🚀 Ingesting {len(files)} file(s) into {collection_path} ...")
    name_prefix = prefix or source_path.name

    results: list[dict] = []
    for i, raw in enumerate(files, 1):
        sample_name = f"{name_prefix}_{i:02d}"
        upload_path = upload_files[raw]
        print(f"\n  [{i}/{len(files)}] {raw.path.name}  →  {sample_name}")

        sample_id = None
        if not skip_samples:
            sample_id = _create_sample(o, collection_path, sample_name, sample_type, dry_run)
            if sample_id:
                print(f"    🧬 Sample: {sample_id}")

        ds_id = _upload_dataset(o, collection_path, upload_path, dataset_type, sample_id, dry_run)
        if ds_id:
            print(f"    📊 Dataset: {ds_id}")

        results.append({
            "file": raw.path.name,
            "sample_name": sample_name,
            "sample_id": sample_id,
            "dataset_id": ds_id,
        })

    # 5. Cleanup temp dir
    if temp_dir:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    # 6. Summary
    ok = sum(1 for r in results if r["dataset_id"])
    print(f"\n{'─'*55}")
    if dry_run:
        print(f"  [DRY RUN] Would ingest {len(files)} file(s) into {collection_path}")
    else:
        print(f"  ✅ Ingested {ok}/{len(files)} file(s) into {collection_path}")
    print(f"{'─'*55}")
