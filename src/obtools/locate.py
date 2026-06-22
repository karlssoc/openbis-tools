"""
Locate datasets by filename pattern or a list of filenames.

Two modes:
  --pattern REGEX     Scan file_list of each dataset in --collection(s).
                      Reliable but requires one API call per dataset.

  --from-file FILE    Read filenames (one per line), query by file_name
                      property. Fast: fetches all datasets per collection
                      with properties inline, then matches client-side.
                      Requires --collection flag(s).
"""

from __future__ import annotations

import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pybis import Openbis


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def locate_datasets(
    o: Openbis,
    *,
    pattern: str | None = None,
    from_file: str | None = None,
    collections: list[str] | None = None,
    dataset_type: str = "RAW_DATA",
    save: str | None = None,
    jobs: int = 16,
) -> list[dict]:
    if not collections:
        print("❌ At least one --collection is required")
        sys.exit(1)

    if from_file:
        results = _locate_by_property(o, from_file, collections=collections,
                                      dataset_type=dataset_type, jobs=jobs)
    elif pattern:
        results = _locate_by_filelist(o, pattern, collections=collections,
                                      dataset_type=dataset_type, jobs=jobs)
    else:
        print("❌ Provide --pattern or --from-file")
        sys.exit(1)

    results.sort(key=lambda x: x["filename"])
    print(f"\nFound {len(results)} match(es).")
    for r in results:
        print(f"  {r['filename']}  →  {r['dataset_code']}  ({r['collection']})")

    if save:
        out = Path(save)
        with open(out, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["filename", "dataset_code", "collection"])
            writer.writeheader()
            writer.writerows(results)
        print(f"Saved {len(results)} rows → {out}")

    return results


# ---------------------------------------------------------------------------
# Mode 1: property-based lookup (fast — bulk fetch with props inline)
# ---------------------------------------------------------------------------

def _locate_by_property(
    o: Openbis,
    from_file: str,
    *,
    collections: list[str],
    dataset_type: str,
    jobs: int,
) -> list[dict]:
    filenames = _read_filenames(from_file)
    fname_set = set(filenames)
    print(f"Matching {len(fname_set)} filename(s) against collections ...")

    results: list[dict] = []

    for coll in collections:
        print(f"  Fetching {coll} ...", end=" ", flush=True)
        try:
            # Request all properties inline to avoid per-dataset API calls
            hits = o.get_datasets(experiment=coll, type=dataset_type, props="*")
        except Exception:
            try:
                hits = o.get_datasets(experiment=coll, type=dataset_type)
            except Exception as exc:
                print(f"❌ {exc}")
                continue

        if hits is None or len(hits) == 0:
            print("0 datasets")
            continue

        rows = list(hits.itertuples()) if hasattr(hits, "itertuples") else list(hits)
        print(f"{len(rows)} datasets", end=" ", flush=True)

        # Fast path: file_name property is a column in the DataFrame
        inline = _match_inline(rows, fname_set, coll)
        if inline is not None:
            print(f"→ {len(inline)} match(es) [inline props]")
            results.extend(inline)
            continue

        # Slow path: fetch each dataset individually to read props
        print(f"→ fetching props individually ...")
        slow = _match_via_fetch(o, rows, fname_set, coll, jobs)
        print(f"     → {len(slow)} match(es)")
        results.extend(slow)

    return results


def _match_inline(rows: list, fname_set: set, coll: str) -> list[dict] | None:
    """Match file_name from DataFrame row attributes — no extra API calls.
    Returns None if file_name property is not present in the rows at all.
    """
    results: list[dict] = []
    prop_seen = False

    for row in rows:
        # pybis may lowercase property codes as column names
        fname = (
            getattr(row, "file_name", None)
            or getattr(row, "FILE_NAME", None)
            or getattr(row, "fileName", None)
        )
        if fname is not None:
            prop_seen = True
            if fname in fname_set:
                code = getattr(row, "permId", None) or getattr(row, "code", None)
                results.append({"filename": fname, "dataset_code": code or "?",
                                 "collection": coll})

    return results if prop_seen else None


def _match_via_fetch(
    o: Openbis,
    rows: list,
    fname_set: set,
    coll: str,
    jobs: int,
) -> list[dict]:
    """Fetch each dataset to read file_name property. Parallel."""
    codes = [getattr(r, "permId", None) or getattr(r, "code", None) for r in rows]
    codes = [c for c in codes if c]

    results: list[dict] = []

    def check(code: str) -> dict | None:
        try:
            ds = o.get_dataset(code)
            fname = (
                ds.props.get("file_name")
                or ds.props.get("FILE_NAME")
                or (Path(ds.file_list[0]).name if ds.file_list else None)
            )
            if fname and fname in fname_set:
                return {"filename": fname, "dataset_code": code, "collection": coll}
        except Exception:
            pass
        return None

    done = 0
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(check, c): c for c in codes}
        for fut in as_completed(futures):
            done += 1
            if done % 50 == 0 or done == len(codes):
                print(f"     {done}/{len(codes)}", end="\r", flush=True)
            r = fut.result()
            if r:
                results.append(r)

    return results


# ---------------------------------------------------------------------------
# Mode 2: file_list scan (exhaustive — fetches file list per dataset)
# ---------------------------------------------------------------------------

def _locate_by_filelist(
    o: Openbis,
    pattern: str,
    *,
    collections: list[str],
    dataset_type: str,
    jobs: int,
) -> list[dict]:
    rx = re.compile(pattern)

    all_codes: list[tuple[str, str]] = []
    for coll in collections:
        print(f"  Fetching {coll} ...", end=" ", flush=True)
        try:
            hits = o.get_datasets(experiment=coll, type=dataset_type)
        except Exception as exc:
            print(f"❌ {exc}")
            continue
        if hits is None or len(hits) == 0:
            print("0 datasets")
            continue
        rows = list(hits.itertuples()) if hasattr(hits, "itertuples") else list(hits)
        codes = [getattr(r, "permId", None) or getattr(r, "code", None) for r in rows]
        codes = [c for c in codes if c]
        all_codes.extend((c, coll) for c in codes)
        print(f"{len(codes)} datasets")

    total = len(all_codes)
    print(f"\nScanning {total} datasets for pattern '{pattern}' ({jobs} workers) ...")

    results: list[dict] = []
    done_count = 0

    def check(code: str, coll: str) -> list[dict]:
        try:
            ds = o.get_dataset(code)
            return [
                {"filename": Path(fp).name, "dataset_code": code, "collection": coll}
                for fp in (ds.file_list or [])
                if rx.search(Path(fp).name)
            ]
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(check, c, col): (c, col) for c, col in all_codes}
        for fut in as_completed(futures):
            done_count += 1
            if done_count % 50 == 0 or done_count == total:
                print(f"  ... {done_count}/{total}", end="\r", flush=True)
            results.extend(fut.result())

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_filenames(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        print(f"❌ File not found: {path}")
        sys.exit(1)
    lines = [ln.strip() for ln in p.read_text().splitlines()]
    names = [ln for ln in lines if ln and not ln.startswith("#")]
    print(f"Read {len(names)} filename(s) from {p.name}")
    return names
