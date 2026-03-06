"""
Parent-child dataset auto-linking.

Suggests OpenBIS parent datasets based on file metadata (DIA-NN logs,
FASTA filenames, version patterns) and lets the user confirm interactively.
"""

from __future__ import annotations

from pathlib import Path
from pybis import Openbis

from .diann import parse_diann_log


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def suggest_parents(o: Openbis, file_path: str, file_type: str, **kwargs) -> list[dict]:
    """
    Return up to 5 ranked parent-dataset suggestions.

    file_type: 'spectral_library' | 'fasta'
    kwargs:
        log_file  – path to DIA-NN log (for spectral_library)
        version   – version string (for fasta)
    """
    try:
        if file_type == "spectral_library":
            return _from_diann_log(o, kwargs.get("log_file"))[:5]
        elif file_type == "fasta":
            return _from_version_pattern(o, file_path, kwargs.get("version"))[:5]
    except Exception as exc:
        print(f"⚠️  Could not generate parent suggestions: {exc}")
    return []


def interactive_confirm(suggestions: list[dict]) -> list[str]:
    """
    Present suggestions and return codes the user confirmed.

    Accepts: single numbers, comma-separated (1,3), ranges (1-3), 'all', or blank.
    """
    if not suggestions:
        return []

    print(f"\n📋 {len(suggestions)} potential parent dataset(s) found:")
    print("=" * 60)
    for i, s in enumerate(suggestions, 1):
        icon = "🎯" if s.get("confidence") == "high" else "🔍"
        print(f"{icon} [{i}] {s['code']}")
        print(f"     Name:  {s.get('name', 'N/A')}")
        print(f"     Type:  {s.get('type', 'N/A')}")
        print(f"     Date:  {s.get('registration_date', 'N/A')}")
        print(f"     Match: {s.get('match_reason', '')}")
        print()

    print("Select datasets to link as parents (e.g. '1', '1,3', '1-3', 'all', or Enter to skip):")
    try:
        raw = input("👉 ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSkipped.")
        return []

    if not raw:
        return []
    if raw.lower() == "all":
        return [s["code"] for s in suggestions]

    chosen: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if "-" in part:
            try:
                start, end = part.split("-", 1)
                chosen += [suggestions[i]["code"] for i in range(int(start) - 1, int(end))]
            except (ValueError, IndexError):
                print(f"  ⚠️  Skipping invalid range: {part}")
        else:
            try:
                chosen.append(suggestions[int(part) - 1]["code"])
            except (ValueError, IndexError):
                print(f"  ⚠️  Skipping invalid selection: {part}")

    for code in chosen:
        print(f"  ✅ Linked: {code}")
    return chosen


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _search_by_terms(o: Openbis, terms: list[str]) -> list[dict]:
    """Search datasets matching any of the given terms (name/code wildcard)."""
    seen: set[str] = set()
    results: list[dict] = []

    for term in terms:
        if not term or len(term) < 3:
            continue
        try:
            datasets = o.get_datasets(code=f"*{term}*")
            if datasets is None or len(datasets) == 0:
                continue
            for ds in (datasets.itertuples() if hasattr(datasets, "itertuples") else datasets):
                code = getattr(ds, "code", None) or getattr(ds, "permId", None)
                if not code or code in seen:
                    continue
                seen.add(code)
                results.append({
                    "code": code,
                    "type": getattr(ds, "type", "N/A"),
                    "name": getattr(ds, "name", "") or "",
                    "registration_date": str(getattr(ds, "registrationDate", "") or ""),
                    "match_reason": f"matched term: {term}",
                    "confidence": "medium",
                })
        except Exception:
            pass

    return results


def _from_diann_log(o: Openbis, log_file: str | None) -> list[dict]:
    """Suggest FASTA parent datasets referenced in a DIA-NN log."""
    if not log_file or not Path(log_file).exists():
        return []

    meta = parse_diann_log(log_file)
    fasta_db = meta.get("FASTA_DATABASE")
    if not fasta_db:
        return []

    print(f"  🔍 Looking for FASTA database: {fasta_db}")
    terms = [fasta_db, Path(fasta_db).stem]
    results = _search_by_terms(o, terms)
    for r in results:
        r["match_reason"] = f"FASTA database reference: {fasta_db}"
        r["confidence"] = "high"
    return results


def _from_version_pattern(o: Openbis, fasta_file: str, version: str | None) -> list[dict]:
    """Suggest parent FASTA datasets based on naming/versioning patterns."""
    stem = Path(fasta_file).stem
    terms = [stem.split("_")[0] if "_" in stem else stem]
    if version:
        terms.append(stem.replace(version, ""))
    results = _search_by_terms(o, terms)
    for r in results:
        r["match_reason"] = f"similar naming pattern: {terms[0]}"
        r["confidence"] = "medium"
    return results
