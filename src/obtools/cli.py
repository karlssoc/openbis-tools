"""
obtools — proteomics-focused OpenBIS CLI toolkit.

Entry point: obtools <command> [options]

Commands:
  connect              Test connection and list spaces
  download             Download a dataset
  download-collection  Download all datasets from a collection
  info                 Show dataset info and lineage
  search               Search datasets, samples, experiments
  upload               Upload any file (auto-detect type)
  upload-fasta         Upload a FASTA database
  upload-lib           Upload a spectral library
  register             Create BIOL_DDB samples directly in OpenBIS
  register-tsv         Generate a BIOL_DDB registration TSV file (offline)
  vocab                List controlled vocabulary terms from OpenBIS
  ingest               Discover raw files, create samples, upload datasets
  make-sequence        Generate a HyStar sequence file for Timmie (TimsTOF HT)
"""

from __future__ import annotations

import argparse
import sys


# ---------------------------------------------------------------------------
# Lazy imports (keep startup fast)
# ---------------------------------------------------------------------------

def _conn():
    from .connection import get
    return get()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_connect(args):
    o = _conn()
    spaces = o.get_spaces()
    print(f"✅ Connected  —  {len(spaces)} space(s):")
    rows = list(spaces.itertuples()) if hasattr(spaces, "itertuples") else list(spaces)
    for s in rows:
        code = getattr(s, "code", "?")
        desc = getattr(s, "description", "") or ""
        print(f"   {code}  {desc}")


def cmd_download(args):
    from .download import download_dataset
    o = _conn()
    for code in args.dataset_codes:
        download_dataset(o, code, args.output, list_only=args.list_only, force=args.force)


def cmd_download_collection(args):
    from .download import download_collection
    o = _conn()
    download_collection(
        o, args.collection, args.output,
        list_only=args.list_only, limit=args.limit, force=args.force,
    )


def cmd_info(args):
    o = _conn()
    try:
        ds = o.get_dataset(args.dataset_code)
    except Exception as exc:
        print(f"❌ Dataset not found: {exc}")
        sys.exit(1)

    print(f"📊 Dataset: {ds.permId}")
    print(f"   Type:     {ds.type}")
    print(f"   Experiment: {getattr(ds, 'experiment', 'N/A')}")

    if args.lineage:
        from .search import search_datasets
        print("\n⬆️  Parents:")
        search_datasets(o, parents_of=args.dataset_code)
        print("\n⬇️  Children:")
        search_datasets(o, children_of=args.dataset_code)


def cmd_search(args):
    from .search import search_datasets, search_samples, search_experiments
    o = _conn()

    if args.children_of or args.parents_of:
        search_datasets(
            o,
            children_of=args.children_of,
            parents_of=args.parents_of,
            save=args.save,
        )
        return

    if args.type in ("datasets", "all"):
        search_datasets(
            o, args.query,
            limit=args.limit,
            space=args.space,
            dataset_type=args.dataset_type,
            property_code=args.property,
            property_value=args.property_value,
            registration_date=args.registration_date,
            save=args.save,
        )
    if args.type in ("samples", "all") and args.query:
        search_samples(o, args.query, args.limit)
    if args.type in ("experiments", "all") and args.query:
        search_experiments(o, args.query, args.limit)


def cmd_upload(args):
    from .upload import detect_file_type, get_uploader, default_collection, default_dataset_type
    o = _conn()

    file_type = args.type if args.type != "auto" else detect_file_type(args.file)
    print(f"🔍 File type: {file_type}")

    collection   = args.collection   or default_collection(file_type)
    dataset_type = args.dataset_type or default_dataset_type(file_type)

    uploader = get_uploader(file_type, o)
    uploader.upload(
        args.file,
        dataset_type=dataset_type,
        collection=collection,
        name=args.name,
        notes=args.notes,
        parents=args.parent_dataset,
        auto_link=args.auto_link,
        dry_run=args.dry_run,
        version=args.version,
        log_file=args.log_file,
    )


def cmd_upload_fasta(args):
    from .upload import FastaUploader, default_collection, default_dataset_type
    o = _conn()
    FastaUploader(o).upload(
        args.fasta_file,
        dataset_type=args.dataset_type or default_dataset_type("fasta"),
        collection=args.collection or default_collection("fasta"),
        name=args.name,
        notes=args.notes,
        parents=args.parent_dataset,
        auto_link=args.auto_link,
        dry_run=args.dry_run,
        version=args.version,
    )


def cmd_upload_lib(args):
    from .upload import SpectralLibraryUploader, default_collection, default_dataset_type
    o = _conn()
    SpectralLibraryUploader(o).upload(
        args.library_file,
        dataset_type=args.dataset_type or default_dataset_type("spectral_library"),
        collection=args.collection or default_collection("spectral_library"),
        name=args.name,
        notes=args.notes,
        parents=args.parent_dataset,
        auto_link=args.auto_link,
        dry_run=args.dry_run,
        log_file=args.log_file,
    )


def cmd_register(args):
    """Create BIOL_DDB samples directly in OpenBIS via API."""
    from .register import register_samples
    o = _conn()

    parents = [p.strip() for p in args.parents.split(",")] if args.parents else []

    register_samples(
        o,
        args.experiment,
        args.n,
        prefix=args.prefix,
        dry_run=args.dry_run,
        confirm=not args.no_confirm,
        sample_type=args.sample_type,
        tax_id=args.tax_id,
        sample_prep=args.sample_prep,
        fractionation=args.fractionation,
        digestion=args.digestion,
        desalting=args.desalting,
        labeling=args.labeling,
        comment=args.comment,
        em_patients=args.em_patients,
        ck_patients=args.ck_patients,
        container=args.container,
        parents=parents,
    )


def cmd_register_tsv(args):
    """Generate a BIOL_DDB registration TSV file (no connection needed)."""
    from .register_tsv import generate_registration_file, print_summary, SAMPLE_TYPES

    if args.list_types:
        print("Common BIOLOGICAL_SAMPLE_TYPE values (offline list — use `obtools vocab` for live CV):")
        for t in SAMPLE_TYPES:
            print(f"  {t}")
        return

    if not args.experiment:
        print("❌ --experiment is required (e.g. /DDB/CK/E_MyStudy2025)")
        sys.exit(1)
    if not args.n:
        print("❌ --n is required (number of samples)")
        sys.exit(1)

    n_treatments = max(0, args.treatments or 0)

    path = generate_registration_file(
        args.experiment,
        args.n,
        out=args.out,
        prefix=args.prefix,
        n_treatments=n_treatments,
        sample_type=args.sample_type or "",
        tax_id=args.tax_id or "",
        digestion=args.digestion or "",
        desalting=args.desalting or "",
        labeling=args.labeling or "",
        fractionation=args.fractionation or "",
        sample_prep=args.sample_prep or "",
        comment=args.comment or "",
        container=args.container or "",
        parents=args.parents or "",
    )
    print_summary(path, args.experiment, args.n, n_treatments)


def cmd_vocab(args):
    """List controlled vocabulary terms from OpenBIS."""
    from .vocab import list_vocabularies, show_vocabulary
    o = _conn()
    if args.vocab_code:
        show_vocabulary(o, args.vocab_code.upper())
    else:
        list_vocabularies(o)


def cmd_make_sequence(args):
    """Generate a HyStar sequence file for Timmie (TimsTOF HT + EvoSep One)."""
    from .sequence_timmie import run_wizard
    run_wizard(args)


def cmd_ingest(args):
    """Discover raw files, create samples, upload datasets."""
    from .ingest import ingest
    o = _conn()
    ingest(
        o,
        args.source,
        args.collection,
        create_collection=args.create_collection,
        collection_type=args.collection_type,
        dataset_type=args.dataset_type,
        sample_type=args.sample_type,
        prefix=args.prefix,
        skip_samples=args.skip_samples,
        raw_instrument_sn=args.raw_instrument_sn,
        raw_instrument_name=args.raw_instrument_name,
        dry_run=args.dry_run,
    )


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="obtools",
        description="Proteomics-focused OpenBIS CLI toolkit",
    )
    sub = p.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # ---- connect ----
    sub.add_parser("connect", help="Test connection and list spaces")

    # ---- download ----
    dl = sub.add_parser("download", help="Download one or more datasets")
    dl.add_argument("dataset_codes", nargs="+", metavar="DATASET_CODE")
    dl.add_argument("--output", "-o", default=None, help="Output directory")
    dl.add_argument("--list-only", action="store_true")
    dl.add_argument("--force", action="store_true")

    # ---- download-collection ----
    dc = sub.add_parser("download-collection", help="Download all datasets in a collection")
    dc.add_argument("collection")
    dc.add_argument("--output", "-o", default=None)
    dc.add_argument("--list-only", action="store_true")
    dc.add_argument("--limit", type=int, default=None)
    dc.add_argument("--force", action="store_true")

    # ---- info ----
    info = sub.add_parser("info", help="Show dataset info and lineage")
    info.add_argument("dataset_code")
    info.add_argument("--lineage", action="store_true", help="Show parent and child datasets")

    # ---- search ----
    srch = sub.add_parser("search", help="Search datasets / samples / experiments")
    srch.add_argument("query", nargs="?")
    srch.add_argument("--type", choices=["datasets", "samples", "experiments", "all"], default="datasets")
    srch.add_argument("--limit", type=int, default=20)
    srch.add_argument("--save", metavar="FILE.csv")
    srch.add_argument("--space")
    srch.add_argument("--dataset-type")
    srch.add_argument("--property")
    srch.add_argument("--property-value")
    srch.add_argument("--registration-date", metavar=">YYYY-MM-DD")
    srch.add_argument("--children-of", metavar="DATASET_CODE")
    srch.add_argument("--parents-of",  metavar="DATASET_CODE")

    # ---- shared upload args ----
    def _upload_common(sp):
        sp.add_argument("--collection")
        sp.add_argument("--dataset-type")
        sp.add_argument("--name")
        sp.add_argument("--notes")
        sp.add_argument("--parent-dataset", action="append", metavar="CODE")
        sp.add_argument("--auto-link", action="store_true")
        sp.add_argument("--dry-run", action="store_true")

    # ---- upload (auto-detect) ----
    up = sub.add_parser("upload", help="Upload any file (auto-detect type)")
    up.add_argument("file")
    up.add_argument("--type", choices=["auto", "fasta", "spectral_library"], default="auto")
    up.add_argument("--version")
    up.add_argument("--log-file")
    _upload_common(up)

    # ---- upload-fasta ----
    uf = sub.add_parser("upload-fasta", help="Upload a FASTA database")
    uf.add_argument("fasta_file")
    uf.add_argument("--version")
    _upload_common(uf)

    # ---- upload-lib ----
    ul = sub.add_parser("upload-lib", help="Upload a spectral library")
    ul.add_argument("library_file")
    ul.add_argument("--log-file", help="DIA-NN log file (metadata + uploaded alongside library)")
    _upload_common(ul)

    # ---- shared sample registration args ----
    def _reg_common(sp):
        sp.add_argument("--prefix", metavar="STR",
                        help="Prefix for sample $NAME (default: last part of experiment path)")
        sp.add_argument("--sample-type", metavar="TYPE",
                        help="BIOLOGICAL_SAMPLE_TYPE (prompted from CV if omitted)")
        sp.add_argument("--tax-id", metavar="ID",
                        help="TAX_ID (e.g. 9606 = Homo sapiens, 10090 = Mus musculus)")
        sp.add_argument("--digestion", metavar="STR",
                        help="DIGESTION (e.g. SP3, iST, FASP)")
        sp.add_argument("--desalting", metavar="STR",
                        help="DESALTING (e.g. C18, SDB-RPS)")
        sp.add_argument("--labeling", metavar="STR",
                        help="LABELING (e.g. LFQ, TMT, iTRAQ)")
        sp.add_argument("--fractionation", metavar="STR",
                        help="FRACTIONATION (e.g. High_pH, SAX)")
        sp.add_argument("--sample-prep", metavar="STR",
                        help="SAMPLE_PREPARATION free text")
        sp.add_argument("--comment", metavar="STR",
                        help="COMMENT field, same for all samples")
        sp.add_argument("--em-patients", metavar="IDs",
                        help="EM_PATIENTS identifiers")
        sp.add_argument("--ck-patients", metavar="IDs",
                        help="CK_PATIENTS identifiers")
        sp.add_argument("--container", metavar="CODE",
                        help="Container sample code (if samples live inside a container)")
        sp.add_argument("--parents", metavar="CODES",
                        help="Parent sample code(s), comma-separated")

    # ---- register (direct API) ----
    reg = sub.add_parser(
        "register",
        help="Create BIOL_DDB samples directly in OpenBIS",
        description=(
            "Connects to OpenBIS and creates N BIOL_DDB sample objects.\n"
            "Controlled-vocabulary fields are fetched live and presented as numbered lists.\n"
            "Pass all flags to run non-interactively (e.g. in scripts)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    reg.add_argument("--experiment", "-e", required=True, metavar="PATH",
                     help="OpenBIS experiment path, e.g. /DDB/CK/E_MyStudy2025")
    reg.add_argument("--n", type=int, required=True, metavar="N",
                     help="Number of samples to create")
    reg.add_argument("--dry-run", action="store_true",
                     help="Preview what would be created without writing to OpenBIS")
    reg.add_argument("--no-confirm", action="store_true",
                     help="Skip confirmation prompt (useful for scripting)")
    _reg_common(reg)

    # ---- register-tsv (offline TSV generator) ----
    rtsv = sub.add_parser(
        "register-tsv",
        help="Generate a BIOL_DDB registration TSV file (no connection needed)",
        description=(
            "Creates an offline tab-separated file for OpenBIS batch import.\n"
            "Hand the file to your OpenBIS admin or import it once you have write access."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    rtsv.add_argument("--experiment", "-e", metavar="PATH",
                      help="OpenBIS experiment path, e.g. /DDB/CK/E_MyStudy2025")
    rtsv.add_argument("--n", type=int, metavar="N",
                      help="Number of samples")
    rtsv.add_argument("--out", "-o", metavar="FILE",
                      help="Output filename (default: YYYY-MM-DD_<experiment>.txt)")
    rtsv.add_argument("--treatments", type=int, default=0, metavar="N",
                      help="Add N TREATMENT_TYPEn / TREATMENT_VALUEn column pairs (fill after generation)")
    rtsv.add_argument("--list-types", action="store_true",
                      help="Print common BIOLOGICAL_SAMPLE_TYPE values and exit")
    _reg_common(rtsv)

    # ---- ingest ----
    ing = sub.add_parser(
        "ingest",
        help="Discover raw MS files, create samples and upload datasets",
        description=(
            "Scans a directory for Thermo .raw files and Bruker .d directories,\n"
            "creates a BIOL_DDB sample per acquisition, and uploads each file as\n"
            "a dataset linked to its sample.\n\n"
            "Bruker .d directories are automatically compressed to .zip before\n"
            "upload using Python's built-in zipfile (no external tools needed).\n"
            "macOS metadata (__MACOSX/, .DS_Store, ._* files) is excluded.\n\n"
            "Examples:\n"
            "  obtools ingest /data/runs/ --collection /DDB/CK/E_Sepsis2025\n"
            "  obtools ingest /data/runs/ --collection /DDB/CK/E_New --create-collection\n"
            "  obtools ingest /data/runs/ --collection /DDB/CK/E_Sepsis2025 --dry-run"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ing.add_argument("source", metavar="PATH",
                     help="Directory containing .raw files and/or .d directories")
    ing.add_argument("--collection", "-c", required=True, metavar="PATH",
                     help="OpenBIS collection path, e.g. /DDB/CK/E_Sepsis2025")
    ing.add_argument("--create-collection", action="store_true",
                     help="Create the collection if it does not exist")
    ing.add_argument("--collection-type", default="MS_EXPERIMENT", metavar="TYPE",
                     help="Collection type when creating (default: MS_EXPERIMENT)")
    ing.add_argument("--dataset-type", default="RAW_DATA", metavar="TYPE",
                     help="OpenBIS dataset type for uploaded files (default: RAW_DATA)")
    ing.add_argument("--sample-type", default="BIOL_DDB", metavar="TYPE",
                     help="OpenBIS sample type to create (default: BIOL_DDB)")
    ing.add_argument("--prefix", metavar="STR",
                     help="Prefix for sample $NAME (default: source directory name)")
    ing.add_argument("--skip-samples", action="store_true",
                     help="Upload datasets only, do not create samples")
    ing.add_argument("--raw-instrument-sn", default="MS:1000529", metavar="SN",
                     help="INSTRUMENT_SN for Thermo .raw files (default: MS:1000529)")
    ing.add_argument("--raw-instrument-name", default="Q_Exactive_HF-X_Orbitrap", metavar="NAME",
                     help="INSTRUMENT_NAME for Thermo .raw files (default: Q_Exactive_HF-X_Orbitrap)")
    ing.add_argument("--dry-run", action="store_true",
                     help="Preview everything without writing to OpenBIS or archiving files")

    # ---- make-sequence ----
    ms_p = sub.add_parser(
        "make-sequence",
        help="Generate a HyStar sequence file for Timmie (TimsTOF HT + EvoSep One)",
        description=(
            "Interactively builds a HyStar-compatible .xlsx sequence file.\n\n"
            "Two modes:\n"
            "  1. Register new samples in OpenBIS, then generate the sequence.\n"
            "  2. Fetch existing BIOL_DDB samples from a collection and generate the sequence.\n\n"
            "All options can be omitted — the wizard will prompt for anything missing.\n\n"
            "Examples:\n"
            "  obtools make-sequence\n"
            "  obtools make-sequence --user CK --project 3000 --label Proteome\n"
            "  obtools make-sequence --from-collection /DDB/CK/E_Proteome2025\n"
            "  obtools make-sequence --experiment /DDB/CK/E_Proteome2025 --n 30 --ms-method dda"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ms_p.add_argument("--user", "-u", metavar="INITIALS",
                      help="User initials (e.g. CK, SK) — prompted if omitted")
    ms_p.add_argument("--project", "-p", metavar="CODE",
                      help="Project code, e.g. 3000 (IMP) or 9129 (BioMS booking) — prompted if omitted")
    ms_p.add_argument("--label", metavar="TEXT",
                      help="Free-text label for the sequence (e.g. Proteome, Phospho) — prompted if omitted")
    ms_p.add_argument("--data-path", metavar="PATH",
                      help=r"Data path on Timmie PC (default: D:\Data\{USER})")

    # Sample source (mutually exclusive)
    src_grp = ms_p.add_mutually_exclusive_group()
    src_grp.add_argument("--from-collection", metavar="PATH",
                         help="Fetch existing BIOL_DDB samples from this OpenBIS collection")
    src_grp.add_argument("--n", type=int, metavar="N",
                         help="Register N new BIOL_DDB samples (requires --experiment)")
    ms_p.add_argument("--experiment", "-e", metavar="PATH",
                      help="OpenBIS experiment for new sample registration (used with --n)")

    # Method selection
    ms_p.add_argument("--lc-method", metavar="KEY",
                      choices=["30spd", "60spd", "100spd", "200spd", "300spd"],
                      help="LC method key (default: 30spd)")
    ms_p.add_argument("--ms-method", metavar="KEY",
                      choices=["dia-long", "dia-short", "dda", "phospho", "p2"],
                      help="MS method key (default: dia-long for 30spd)")
    ms_p.add_argument("--injections", type=int, metavar="N", default=None,
                      help="Number of injections per sample (default: 1)")

    ms_p.add_argument("--output", "-o", metavar="FILE",
                      help="Output .xlsx path (default: auto-generated from user/project/label)")
    ms_p.add_argument("--dry-run", action="store_true",
                      help="Preview without writing the file or registering samples")
    ms_p.add_argument("--no-confirm", action="store_true",
                      help="Skip registration confirmation prompt")
    # Pass-through flags for register_samples (used when --n is set)
    _reg_common(ms_p)

    # ---- vocab ----
    vc = sub.add_parser(
        "vocab",
        help="List controlled vocabulary terms from OpenBIS",
        description=(
            "Fetches vocabulary terms live from OpenBIS.\n"
            "Use this before filling in a registration TSV to see valid TREATMENT_TYPE values etc.\n\n"
            "Examples:\n"
            "  obtools vocab TREATMENT_TYPE\n"
            "  obtools vocab BIOLOGICAL_SAMPLE_TYPE\n"
            "  obtools vocab                          # list all vocabularies"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    vc.add_argument("vocab_code", nargs="?", metavar="VOCAB_CODE",
                    help="Vocabulary code to look up (omit to list all vocabularies)")

    return p


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_HANDLERS = {
    "connect":             cmd_connect,
    "download":            cmd_download,
    "download-collection": cmd_download_collection,
    "info":                cmd_info,
    "search":              cmd_search,
    "upload":              cmd_upload,
    "upload-fasta":        cmd_upload_fasta,
    "upload-lib":          cmd_upload_lib,
    "register":            cmd_register,
    "register-tsv":        cmd_register_tsv,
    "vocab":               cmd_vocab,
    "ingest":              cmd_ingest,
    "make-sequence":       cmd_make_sequence,
}


def main():
    parser = build_parser()
    args = parser.parse_args()
    handler = _HANDLERS.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)
