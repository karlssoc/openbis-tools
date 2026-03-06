"""
Generate OpenBIS BIOL_DDB sample registration TSV files (offline).

The file is ready for the user to annotate (fill in treatment columns etc.)
and then submit to OpenBIS via the web UI or send to an admin.

Usage:
    # Basic — core BIOL_DDB columns only
    obtools register-tsv -e /DDB/CK/E_Sepsis2025 --n 8

    # With 2 treatment annotation columns added
    obtools register-tsv -e /DDB/CK/E_Sepsis2025 --n 8 --treatments 2

    # Pre-fill shared fields
    obtools register-tsv -e /DDB/CK/E_Sepsis2025 --n 8 --treatments 3 \\
        --sample-type PLASMA --tax-id 9606 --digestion iST --labeling LFQ

    # See valid TREATMENT_TYPE values (requires connection)
    obtools vocab TREATMENT_TYPE
"""

from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

# Core BIOL_DDB columns — fixed order, grandfathered legacy layout
CORE_COLUMNS = [
    "container",
    "parents",
    "experiment",
    "$NAME",
    "BIOLOGICAL_SAMPLE_TYPE",
    "TAX_ID",
    "SAMPLE_PREPARATION",
    "FRACTIONATION",
    "DIGESTION",
    "DESALTING",
    "LABELING",
    "COMMENT",
    "EM_PATIENTS",
    "CK_PATIENTS",
]

# Common controlled-vocabulary hints (offline fallback — use `obtools vocab` for live values)
SAMPLE_TYPES = [
    "PLASMA", "SERUM", "URINE", "CSF", "SALIVA",
    "LEUKOCYTES", "PBMC", "WHOLE_BLOOD",
    "TISSUE_LIVER", "TISSUE_LUNG", "TISSUE_KIDNEY", "TISSUE_BRAIN",
    "TISSUE_SPLEEN", "TISSUE_HEART", "TISSUE_MUSCLE",
    "CELL_CULTURE", "YEAST", "BACTERIA", "OTHER",
]


def _treatment_columns(n_treatments: int) -> list[str]:
    """Return interleaved TREATMENT_TYPEn / TREATMENT_VALUEn column names."""
    cols = []
    for i in range(1, n_treatments + 1):
        cols.append(f"TREATMENT_TYPE{i}")
        cols.append(f"TREATMENT_VALUE{i}")
    return cols


def generate_registration_file(
    experiment: str,
    n: int,
    *,
    out: str | None = None,
    prefix: str | None = None,
    n_treatments: int = 0,
    sample_type: str = "",
    tax_id: str = "",
    digestion: str = "",
    desalting: str = "",
    labeling: str = "",
    fractionation: str = "",
    sample_prep: str = "",
    comment: str = "",
    container: str = "",
    parents: str = "",
) -> Path:
    """
    Write a BIOL_DDB registration TSV to disk.

    n_treatments: number of TREATMENT_TYPEn / TREATMENT_VALUEn column pairs to append.
    Returns the path of the written file.
    """
    if n < 1:
        print("❌ --n must be at least 1")
        sys.exit(1)

    today = date.today().strftime("%Y-%m-%d")
    exp_short = experiment.rstrip("/").split("/")[-1]
    out_path = Path(out) if out else Path(f"{today}_{exp_short}.txt")
    name_prefix = prefix or exp_short

    treatment_cols = _treatment_columns(n_treatments)
    all_columns = CORE_COLUMNS + treatment_cols

    rows = []
    for i in range(1, n + 1):
        row: dict[str, str] = {
            "container":              container,
            "parents":                parents,
            "experiment":             experiment,
            "$NAME":                  f"{name_prefix}_{i:02d}",
            "BIOLOGICAL_SAMPLE_TYPE": sample_type,
            "TAX_ID":                 tax_id,
            "SAMPLE_PREPARATION":     sample_prep,
            "FRACTIONATION":          fractionation,
            "DIGESTION":              digestion,
            "DESALTING":              desalting,
            "LABELING":               labeling,
            "COMMENT":                comment,
            "EM_PATIENTS":            "",
            "CK_PATIENTS":            "",
        }
        # Treatment columns left blank for the user to fill in
        for col in treatment_cols:
            row[col] = ""
        rows.append(row)

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=all_columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    return out_path


def print_summary(path: Path, experiment: str, n: int, n_treatments: int = 0) -> None:
    treatment_cols = _treatment_columns(n_treatments)
    all_columns = CORE_COLUMNS + treatment_cols

    print(f"\n✅ Registration file: {path}")
    print(f"   Experiment : {experiment}")
    print(f"   Samples    : {n}")
    if n_treatments:
        print(f"   Treatments : {n_treatments} pair(s) — fill TREATMENT_TYPE with CV terms")
        print(f"   💡 Run:  obtools vocab TREATMENT_TYPE  to see valid type values")
    print(f"\n   Columns ({len(all_columns)}):")
    for col in all_columns:
        blank = "  ← fill in" if col in treatment_cols or col in ("EM_PATIENTS", "CK_PATIENTS") else ""
        print(f"     {col}{blank}")
    print(f"\n   Submit via:  OpenBIS web UI → Admin → Batch register → BIOL_DDB")
