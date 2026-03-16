"""
Generate HyStar sequence files (.xlsx) for the Bruker TimsTOF HT + EvoSep One (Timmie).

The generated file has a single sheet named SampleTable with 13 columns matching
the format exported by HyStar / Bruker timsControl.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Windows paths used on the Timmie acquisition PC
# ---------------------------------------------------------------------------

_LC_BASE = r"D:\Methods\EvoSep"
_MS_BASE = r"D:\Methods\Default Application Methods\OTOF\timsTOF HT\Proteomics TIMS on"
_ACQ_EXECUTE   = r"C:\apps\datamover\run_batchfile_hidden_single_file_upload.vbs"
_ACQ_PARAMETER = r"C:\apps\datamover\run_datamover_single_file_upload.bat"

# ---------------------------------------------------------------------------
# Method catalogue
# ---------------------------------------------------------------------------

# Key → filename stem (no path prefix, no extension suffix)
LC_METHODS: dict[str, str] = {
    "30spd":  "30 Samples per day",
    "60spd":  "60 Samples per day",
    "100spd": "100 Samples per day",
    "200spd": "200 Samples per day",
    "300spd": "300 Samples per day",
}

MS_METHODS: dict[str, str] = {
    "dia-long":  "dia-PASEF - long gradient",
    "dia-short": "dia-PASEF - short gradient",
    "dda":       "DDA PASEF-standard_1.1sec_cycletime",
    "phospho":   "dia-PASEF_Phosphopeptides_0.65-1.45_1.38sec-cycletime",
    "p2":        "diaPASEF_P2_V02",
}

# Recommended MS method per LC method (gradient / cycle-time match)
_LC_DEFAULT_MS: dict[str, str] = {
    "30spd":  "dia-long",   # 30 SPD → long gradient, 1.1 sec cycletime
    "60spd":  "dia-short",
    "100spd": "dia-short",
    "200spd": "dia-short",
    "300spd": "dia-short",
}


def _lc_path(key: str) -> str:
    return rf"{_LC_BASE}\{LC_METHODS[key]}.m?HyStar_LC"


def _ms_path(key: str) -> str:
    return rf"{_MS_BASE}\{MS_METHODS[key]}.m?OtofImpacTEMControl"


# ---------------------------------------------------------------------------
# Vial positions:  S{plate}-{row}{col}  e.g. S1-A1 … S1-H12, S2-A1 …
# Layout: A1→A12, B1→B12, … H1→H12  (96 wells per plate)
# ---------------------------------------------------------------------------

_ROWS = "ABCDEFGH"


def _vial(i: int, start_plate: int = 1) -> str:
    """Return vial string for 0-indexed absolute position (wraps every 96)."""
    plate = start_plate + i // 96
    pos = i % 96
    row = _ROWS[pos // 12]
    col = (pos % 12) + 1
    return f"S{plate}-{row}{col}"


# ---------------------------------------------------------------------------
# Row dataclass
# ---------------------------------------------------------------------------

@dataclass
class SeqRow:
    sample_id:    str
    openbis_code: str = ""
    comment:      str = ""


# ---------------------------------------------------------------------------
# DataFrame builder + XLSX writer
# ---------------------------------------------------------------------------

_COLUMNS = [
    "Vial", "Sample ID", "Method Set", "Separation Method", "Injection Method",
    "MS Method", "Processing Method", "ACQEnd_Execute", "ACQEnd_Parameter",
    "Data Path", "Sample Comment", "Openbis_Sample_ID", "BPS Token",
]


def build_df(
    rows: list[SeqRow],
    *,
    lc_key: str = "30spd",
    ms_key: str = "dia-long",
    data_path: str,
    start_plate: int = 1,
) -> "pd.DataFrame":
    """Build a sequence DataFrame from a list of SeqRow entries."""
    try:
        import pandas as pd
    except ImportError:
        print("❌ pandas is required: pip install pandas openpyxl")
        sys.exit(1)

    lc = _lc_path(lc_key)
    ms = _ms_path(ms_key)

    records = []
    for i, row in enumerate(rows):
        records.append({
            "Vial":             _vial(i, start_plate),
            "Sample ID":        row.sample_id,
            "Method Set":       None,
            "Separation Method": lc,
            "Injection Method": "Standard",
            "MS Method":        ms,
            "Processing Method": None,
            "ACQEnd_Execute":   _ACQ_EXECUTE,
            "ACQEnd_Parameter": _ACQ_PARAMETER,
            "Data Path":        data_path,
            "Sample Comment":   row.comment or None,
            "Openbis_Sample_ID": row.openbis_code or None,
            "BPS Token":        None,
        })
    return pd.DataFrame(records, columns=_COLUMNS)


def write_xlsx(df: "pd.DataFrame", path: Path) -> None:
    """Write the sequence DataFrame to an XLSX file with sheet name SampleTable."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("❌ openpyxl is required: pip install pandas openpyxl")
        sys.exit(1)
    df.to_excel(path, sheet_name="SampleTable", index=False)


def auto_filename(user: str, project: str, label: str) -> str:
    yymm = datetime.now().strftime("%y%m")
    label_safe = label.strip().replace(" ", "_")
    return f"{user}_T{yymm}_{project}_{label_safe}.xlsx"


# ---------------------------------------------------------------------------
# Interactive helpers
# ---------------------------------------------------------------------------

def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val if val else (default or "")


def _choose(label: str, options: list[str], default_idx: int = 0) -> str:
    print(f"\n  {label}:")
    for i, opt in enumerate(options, 1):
        marker = "  ← default" if i - 1 == default_idx else ""
        print(f"    {i:>2}. {opt}{marker}")
    raw = input(f"  Enter number [{default_idx + 1}]: ").strip()
    if not raw:
        return options[default_idx]
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]
    return raw


# ---------------------------------------------------------------------------
# Sample source helpers
# ---------------------------------------------------------------------------

def _fetch_from_collection(collection_path: str, n_inj: int) -> list[SeqRow]:
    """Fetch BIOL_DDB samples from an OpenBIS collection and return SeqRows."""
    from .connection import get as _conn
    o = _conn()
    print(f"\n  Fetching samples from {collection_path} ...")
    try:
        result = o.get_samples(experiment=collection_path, type="BIOL_DDB")
    except Exception as exc:
        print(f"❌ Could not fetch samples: {exc}")
        sys.exit(1)

    rows: list[SeqRow] = []
    # pybis may return a Things object (iterable of sample objects) or a DataFrame
    samples = list(result) if hasattr(result, "__iter__") else []
    if not samples:
        print("❌ No BIOL_DDB samples found in that collection.")
        sys.exit(1)

    for s in samples:
        code = getattr(s, "code", "") or ""
        # $name is stored as a property
        try:
            name = s.props.get("$name") or s.props.get("name") or code
        except Exception:
            name = code
        for _ in range(n_inj):
            rows.append(SeqRow(sample_id=name, openbis_code=code))

    print(f"  Found {len(samples)} sample(s) → {len(rows)} sequence row(s).")
    return rows


def _register_new_samples(
    args,
    n: int,
    experiment: str,
    prefix: str,
    n_inj: int,
) -> list[SeqRow]:
    """Register new BIOL_DDB samples in OpenBIS and return SeqRows."""
    from .connection import get as _conn
    from .register import register_samples

    o = _conn()
    codes = register_samples(
        o,
        experiment,
        n,
        prefix=prefix,
        dry_run=getattr(args, "dry_run", False),
        confirm=not getattr(args, "no_confirm", False),
        sample_type=getattr(args, "sample_type", None),
        tax_id=getattr(args, "tax_id", None),
        sample_prep=getattr(args, "sample_prep", None),
        fractionation=getattr(args, "fractionation", None),
        digestion=getattr(args, "digestion", None),
        desalting=getattr(args, "desalting", None),
        labeling=getattr(args, "labeling", None),
        comment=getattr(args, "comment", None),
    )

    rows: list[SeqRow] = []
    for i, code in enumerate(codes, 1):
        name = f"{prefix}_{i:02d}"
        for _ in range(n_inj):
            rows.append(SeqRow(sample_id=name, openbis_code=code))
    return rows


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------

def run_wizard(args) -> None:
    """Interactive wizard: prompt for missing parameters, build and write sequence XLSX."""
    try:
        import pandas as pd  # noqa: F401
    except ImportError:
        print("❌ pandas + openpyxl required:  pip install pandas openpyxl")
        sys.exit(1)

    print("\n=== Timmie sequence file generator ===\n")

    # --- User initials ---
    user = (getattr(args, "user", None) or _ask("User initials (e.g. CK, SK)")).upper()
    if not user:
        print("❌ User initials required"); sys.exit(1)

    # --- Project code ---
    project = getattr(args, "project", None) or _ask("Project code (e.g. 3000, 9129)")
    if not project:
        print("❌ Project code required"); sys.exit(1)

    # --- Label ---
    label = getattr(args, "label", None) or _ask("Sequence label (e.g. Proteome, Phospho)")
    if not label:
        print("❌ Label required"); sys.exit(1)

    # --- Data path ---
    default_data_path = rf"D:\Data\{user}"
    data_path = getattr(args, "data_path", None) or _ask("Data path on Timmie PC", default_data_path)

    # --- LC method ---
    lc_keys = list(LC_METHODS.keys())
    lc_key = getattr(args, "lc_method", None)
    if not lc_key:
        lc_labels = [f"{k}  ({v})" for k, v in LC_METHODS.items()]
        chosen = _choose("LC method", lc_labels, default_idx=0)
        lc_key = lc_keys[lc_labels.index(chosen)] if chosen in lc_labels else lc_keys[0]

    # --- MS method ---
    ms_keys = list(MS_METHODS.keys())
    ms_key = getattr(args, "ms_method", None)
    if not ms_key:
        ms_labels = [f"{k}  ({v})" for k, v in MS_METHODS.items()]
        default_ms_idx = ms_keys.index(_LC_DEFAULT_MS.get(lc_key, "dia-long"))
        chosen = _choose("MS method", ms_labels, default_idx=default_ms_idx)
        ms_key = ms_keys[ms_labels.index(chosen)] if chosen in ms_labels else ms_keys[default_ms_idx]

    # --- Injections per sample ---
    n_inj = getattr(args, "injections", None)
    if n_inj is None:
        raw = _ask("Injections per sample", "1")
        n_inj = int(raw) if raw.isdigit() else 1

    # --- Sample source ---
    from_collection: str | None = getattr(args, "from_collection", None)
    n_new: int | None = getattr(args, "n", None)
    experiment: str | None = getattr(args, "experiment", None)

    seq_rows: list[SeqRow] = []

    if from_collection:
        seq_rows = _fetch_from_collection(from_collection, n_inj)

    elif n_new:
        if not experiment:
            experiment = _ask("OpenBIS experiment path (e.g. /DDB/CK/E_Proteome2025)")
        yymm = datetime.now().strftime("%y%m")
        prefix = f"{user}_T{yymm}_{project}_{label}"
        seq_rows = _register_new_samples(args, n_new, experiment, prefix, n_inj)

    else:
        # Ask interactively
        mode_opts = [
            "Register new samples in OpenBIS",
            "Use existing samples from a collection",
        ]
        mode = _choose("Sample source", mode_opts, default_idx=0)

        if "existing" in mode:
            coll = _ask("OpenBIS collection path (e.g. /DDB/CK/E_Proteome2025)")
            seq_rows = _fetch_from_collection(coll, n_inj)
        else:
            if not experiment:
                experiment = _ask("OpenBIS experiment path (e.g. /DDB/CK/E_Proteome2025)")
            raw = _ask("Number of samples to register")
            n_new = int(raw) if raw.isdigit() else 0
            if n_new < 1:
                print("❌ Need at least 1 sample"); sys.exit(1)
            yymm = datetime.now().strftime("%y%m")
            prefix = f"{user}_T{yymm}_{project}_{label}"
            seq_rows = _register_new_samples(args, n_new, experiment, prefix, n_inj)

    if not seq_rows:
        print("❌ No samples — nothing to write."); sys.exit(1)

    # --- Build DataFrame ---
    df = build_df(seq_rows, lc_key=lc_key, ms_key=ms_key, data_path=data_path)

    # --- Preview ---
    print(f"\n{'─' * 62}")
    print(f"  Instrument : Timmie (TimsTOF HT + EvoSep One)")
    print(f"  LC method  : {lc_key}  —  {LC_METHODS[lc_key]}")
    print(f"  MS method  : {ms_key}  —  {MS_METHODS[ms_key]}")
    print(f"  Rows       : {len(seq_rows)} sample(s) × {n_inj} inj = {len(df)} rows")
    print(f"  Vials      : {df['Vial'].iloc[0]} … {df['Vial'].iloc[-1]}")
    print(f"  Data path  : {data_path}")
    print()
    preview_cols = ["Vial", "Sample ID", "Openbis_Sample_ID"]
    print(df[preview_cols].head(8).to_string(index=False))
    if len(df) > 8:
        print(f"  … {len(df) - 8} more row(s)")
    print(f"{'─' * 62}")

    # --- Output ---
    out = getattr(args, "output", None)
    if not out:
        out = auto_filename(user, project, label)
    out_path = Path(out)

    if getattr(args, "dry_run", False):
        print(f"\n[DRY RUN] Would write: {out_path}  ({len(df)} rows)")
        return

    write_xlsx(df, out_path)
    print(f"\n✅ Written: {out_path}  ({len(df)} rows)")
