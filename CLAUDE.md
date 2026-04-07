# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
uv venv .venv
uv pip install -e . -p .venv/bin/python

# Run
.venv/bin/obtools <command>
# or after editable install on PATH:
obtools <command>

# Dry-run any upload/ingest without writing
obtools upload file.fasta --dry-run
obtools ingest /data/runs/ --collection /DDB/CK/E_Test --dry-run
```

No automated tests — all testing is manual against a live OpenBIS instance (`https://bioms.med.lu.se/openbis/`).

## Architecture

All source lives in `src/obtools/`. No sub-packages — flat module layout.

### Entry point & dispatch

`cli.py` is the sole entry point (`obtools = obtools.cli:main`). It builds an argparse tree in `build_parser()` and dispatches to `cmd_<name>(args)` handlers via a `_HANDLERS` dict. All module imports are **lazy** (inside handler functions) to keep startup fast.

Every handler calls `_conn()` which delegates to `connection.get()` → returns an authenticated `pybis.Openbis` object with token caching (pybis saves tokens to `~/.pybis/session.json`; reused until expiry).

### Credential loading (`auth.py`)

Priority: `~/.openbis/credentials` file → OS keychain → environment variables.
Keys: `OPENBIS_URL`, `OPENBIS_USERNAME`, `OPENBIS_PASSWORD`, `OBTOOLS_DOWNLOAD_DIR`, `OBTOOLS_VERIFY_CERTS`.

### Upload system (`upload.py`)

Uploader class hierarchy: `Uploader` (base) → `FastaUploader`, `SpectralLibraryUploader`.
Each subclass overrides `parse_metadata(fp, **kwargs)` and `make_name(fp, meta, custom_name)`.
`get_uploader(file_type, o)` is the factory function.

File type detection via `detect_file_type(path)` → `"fasta" | "spectral_library" | "unknown"`.

The `--auto-link` flag invokes `autolink.suggest_parents()` → heuristic dataset search + `interactive_confirm()` (numbered menu accepting single, comma-list, or range input) → parent codes added before `dataset.save()`.

**Important**: `SPECTRAL_LIBRARY` datasets use the `notes` property for the human-readable name instead of `$name` (mapped in `_NAME_PROP`). The base `Uploader._set_prop()` silently swallows unknown property errors.

### Ingest workflow (`ingest.py`)

Scans a source directory for `.raw` (Thermo) and `.d` (Bruker) files. For each file:
1. Bruker `.d` dirs are zipped in-memory (excluding macOS metadata) before upload
2. A `BIOL_DDB` sample is created per acquisition (unless `--skip-samples`)
3. A `RAW_DATA` dataset is uploaded and linked to the sample
4. Metadata extracted: `ACQUISITION_DATE` from `analysis.tdf` SQLite (Bruker) or file mtime; `INSTRUMENT_SN`, `INSTRUMENT_NAME` hardcoded by vendor

### Sequence file generation (`sequence_timmie.py`)

Generates HyStar XLSX sequence files for Timmie (TimsTOF HT + EvoSep One). Invoked via `obtools make-sequence`. Interactive wizard prompts for user initials, project code, LC/MS method selection, and sample source (fetch existing BIOL_DDB samples from a collection or register new ones). Vial positions follow 96-well plate layout (A1→H12, wrapping to S2 for >96 samples). Output filename: `{user}_T{YYMM}_{project}_{label}.xlsx`.

MS method keys: `dia-long`, `dia-short`, `dda`, `phospho`, `p2`.
LC method keys: `30spd`, `60spd`, `100spd`, `200spd`, `300spd`.

### Metadata parsing (`diann.py`)

`parse_diann_log(log_file)` — regex extraction of DIA-NN run parameters and library stats.
`parse_fasta_metadata(fasta_path, version)` — counts sequences and parses `OS=` species fields from FASTA headers.

### Sample registration (`register.py`, `register_tsv.py`)

`register.py`: interactive CLI wizard for creating `BIOL_DDB` samples; fetches CV terms once and caches them.
`register_tsv.py`: offline TSV generation (no connection needed) for bulk OpenBIS batch import.

## Key conventions

- `DEFAULT_COLLECTIONS` and `DEFAULT_TYPES` dicts in `upload.py` define the OpenBIS collection paths and dataset types for each file category — update these when adding new upload paths.
- OpenBIS dataset codes look like `20250502110701494-1323378` (internal) or `DDBS377561` (friendly). Collection paths use `/SPACE/PROJECT/EXPERIMENT` format.
- The graveyard predecessor (`~/Projects/Graveyard/ck-pybis-toolkit`) has a `upload-analyzed` command and a JSON config system (`~/.pybis/config.json`) not present here — refer to it if either feature is needed.
