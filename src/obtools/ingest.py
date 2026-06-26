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

import datetime
import json
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

from pybis import Openbis

from .paths import config_root

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
# Metadata extraction
# ---------------------------------------------------------------------------

def _bruker_acquisition_date(d_dir: Path) -> str | None:
    """
    Read acquisition datetime from a Bruker timsTOF analysis.tdf SQLite file.
    Returns an ISO 8601 string, or None if unavailable.
    """
    tdf = d_dir / "analysis.tdf"
    if not tdf.exists():
        return None
    try:
        with sqlite3.connect(str(tdf)) as conn:
            row = conn.execute(
                "SELECT Value FROM GlobalMetadata WHERE Key='AcquisitionDateTime'"
            ).fetchone()
            if row:
                return row[0]
    except Exception:
        pass
    return None


def _file_mtime_iso(path: Path) -> str:
    """Return file modification time as ISO 8601 string (local timezone)."""
    mtime = path.stat().st_mtime
    return datetime.datetime.fromtimestamp(mtime).astimezone().isoformat()


def _build_dataset_props(
    raw: "RawFile",
    upload_path: Path,
    raw_instrument_sn: str,
    raw_instrument_name: str,
) -> dict:
    """
    Build a dict of OpenBIS dataset properties for a raw acquisition.

    - file_name / file_size: derived from the upload path
    - ACQUISITION_DATE: read from Bruker TDF, or file mtime for Thermo
    - INSTRUMENT_SN / INSTRUMENT_NAME: vendor-specific defaults
    """
    props: dict = {
        "file_name": raw.path.name,
        "file_size": str(upload_path.stat().st_size),
    }

    if raw.vendor == "bruker":
        props["INSTRUMENT_SN"] = "MS:1003404"
        props["INSTRUMENT_NAME"] = "timsTOF_HT"
        date = _bruker_acquisition_date(raw.path)
        props["ACQUISITION_DATE"] = date if date else _file_mtime_iso(raw.path)
    else:
        props["INSTRUMENT_SN"] = raw_instrument_sn
        props["INSTRUMENT_NAME"] = raw_instrument_name
        props["ACQUISITION_DATE"] = _file_mtime_iso(raw.path)

    return props


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
# Incremental ingest: ledger + time filters (for scheduled/unattended runs)
# ---------------------------------------------------------------------------

def _ledger_path() -> Path:
    """JSON ledger of already-uploaded files, under the portable config root."""
    return config_root() / "ingested.json"


def _load_ledger() -> dict:
    path = _ledger_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (ValueError, OSError):
            pass
    return {}


def _save_ledger(ledger: dict) -> None:
    path = _ledger_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ledger, indent=2))
    except OSError as exc:
        print(f"    ⚠️  Could not write ledger {path}: {exc}")


def _already_ingested(ledger: dict, collection: str, raw: RawFile) -> bool:
    """True if this file was uploaded before and is unchanged since (size + mtime).

    A re-acquired file reusing the same name has a different size/mtime, so it
    is re-uploaded rather than silently skipped. Bruker .d directories match on
    mtime only (a directory's own size is not meaningful).
    """
    entry = ledger.get(collection, {}).get(raw.path.name)
    if not entry:
        return False
    try:
        st = raw.path.stat()
    except OSError:
        return False
    if abs(entry.get("mtime", 0) - st.st_mtime) >= 1.0:
        return False
    return raw.is_dir or entry.get("size") == st.st_size


def _record_ingested(ledger: dict, collection: str, raw: RawFile, dataset_id: str) -> None:
    try:
        st = raw.path.stat()
    except OSError:
        return
    ledger.setdefault(collection, {})[raw.path.name] = {
        "size": st.st_size,
        "mtime": st.st_mtime,
        "dataset_id": dataset_id,
        "uploaded_at": datetime.datetime.now().astimezone().isoformat(),
    }


def _mtime_dt(raw: RawFile) -> datetime.datetime:
    """File modification time as a timezone-aware (local) datetime."""
    return datetime.datetime.fromtimestamp(raw.path.stat().st_mtime).astimezone()


def _age_minutes(raw: RawFile) -> float:
    """Minutes since the file was last modified (proxy for 'still acquiring')."""
    return (datetime.datetime.now().timestamp() - raw.path.stat().st_mtime) / 60.0


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
    props: dict,
    dry_run: bool,
) -> str | None:
    """Upload a file as a dataset. Returns permId or None on failure."""
    size_mb = file_path.stat().st_size / 1_048_576
    print(f"    ⬆️  {file_path.name}  ({size_mb:.1f} MB)")

    if dry_run:
        print(f"    [DRY RUN] Would upload dataset  (type: {dataset_type})")
        for k, v in props.items():
            print(f"              {k} = {v}")
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
            except Exception as exc:
                print(f"    ⚠️  Could not link sample {sample_id}: {exc}")
        skipped: list[str] = []
        for key, value in props.items():
            try:
                ds.props[key] = value
            except Exception:
                skipped.append(key)   # unknown property for this dataset type
        if skipped:
            print(f"    ⚠️  Properties not set (unknown for {dataset_type}): {', '.join(skipped)}")
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
    skip_existing: bool = False,
    min_age_minutes: float = 0,
    since: datetime.datetime | None = None,
    raw_instrument_sn: str = "MS:1000529",
    raw_instrument_name: str = "Q_Exactive_HF-X_Orbitrap",
    dry_run: bool = False,
) -> None:
    """
    Full ingest workflow: discover → archive Bruker dirs → create samples → upload datasets.

    For scheduled/unattended QC uploads, set skip_existing (skip files recorded
    in the ledger), min_age_minutes (skip files still being acquired), and/or
    since (skip files modified before this datetime).
    """
    source_path = Path(source)

    # 1. Discover raw files
    print(f"\n🔍 Scanning: {source_path}")
    files = discover(source_path)

    if not files:
        print("  ℹ️  No .raw files or .d directories found.")
        return

    # 1b. Incremental filters (no-ops unless the corresponding option is set)
    ledger = _load_ledger()
    if skip_existing or min_age_minutes or since:
        kept: list[RawFile] = []
        for f in files:
            if since and _mtime_dt(f) < since:
                print(f"    ⏭️  Skipping (before --since): {f.path.name}")
            elif min_age_minutes and _age_minutes(f) < min_age_minutes:
                print(f"    ⏳ Skipping (modified < {min_age_minutes:g} min ago, may still be acquiring): {f.path.name}")
            elif skip_existing and _already_ingested(ledger, collection_path, f):
                print(f"    ✓ Already ingested: {f.path.name}")
            else:
                kept.append(f)
        files = kept
        if not files:
            print("\n  ℹ️  Nothing new to ingest.")
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

        props = _build_dataset_props(raw, upload_path, raw_instrument_sn, raw_instrument_name)
        ds_id = _upload_dataset(o, collection_path, upload_path, dataset_type, sample_id, props, dry_run)
        if ds_id:
            print(f"    📊 Dataset: {ds_id}")
            if not dry_run:
                # Save incrementally so a crash/reboot never re-uploads done files.
                _record_ingested(ledger, collection_path, raw, ds_id)
                _save_ledger(ledger)

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
