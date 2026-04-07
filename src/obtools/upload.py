"""
Upload workflows for proteomics datasets.

Supports FASTA databases, spectral libraries, and generic analyzed data.
All uploaders share a common base; subclasses handle metadata extraction
and dataset naming specific to each file type.
"""

from __future__ import annotations

import fnmatch
import sys
import tempfile
import zipfile
from pathlib import Path

from pybis import Openbis

from .diann import parse_diann_log, parse_fasta_metadata
from .autolink import suggest_parents, interactive_confirm


# ---------------------------------------------------------------------------
# Folder helpers
# ---------------------------------------------------------------------------

def _matches_any_exclude(rel_path: str, excludes: list[str]) -> bool:
    """Return True if rel_path (or its basename) matches any exclude glob pattern."""
    name = Path(rel_path).name
    return any(fnmatch.fnmatch(rel_path, p) or fnmatch.fnmatch(name, p) for p in excludes)


def _collect_folder_files(folder: Path, excludes: list[str]) -> tuple[list[Path], list[Path]]:
    """Walk folder, split files into included/excluded based on patterns."""
    included, excluded = [], []
    for f in sorted(folder.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(folder.parent))
        (excluded if _matches_any_exclude(rel, excludes) else included).append(f)
    return included, excluded


def _zip_folder(folder: Path, excludes: list[str]) -> Path:
    """Zip folder contents into a temp file, preserving structure from folder's parent."""
    included, _ = _collect_folder_files(folder, excludes)
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False, prefix=f"{folder.name}_")
    tmp.close()
    zip_path = Path(tmp.name)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in included:
            zf.write(f, f.relative_to(folder.parent))
    return zip_path


# ---------------------------------------------------------------------------
# File-type detection
# ---------------------------------------------------------------------------

def detect_file_type(file_path: str) -> str:
    """Infer file type from extension/name. Returns 'fasta', 'spectral_library', or 'unknown'."""
    p = Path(file_path)
    suffix = p.suffix.lower()
    stem = p.stem.lower()

    if suffix in (".fasta", ".fa", ".fas"):
        return "fasta"
    if suffix in (".speclib", ".sptxt"):
        return "spectral_library"
    if suffix in (".tsv", ".csv") and "lib" in stem:
        return "spectral_library"
    return "unknown"


# ---------------------------------------------------------------------------
# Base uploader
# ---------------------------------------------------------------------------

# Default OpenBIS collections by file type (can be overridden per call)
_DEFAULT_COLLECTIONS = {
    "fasta":            "/DDB/CK/FASTA",
    "spectral_library": "/DDB/CK/PREDSPECLIB",
    "unknown":          "/DDB/CK/UNKNOWN",
}

_DEFAULT_TYPES = {
    "fasta":            "BIO_DB",
    "spectral_library": "SPECTRAL_LIBRARY",
    "unknown":          "UNKNOWN",
}

# Which OpenBIS property maps to the human-readable name per dataset type
_NAME_PROP = {
    "SPECTRAL_LIBRARY": "notes",   # SPECTRAL_LIBRARY has no $name property
}


class Uploader:
    """Base uploader. Subclasses override `parse_metadata` and `make_name`."""

    def __init__(self, o: Openbis):
        self.o = o

    # Subclass hooks
    def parse_metadata(self, file_path: Path, **kwargs) -> dict:
        return {}

    def make_name(self, file_path: Path, meta: dict, custom_name: str | None) -> str:
        return custom_name or file_path.stem

    # Main entry point
    def upload(
        self,
        file_path: str,
        *,
        dataset_type: str,
        collection: str,
        name: str | None = None,
        notes: str | None = None,
        parents: list[str] | None = None,
        extra_files: list[str] | None = None,
        auto_link: bool = False,
        dry_run: bool = False,
        exclude: list[str] | None = None,
        **kwargs,
    ):
        fp = Path(file_path)
        if not fp.exists():
            print(f"❌ Not found: {fp}")
            sys.exit(1)

        is_folder = fp.is_dir()
        meta = self.parse_metadata(fp, **kwargs)
        human_name = self.make_name(fp, meta, name)

        # Auto-link: suggest + confirm parent datasets interactively
        parent_list = list(parents or [])
        if auto_link:
            file_type = detect_file_type(str(fp))
            print("🔗 Auto-linking: searching for potential parent datasets...")
            suggestions = suggest_parents(self.o, str(fp), file_type, **kwargs)
            confirmed = interactive_confirm(suggestions)
            parent_list.extend(confirmed)

        if dry_run:
            if is_folder:
                self._show_dry_run_folder(fp, human_name, collection, dataset_type, notes, extra_files, parent_list, exclude or [])
            else:
                self._show_dry_run(fp, human_name, collection, dataset_type, notes, meta, extra_files, parent_list)
            return None

        if is_folder:
            zip_path = _zip_folder(fp, exclude or [])
            try:
                return self._perform_upload(zip_path, dataset_type, collection, human_name, notes, meta, extra_files, parent_list)
            finally:
                zip_path.unlink(missing_ok=True)

        return self._perform_upload(fp, dataset_type, collection, human_name, notes, meta, extra_files, parent_list)

    # ------------------------------------------------------------------

    def _show_dry_run_folder(self, fp, name, collection, ds_type, notes, extra_files, parents, excludes):
        included, excluded = _collect_folder_files(fp, excludes)
        print(f"\n🔍 Dry run — would zip and upload folder:")
        print(f"   Folder:       {fp}")
        print(f"   Name:         {name}")
        print(f"   Collection:   {collection}")
        print(f"   Dataset type: {ds_type}")
        print(f"   Files:        {len(included)} included")
        if excluded:
            print(f"   Excluded:     {len(excluded)} file(s)")
            for f in excluded[:5]:
                print(f"     {f.relative_to(fp.parent)}")
            if len(excluded) > 5:
                print(f"     ... and {len(excluded) - 5} more")
        if notes:
            print(f"   Notes:        {notes}")
        if extra_files:
            print(f"   Extra files:  {len(extra_files)}")
        if parents:
            print(f"   Parents:      {', '.join(parents)}")

    def _show_dry_run(self, fp, name, collection, ds_type, notes, meta, extra_files, parents):
        print(f"\n🔍 Dry run — would upload:")
        print(f"   File:         {fp}")
        print(f"   Name:         {name}")
        print(f"   Collection:   {collection}")
        print(f"   Dataset type: {ds_type}")
        if notes:
            print(f"   Notes:        {notes}")
        if extra_files:
            print(f"   Extra files:  {len(extra_files)}")
        if parents:
            print(f"   Parents:      {', '.join(parents)}")
        print(f"   Metadata ({len(meta)} fields):")
        for k, v in meta.items():
            print(f"     {k}: {v}")

    def _perform_upload(self, fp, ds_type, collection, human_name, notes, meta, extra_files, parents):
        print(f"\n🚀 Uploading to OpenBIS...")
        print(f"   File:         {fp}")
        print(f"   Collection:   {collection}")
        print(f"   Dataset type: {ds_type}")

        files = [str(fp)] + [str(f) for f in (extra_files or []) if Path(f).exists()]

        dataset = self.o.new_dataset(type=ds_type, experiment=collection, files=files)

        # Set human-readable name
        name_prop = _NAME_PROP.get(ds_type, "$name")
        self._set_prop(dataset, name_prop, human_name)

        # Apply metadata properties (server will silently ignore unknown ones)
        for k, v in meta.items():
            self._set_prop(dataset, k.lower(), str(v))

        if notes:
            self._set_prop(dataset, "notes", notes)

        print("💾 Saving dataset...")
        dataset.save()

        if parents:
            try:
                dataset.add_parents(parents)
                print(f"🔗 Linked to {len(parents)} parent(s): {', '.join(parents)}")
            except Exception as exc:
                print(f"⚠️  Could not link parents: {exc}")

        print(f"✅ Done — dataset code: {dataset.code}")
        return dataset

    @staticmethod
    def _set_prop(dataset, prop: str, value):
        try:
            dataset.props[prop] = value
        except Exception:
            pass   # Unknown property — server will reject; we move on silently


# ---------------------------------------------------------------------------
# File-type–specific uploaders
# ---------------------------------------------------------------------------

class FastaUploader(Uploader):
    def parse_metadata(self, fp, version=None, **kwargs):
        return parse_fasta_metadata(str(fp), version)

    def make_name(self, fp, meta, custom_name):
        if custom_name:
            return custom_name
        name = fp.stem
        if "VERSION" in meta:
            name += f" v{meta['VERSION']}"
        if "PRIMARY_SPECIES" in meta:
            name += f" ({meta['PRIMARY_SPECIES']})"
        return name


class SpectralLibraryUploader(Uploader):
    def parse_metadata(self, fp, log_file=None, **kwargs):
        if log_file and Path(log_file).exists():
            return parse_diann_log(log_file)
        return {}

    def make_name(self, fp, meta, custom_name):
        if custom_name:
            return custom_name
        parts = [fp.stem]
        if "FASTA_DATABASE" in meta:
            parts.append(f"({Path(meta['FASTA_DATABASE']).stem})")
        if "N_PROTEINS" in meta:
            parts.append(f"{meta['N_PROTEINS']} proteins")
        if "DIANN_VERSION" in meta:
            parts.append(f"DIA-NN v{meta['DIANN_VERSION']}")
        return " ".join(parts)

    def upload(self, file_path, *, log_file=None, **kwargs):
        # Also upload the log file alongside the library
        extra = [log_file] if log_file and Path(log_file).exists() else None
        return super().upload(file_path, extra_files=extra, log_file=log_file, **kwargs)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_uploader(file_type: str, o: Openbis) -> Uploader:
    return {
        "fasta":            FastaUploader,
        "spectral_library": SpectralLibraryUploader,
    }.get(file_type, Uploader)(o)


def default_collection(file_type: str) -> str:
    return _DEFAULT_COLLECTIONS.get(file_type, _DEFAULT_COLLECTIONS["unknown"])


def default_dataset_type(file_type: str) -> str:
    return _DEFAULT_TYPES.get(file_type, _DEFAULT_TYPES["unknown"])
