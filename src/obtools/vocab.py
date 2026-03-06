"""
Look up controlled vocabulary terms from OpenBIS.

Useful before filling in a registration TSV so you know what values
are valid for fields like TREATMENT_TYPE, BIOLOGICAL_SAMPLE_TYPE, etc.

Usage:
    obtools vocab TREATMENT_TYPE
    obtools vocab BIOLOGICAL_SAMPLE_TYPE
    obtools vocab                          # list all available vocabularies
"""

from __future__ import annotations

import sys
from pybis import Openbis


def list_vocabularies(o: Openbis) -> None:
    """Print all vocabulary codes defined in this OpenBIS instance."""
    try:
        vocabs = o.get_vocabularies()
    except Exception as exc:
        print(f"❌ Could not fetch vocabularies: {exc}")
        sys.exit(1)

    if vocabs is None or len(vocabs) == 0:
        print("ℹ️  No vocabularies found.")
        return

    rows = list(vocabs.itertuples()) if hasattr(vocabs, "itertuples") else list(vocabs)
    print(f"📖 {len(rows)} vocabularies defined in OpenBIS:\n")
    for row in sorted(rows, key=lambda r: getattr(r, "code", "")):
        code = getattr(row, "code", "?")
        desc = getattr(row, "description", "") or ""
        print(f"  {code:<40}  {desc}")
    print(f"\nUse:  obtools vocab <CODE>  to see terms for a specific vocabulary.")


def show_vocabulary(o: Openbis, vocab_code: str) -> None:
    """Print all terms for a single vocabulary, with labels and descriptions."""
    try:
        vocab = o.get_vocabulary(vocab_code)
    except Exception as exc:
        print(f"❌ Vocabulary '{vocab_code}' not found: {exc}")
        print("   Run  obtools vocab  (no argument) to list all available vocabularies.")
        sys.exit(1)

    try:
        terms = vocab.get_terms()
    except Exception as exc:
        print(f"❌ Could not fetch terms for '{vocab_code}': {exc}")
        sys.exit(1)

    if terms is None or len(terms) == 0:
        print(f"ℹ️  Vocabulary '{vocab_code}' has no terms.")
        return

    rows = list(terms.itertuples()) if hasattr(terms, "itertuples") else list(terms)
    rows_sorted = sorted(rows, key=lambda r: getattr(r, "code", ""))

    print(f"\n📖 {vocab_code}  ({len(rows_sorted)} terms)\n")
    print(f"  {'CODE':<35}  LABEL")
    print(f"  {'─'*35}  {'─'*30}")
    for row in rows_sorted:
        code  = getattr(row, "code",  "?")
        label = getattr(row, "label", "") or getattr(row, "description", "") or ""
        print(f"  {code:<35}  {label}")

    print(f"\n  Use these CODE values in your registration TSV.")
