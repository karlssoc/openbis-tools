"""
Search OpenBIS for datasets, samples, and experiments.

Supports basic keyword search and advanced filtering (space, type,
property values, date range, relationship queries).
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

from pybis import Openbis


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def search_datasets(
    o: Openbis,
    query: str | None = None,
    *,
    limit: int = 20,
    space: str | None = None,
    dataset_type: str | None = None,
    property_code: str | None = None,
    property_value: str | None = None,
    registration_date: str | None = None,
    children_of: str | None = None,
    parents_of: str | None = None,
    save: str | None = None,
) -> list[dict]:
    """Search datasets and optionally save results to CSV."""

    if children_of:
        results = _get_children(o, children_of)
    elif parents_of:
        results = _get_parents(o, parents_of)
    else:
        results = _search(o, query, limit, space, dataset_type, property_code, property_value, registration_date)

    _print_results(results)

    if save and results:
        _save_csv(results, save)

    return results


def search_samples(o: Openbis, query: str, limit: int = 20) -> list[dict]:
    print(f"🧪 Samples matching '{query}':")
    try:
        hits = o.get_samples(code=f"*{query}*")
        return _process(hits, "sample", limit)
    except Exception as exc:
        print(f"  ❌ {exc}")
        return []


def search_experiments(o: Openbis, query: str, limit: int = 20) -> list[dict]:
    print(f"🔬 Experiments matching '{query}':")
    try:
        hits = o.get_experiments(code=f"*{query}*")
        return _process(hits, "experiment", limit)
    except Exception as exc:
        print(f"  ❌ {exc}")
        return []


# ---------------------------------------------------------------------------
# Relationship queries
# ---------------------------------------------------------------------------

def _get_children(o: Openbis, parent_code: str) -> list[dict]:
    print(f"📥 Children of {parent_code}:")
    try:
        hits = o.get_datasets(withParents=parent_code)
        return _process(hits, "dataset")
    except Exception as exc:
        print(f"  ❌ {exc}")
        return []


def _get_parents(o: Openbis, child_code: str) -> list[dict]:
    print(f"📤 Parents of {child_code}:")
    try:
        ds = o.get_dataset(child_code)
        parents = ds.parents
        if not parents:
            print("  ℹ️  No parents found.")
            return []
        return _process(parents, "dataset")
    except Exception as exc:
        print(f"  ❌ {exc}")
        return []


# ---------------------------------------------------------------------------
# Filtered search
# ---------------------------------------------------------------------------

def _search(
    o,
    query,
    limit,
    space,
    dataset_type,
    property_code,
    property_value,
    registration_date,
) -> list[dict]:
    kwargs: dict = {}

    if space:
        kwargs["space"] = space
    if dataset_type:
        kwargs["type"] = dataset_type
    if property_code and property_value:
        kwargs["props"] = {property_code: f"*{property_value}*"}
    if query:
        kwargs["code"] = f"*{query}*"

    print(f"🔍 Searching datasets...")
    try:
        hits = o.get_datasets(**kwargs)
    except Exception as exc:
        print(f"  ❌ Search failed: {exc}")
        return []

    results = _process(hits, "dataset", limit)

    # Client-side date filter (pybis may not support server-side date filters)
    if registration_date and results:
        results = _filter_by_date(results, registration_date)

    return results


def _filter_by_date(results: list[dict], expr: str) -> list[dict]:
    """Filter by registration date. expr like '>2024-01-01' or '<2024-12-31'."""
    try:
        op = expr[0]
        cutoff = datetime.fromisoformat(expr[1:].strip())
    except (ValueError, IndexError):
        print(f"  ⚠️  Invalid date filter '{expr}' — ignored. Use format '>YYYY-MM-DD'.")
        return results

    filtered = []
    for r in results:
        raw = r.get("registration_date", "")
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw)[:10])
            if (op == ">" and dt > cutoff) or (op == "<" and dt < cutoff):
                filtered.append(r)
        except ValueError:
            pass
    return filtered


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _process(hits, obj_type: str, limit: int = 0) -> list[dict]:
    if hits is None or len(hits) == 0:
        return []

    results: list[dict] = []
    rows = list(hits.itertuples()) if hasattr(hits, "itertuples") else list(hits)
    if limit:
        rows = rows[:limit]

    for row in rows:
        code = getattr(row, "permId", None) or getattr(row, "code", None)
        results.append({
            "type": obj_type,
            "code": code or "?",
            "object_type": getattr(row, "type", "N/A"),
            "registration_date": str(getattr(row, "registrationDate", "") or ""),
        })
    return results


def _print_results(results: list[dict]) -> None:
    if not results:
        print("  ℹ️  No results.")
        return
    print(f"  Found {len(results)} result(s):")
    for r in results:
        print(f"    • {r['code']}  [{r['object_type']}]  {r['registration_date']}")


def _save_csv(results: list[dict], path: str) -> None:
    out = Path(path)
    try:
        with open(out, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        print(f"  💾 Saved {len(results)} rows to {out}")
    except Exception as exc:
        print(f"  ❌ Could not save CSV: {exc}")
