"""
DIA-NN log and FASTA file metadata parsing.

This is the core unique value of openbis-tools: extracting structured
metadata from DIA-NN outputs and FASTA databases for automatic OpenBIS
dataset annotation and parent-child linking.
"""

import os
import re
from pathlib import Path


def parse_diann_log(log_file: str) -> dict:
    """
    Extract metadata from a DIA-NN log file.

    Returns a dict with keys like DIANN_VERSION, FASTA_DATABASE,
    N_PRECURSORS, N_PROTEINS, MODIFICATIONS, etc.
    Returns {} if the file cannot be read or parsed.
    """
    try:
        log_content = Path(log_file).read_text()
    except Exception as exc:
        print(f"⚠️  Cannot read DIA-NN log {log_file}: {exc}")
        return {}

    meta: dict = {}

    def _find(pattern, cast=str):
        m = re.search(pattern, log_content)
        if m:
            try:
                return cast(m.group(1).strip())
            except Exception:
                pass
        return None

    # Version & dates
    meta["DIANN_VERSION"]    = _find(r"DIA-NN ([\d.]+)")
    meta["COMPILE_DATE"]     = _find(r"Compiled on (.+)")
    meta["GENERATION_DATE"]  = _find(r"Current date and time: (.+)")

    # Library statistics
    meta["N_PRECURSORS"] = _find(r"(\d+) precursors generated", int)
    meta["N_PROTEINS"]   = _find(r"Library contains (\d+) proteins", int)
    meta["N_GENES"]      = _find(r"and (\d+) genes", int)

    # FASTA database
    fasta_path = _find(r"--fasta ([^\s]+)")
    if fasta_path:
        meta["FASTA_DATABASE"] = os.path.basename(fasta_path)
        meta["FASTA_PATH"]     = fasta_path

    # Peptide / precursor / fragment parameters
    meta["MIN_PEPTIDE_LENGTH"]  = _find(r"--min-pep-len (\d+)", int)
    meta["MAX_PEPTIDE_LENGTH"]  = _find(r"--max-pep-len (\d+)", int)
    meta["MIN_PRECURSOR_MZ"]    = _find(r"--min-pr-mz (\d+)", int)
    meta["MAX_PRECURSOR_MZ"]    = _find(r"--max-pr-mz (\d+)", int)
    meta["MIN_PRECURSOR_CHARGE"]= _find(r"--min-pr-charge (\d+)", int)
    meta["MAX_PRECURSOR_CHARGE"]= _find(r"--max-pr-charge (\d+)", int)
    meta["MIN_FRAGMENT_MZ"]     = _find(r"--min-fr-mz (\d+)", int)
    meta["MAX_FRAGMENT_MZ"]     = _find(r"--max-fr-mz (\d+)", int)
    meta["MISSED_CLEAVAGES"]    = _find(r"--missed-cleavages (\d+)", int)
    meta["CLEAVAGE_SITES"]      = _find(r"--cut ([^\s]+)")

    # Generation method
    methods = []
    if "Deep learning will be used" in log_content:
        methods.append("Deep learning prediction")
    if "--gen-spec-lib" in log_content:
        methods.append("In silico library generation")
    if "--predictor" in log_content:
        methods.append("RT predictor")
    if methods:
        meta["GENERATION_METHOD"] = ", ".join(methods)

    # Modifications
    mods = []
    if "Cysteine carbamidomethylation enabled" in log_content:
        mods.append("Cysteine carbamidomethylation (fixed)")
    if "--met-excision" in log_content:
        mods.append("N-terminal methionine excision")
    if "--unimod4" in log_content:
        mods.append("Unimod modifications")
    if mods:
        meta["MODIFICATIONS"] = ", ".join(mods)

    # System info
    meta["THREADS_USED"] = _find(r"Thread number set to (\d+)", int)
    meta["SYSTEM_CORES"] = _find(r"Logical CPU cores: (\d+)", int)

    # Drop None values
    return {k: v for k, v in meta.items() if v is not None}


def parse_fasta_metadata(fasta_file: str, version: str | None = None) -> dict:
    """
    Extract metadata from a FASTA file (entry count, species breakdown, etc.).

    Returns a dict suitable for use as OpenBIS dataset properties.
    """
    meta: dict = {}
    species_counts: dict = {}
    total = 0

    try:
        with open(fasta_file) as fh:
            for line in fh:
                if not line.startswith(">"):
                    continue
                total += 1
                # Best-effort species extraction from UniProt-style headers
                # e.g. >sp|P12345|GENE_HUMAN ... OS=Homo sapiens OX=9606
                m = re.search(r"OS=(.+?)(?:\s+OX=|\s+GN=|$)", line)
                if m:
                    species = m.group(1).strip()
                    species_counts[species] = species_counts.get(species, 0) + 1
    except Exception as exc:
        print(f"⚠️  Cannot read FASTA {fasta_file}: {exc}")
        return {}

    meta["N_SEQUENCES"] = total

    if species_counts:
        top = sorted(species_counts.items(), key=lambda x: x[1], reverse=True)
        meta["PRIMARY_SPECIES"] = top[0][0]
        meta["N_SPECIES"] = len(top)
        if len(top) > 1:
            meta["SPECIES_BREAKDOWN"] = "; ".join(f"{sp} ({n})" for sp, n in top[:5])

    if version:
        meta["VERSION"] = version

    fasta_path = Path(fasta_file)
    meta["FILENAME"] = fasta_path.name
    meta["FILE_SIZE_MB"] = round(fasta_path.stat().st_size / 1_048_576, 2)

    return meta
