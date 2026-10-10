"""
Locate datasets by filename pattern or a list of filenames.

Without --collection (recommended):
  One bulk query over all datasets of --dataset-type (optionally bounded by
  --registration-date) with the FILE_NAME property inline, matched client-side.
  FILE_NAME is set on RAW datasets from both the datamover (/MS_DATA/...) and
  DDB/obtools registrations, so you don't need to know where a run landed.

With --collection(s):
  --pattern REGEX     Scan file_list of each dataset in the collection(s).
                      Exhaustive but one API call per dataset.
  --from-file FILE    Bulk fetch per collection with props inline, match
                      FILE_NAME client-side.

Output rows carry md5 and size (from MD5_CHECKSUM / FILE_SIZE) and a
`duplicate` flag when the same filename is registered more than once.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pybis import Openbis

FIELDS = ["filename", "dataset_code", "collection", "md5", "size",
          "registration_date", "duplicate"]

_INLINE_PROPS = ["FILE_NAME", "MD5_CHECKSUM", "FILE_SIZE"]


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
    registration_date: str | None = None,
    save: str | None = None,
    jobs: int = 16,
) -> list[dict]:
    if not (pattern or from_file):
        print("❌ Provide --pattern or --from-file")
        sys.exit(1)

    if from_file:
        fname_set = set(_read_filenames(from_file))
        match = fname_set.__contains__
    else:
        rx = re.compile(pattern)
        match = lambda name: bool(rx.search(name))

    sink = _CsvSink(save) if save else None
    try:
        if not collections:
            results = _locate_global(o, match, dataset_type=dataset_type,
                                     registration_date=registration_date, sink=sink)
        elif from_file:
            results = _locate_by_property(o, match, collections=collections,
                                          dataset_type=dataset_type,
                                          registration_date=registration_date,
                                          jobs=jobs, sink=sink)
        else:
            results = _locate_by_filelist(o, match, collections=collections,
                                          dataset_type=dataset_type,
                                          registration_date=registration_date,
                                          jobs=jobs, sink=sink)
    finally:
        if sink:
            sink.close()

    counts = Counter(r["filename"] for r in results)
    for r in results:
        r["duplicate"] = counts[r["filename"]] > 1
    results.sort(key=lambda x: (x["filename"], str(x["registration_date"])))

    n_dup = sum(1 for c in counts.values() if c > 1)
    print(f"\nFound {len(results)} match(es) for {len(counts)} filename(s)"
          + (f"; {n_dup} registered more than once" if n_dup else "") + ".")
    for r in results:
        flag = "  [dup]" if r["duplicate"] else ""
        print(f"  {r['filename']}  →  {r['dataset_code']}  ({r['collection']}){flag}")

    if from_file:
        missing = sorted(fname_set - set(counts))
        if missing:
            print(f"\n⚠️  {len(missing)} filename(s) not found:")
            for m in missing:
                print(f"  {m}")

    if save:
        # Rewrite sorted, with the duplicate flag (rows were streamed during the scan)
        _write_csv(Path(save), results)
        print(f"Saved {len(results)} rows → {save}")

    return results


# ---------------------------------------------------------------------------
# Mode 0: global bulk query on FILE_NAME (no collection needed)
# ---------------------------------------------------------------------------

def _locate_global(o: Openbis, match, *, dataset_type: str,
                   registration_date: str | None, sink) -> list[dict]:
    where = f" registered {registration_date}" if registration_date else ""
    print(f"Fetching all {dataset_type} datasets{where} (FILE_NAME inline) ...",
          end=" ", flush=True)
    kwargs = {"registrationDate": registration_date} if registration_date else {}
    hits = o.get_datasets(type=dataset_type, count=None, props=_INLINE_PROPS, **kwargs)
    rows = _rows(hits)
    print(f"{len(rows)} datasets")

    results = []
    for row in rows:
        r = _row_result(row, None)
        if r and match(r["filename"]):
            results.append(r)
            if sink:
                sink.write(r)
    return results


# ---------------------------------------------------------------------------
# Mode 1: property-based lookup per collection (bulk fetch with props inline)
# ---------------------------------------------------------------------------

def _locate_by_property(o: Openbis, match, *, collections: list[str],
                        dataset_type: str, registration_date: str | None,
                        jobs: int, sink) -> list[dict]:
    kwargs = {"registrationDate": registration_date} if registration_date else {}
    results: list[dict] = []

    for coll in collections:
        print(f"  Fetching {coll} ...", end=" ", flush=True)
        try:
            hits = o.get_datasets(experiment=coll, type=dataset_type, props="*", **kwargs)
        except Exception:
            try:
                hits = o.get_datasets(experiment=coll, type=dataset_type, **kwargs)
            except Exception as exc:
                print(f"❌ {exc}")
                continue

        rows = _rows(hits)
        if not rows:
            print("0 datasets")
            continue
        print(f"{len(rows)} datasets", end=" ", flush=True)

        # Fast path: FILE_NAME property is a column in the DataFrame
        inline = _match_inline(rows, match, coll)
        if inline is not None:
            print(f"→ {len(inline)} match(es) [inline props]")
            found = inline
        else:
            # Slow path: fetch each dataset individually to read props
            print("→ fetching props individually ...")
            found = _match_via_fetch(o, rows, match, coll, jobs)
            print(f"     → {len(found)} match(es)")

        results.extend(found)
        if sink:
            for r in found:
                sink.write(r)

    return results


def _match_inline(rows: list, match, coll: str) -> list[dict] | None:
    """Match FILE_NAME from DataFrame row attributes — no extra API calls.
    Returns None if the FILE_NAME property is not present in the rows at all.
    """
    results: list[dict] = []
    prop_seen = False
    for row in rows:
        r = _row_result(row, coll)
        if r is not None:
            prop_seen = True
            if match(r["filename"]):
                results.append(r)
    return results if prop_seen else None


def _match_via_fetch(o: Openbis, rows: list, match, coll: str, jobs: int) -> list[dict]:
    """Fetch each dataset to read the file_name property. Parallel."""
    codes = [c for c in (_code(r) for r in rows) if c]
    results: list[dict] = []

    def check(code: str) -> dict | None:
        try:
            ds = o.get_dataset(code)
            fname = (
                ds.props.get("file_name")
                or (Path(ds.file_list[0]).name if ds.file_list else None)
            )
            if fname and match(fname):
                return _ds_result(ds, fname, code, coll)
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

def _locate_by_filelist(o: Openbis, match, *, collections: list[str],
                        dataset_type: str, registration_date: str | None,
                        jobs: int, sink) -> list[dict]:
    kwargs = {"registrationDate": registration_date} if registration_date else {}

    all_codes: list[tuple[str, str]] = []
    for coll in collections:
        print(f"  Fetching {coll} ...", end=" ", flush=True)
        try:
            hits = o.get_datasets(experiment=coll, type=dataset_type, **kwargs)
        except Exception as exc:
            print(f"❌ {exc}")
            continue
        codes = [c for c in (_code(r) for r in _rows(hits)) if c]
        if not codes:
            print("0 datasets")
            continue
        all_codes.extend((c, coll) for c in codes)
        print(f"{len(codes)} datasets")

    total = len(all_codes)
    print(f"\nScanning {total} datasets ({jobs} workers) ...")

    results: list[dict] = []
    done_count = 0

    def check(code: str, coll: str) -> list[dict]:
        try:
            ds = o.get_dataset(code)
            return [
                _ds_result(ds, Path(fp).name, code, coll)
                for fp in (ds.file_list or [])
                if match(Path(fp).name)
            ]
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(check, c, col): (c, col) for c, col in all_codes}
        for fut in as_completed(futures):
            done_count += 1
            if done_count % 50 == 0 or done_count == total:
                print(f"  ... {done_count}/{total}", end="\r", flush=True)
            found = fut.result()
            results.extend(found)
            if sink:
                for r in found:
                    sink.write(r)

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rows(hits) -> list:
    if hits is None or len(hits) == 0:
        return []
    df = getattr(hits, "df", hits)          # pybis Things → DataFrame (props as columns)
    return list(df.itertuples()) if hasattr(df, "itertuples") else list(df)


def _code(row) -> str | None:
    return getattr(row, "permId", None) or getattr(row, "code", None)


def _attr(row, name: str):
    """Read a property column; pybis may return it upper- or lower-case."""
    val = getattr(row, name, None)
    if val is None:
        val = getattr(row, name.lower(), None)
    return None if val != val else val    # NaN → None


def _row_result(row, coll: str | None) -> dict | None:
    """Build a result dict from a DataFrame row, or None if it has no FILE_NAME."""
    fname = _attr(row, "FILE_NAME")
    if fname is None:
        return None
    return {
        "filename": fname,
        "dataset_code": _code(row) or "?",
        "collection": coll or getattr(row, "experiment", ""),
        "md5": _attr(row, "MD5_CHECKSUM") or "",
        "size": _attr(row, "FILE_SIZE") or "",
        "registration_date": getattr(row, "registrationDate", ""),
    }


def _ds_result(ds, fname: str, code: str, coll: str) -> dict:
    return {
        "filename": fname,
        "dataset_code": code,
        "collection": coll,
        "md5": ds.props.get("md5_checksum") or "",
        "size": ds.props.get("file_size") or "",
        "registration_date": getattr(ds, "registrationDate", ""),
    }


class _CsvSink:
    """Append rows as they are found so an interrupted scan keeps its progress."""

    def __init__(self, path: str):
        self._fh = open(path, "w", newline="")
        self._w = csv.DictWriter(self._fh, fieldnames=FIELDS, extrasaction="ignore")
        self._w.writeheader()
        self._fh.flush()

    def write(self, row: dict):
        self._w.writerow(row)
        self._fh.flush()

    def close(self):
        self._fh.close()


def _write_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _read_filenames(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        print(f"❌ File not found: {path}")
        sys.exit(1)
    lines = [ln.strip() for ln in p.read_text().splitlines()]
    names = [ln for ln in lines if ln and not ln.startswith("#")]
    print(f"Read {len(names)} filename(s) from {p.name}")
    return names
