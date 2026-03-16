"""
Direct registration of BIOL_DDB samples/objects in OpenBIS via the pybis API.

Controlled-vocabulary fields are fetched live from OpenBIS so the interactive
prompts always show valid options. Pass all flags to skip prompts entirely
for scripted/non-interactive use.

Usage (interactive):
    obtools register --experiment /DDB/CK/E_MyStudy2025 --n 8

Usage (fully scripted):
    obtools register --experiment /DDB/CK/E_Sepsis2025 --n 12 \\
        --prefix SP25 --sample-type PLASMA --tax-id 9606 \\
        --digestion iST --labeling LFQ --no-confirm
"""

from __future__ import annotations

import sys
from typing import Any

from pybis import Openbis

# ---------------------------------------------------------------------------
# Property definitions for BIOL_DDB
# ---------------------------------------------------------------------------

# Maps column name → (openbis_property_code, is_controlled_vocabulary, vocab_name_or_None)
# '$NAME' is handled separately as it maps to the object name, not a property.
PROPERTIES: list[tuple[str, str, str | None]] = [
    ("BIOLOGICAL_SAMPLE_TYPE", "BIOLOGICAL_SAMPLE_TYPE", "BIOLOGICAL_SAMPLE_TYPE"),
    ("TAX_ID",                 "TAX_ID",                 "NCBI_TAXONOMY"),
    ("SAMPLE_PREPARATION",     "SAMPLE_PREPARATION",     "SAMPLE_PREPARATION"),
    ("FRACTIONATION",          "FRACTIONATION",          "FRACTIONATION"),
    ("DIGESTION",              "DIGESTION",              "DIGESTION"),
    ("DESALTING",              "DESALTING",              "DESALTING"),
    ("LABELING",               "LABELING",               "LABELING"),
    ("COMMENT",                "COMMENT",                None),     # free text
    ("EM_PATIENTS",            "EM_PATIENTS",            None),     # free text
    ("CK_PATIENTS",            "CK_PATIENTS",            None),     # free text
]

# Fields we know are free text (never fetch a vocabulary for these)
FREE_TEXT = {"COMMENT", "EM_PATIENTS", "CK_PATIENTS"}


# ---------------------------------------------------------------------------
# Vocabulary helpers
# ---------------------------------------------------------------------------

def _fetch_vocab_terms(o: Openbis, vocab_code: str) -> list[str]:
    """Fetch controlled vocabulary terms from OpenBIS. Returns [] on failure."""
    try:
        vocab = o.get_vocabulary(vocab_code)
        terms = vocab.get_terms()
        if terms is None or len(terms) == 0:
            return []
        if hasattr(terms, "itertuples"):
            return [getattr(row, "code", "") for row in terms.itertuples() if getattr(row, "code", "")]
        return [getattr(t, "code", str(t)) for t in terms]
    except Exception:
        return []


def _build_vocab_cache(o: Openbis) -> dict[str, list[str]]:
    """Pre-fetch all CV terms we'll need. Silently skips vocabularies that don't exist."""
    cache: dict[str, list[str]] = {}
    for _, _, vocab_name in PROPERTIES:
        if vocab_name and vocab_name not in FREE_TEXT and vocab_name not in cache:
            terms = _fetch_vocab_terms(o, vocab_name)
            if terms:
                cache[vocab_name] = terms
    return cache


# ---------------------------------------------------------------------------
# Interactive prompt helpers
# ---------------------------------------------------------------------------

def _prompt(label: str, terms: list[str], current: str | None) -> str:
    """
    Prompt the user for a value. If `terms` is non-empty, display them as
    numbered options. Pressing Enter keeps `current` (if set) or leaves blank.
    """
    if current is not None:
        # Value already provided via CLI flag — use it without prompting
        return current

    if terms:
        print(f"\n  {label}:")
        for i, t in enumerate(terms, 1):
            print(f"    {i:>3}. {t}")
        raw = input(f"  Enter number or value (blank to skip): ").strip()
        if not raw:
            return ""
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(terms):
                return terms[idx]
        return raw.upper()
    else:
        raw = input(f"  {label} (blank to skip): ").strip()
        return raw


# ---------------------------------------------------------------------------
# Core registration
# ---------------------------------------------------------------------------

def register_samples(
    o: Openbis,
    experiment: str,
    n: int,
    *,
    prefix: str | None = None,
    dry_run: bool = False,
    confirm: bool = True,
    # Pre-filled values from CLI flags (None = prompt interactively)
    sample_type: str | None = None,
    tax_id: str | None = None,
    sample_prep: str | None = None,
    fractionation: str | None = None,
    digestion: str | None = None,
    desalting: str | None = None,
    labeling: str | None = None,
    comment: str | None = None,
    em_patients: str | None = None,
    ck_patients: str | None = None,
    container: str | None = None,
    parents: list[str] | None = None,
) -> list[str]:
    """
    Register `n` BIOL_DDB objects in OpenBIS.

    Returns list of created sample codes (e.g. DDBS377561). In dry_run mode returns [] and only prints.
    """
    if n < 1:
        print("❌ --n must be at least 1")
        sys.exit(1)

    # Verify experiment exists
    print(f"🔍 Checking experiment {experiment} ...")
    try:
        o.get_experiment(experiment)
    except Exception as exc:
        print(f"❌ Experiment not found: {exc}")
        sys.exit(1)

    # Build sample name prefix
    exp_short = experiment.rstrip("/").split("/")[-1]
    name_prefix = prefix or exp_short

    # Pre-fetch controlled vocabularies
    print("📖 Fetching controlled vocabularies from OpenBIS...")
    vocab_cache = _build_vocab_cache(o)

    # Map CLI values so we can look them up by property code
    cli_values: dict[str, str | None] = {
        "BIOLOGICAL_SAMPLE_TYPE": sample_type,
        "TAX_ID":                 tax_id,
        "SAMPLE_PREPARATION":     sample_prep,
        "FRACTIONATION":          fractionation,
        "DIGESTION":              digestion,
        "DESALTING":              desalting,
        "LABELING":               labeling,
        "COMMENT":                comment,
        "EM_PATIENTS":            em_patients,
        "CK_PATIENTS":            ck_patients,
    }

    # Determine whether we need interactive prompts at all
    needs_interactive = any(v is None for v in cli_values.values())

    # Collect shared property values (same for all samples)
    print("\n📝 Sample properties (shared across all samples):")
    shared_props: dict[str, str] = {}

    for col, prop_code, vocab_name in PROPERTIES:
        cli_val = cli_values.get(prop_code)
        terms = vocab_cache.get(vocab_name, []) if vocab_name else []
        value = _prompt(col, terms, cli_val)
        if value:
            shared_props[prop_code] = value

    # Container / parents — same for all samples unless specified per-sample
    container_val   = container or ""
    parents_val     = parents or []

    # Preview
    print(f"\n{'─'*55}")
    print(f"  Experiment : {experiment}")
    print(f"  Object type: BIOL_DDB")
    print(f"  Samples    : {n}  ({name_prefix}_01 … {name_prefix}_{n:02d})")
    if container_val:
        print(f"  Container  : {container_val}")
    if parents_val:
        print(f"  Parents    : {', '.join(parents_val)}")
    print(f"  Properties :")
    for k, v in shared_props.items():
        print(f"    {k}: {v}")
    if dry_run:
        print(f"\n  [DRY RUN — nothing will be created]")
    print(f"{'─'*55}")

    if dry_run:
        return []

    if confirm:
        try:
            answer = input("\nCreate these samples? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return []
        if answer not in ("y", "yes"):
            print("Aborted.")
            return []

    # Create samples
    created: list[str] = []
    print(f"\n🚀 Creating {n} samples in OpenBIS...")

    for i in range(1, n + 1):
        name = f"{name_prefix}_{i:02d}"
        try:
            sample = o.new_sample(
                type="BIOL_DDB",
                experiment=experiment,
                props=shared_props,
            )
            # $NAME is set via the name property, not props
            sample.props["$name"] = name

            if container_val:
                sample.container = container_val
            if parents_val:
                sample.parents = parents_val

            sample.save()
            code = sample.code
            created.append(code)
            print(f"  ✅ {name}  →  {code}")
        except Exception as exc:
            print(f"  ❌ {name} failed: {exc}")

    print(f"\n✅ Created {len(created)}/{n} samples.")
    return created
