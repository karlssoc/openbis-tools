# openbis-tools

Proteomics-focused OpenBIS CLI toolkit for LU-IMP group. Installs a single command, `obtools`, covering sample registration, dataset upload (FASTA, spectral libraries), download, search, and controlled vocabulary lookup.

---

## Installation

```bash
pipx install git+https://github.com/karlssoc/openbis-tools.git
```



Verify:

```bash
obtools --help
```

---

## Credentials

```bash
mkdir -p ~/.openbis && chmod 700 ~/.openbis
cp credentials.example ~/.openbis/credentials
chmod 600 ~/.openbis/credentials
```

Edit `~/.openbis/credentials`:

```
OPENBIS_URL=https://your-server.com/openbis/
OPENBIS_USERNAME=your_username

# Optional
# OBTOOLS_DOWNLOAD_DIR=~/data/openbis
# OBTOOLS_VERIFY_CERTS=false
```

**Store your password in the OS keychain** (recommended — no plaintext passwords):

```bash
# macOS
security add-generic-password -a your_username -s openbis-tools -w

# Windows
cmdkey /generic:openbis-tools /user:your_username /pass:your_password

# Linux (requires libsecret-tools)
secret-tool store --label=openbis-tools service openbis-tools username your_username
```

`obtools` reads the password from the keychain automatically. Environment variables (`OPENBIS_URL`, `OPENBIS_USERNAME`, `OPENBIS_PASSWORD`) override all other sources if set.

Test your connection:

```bash
obtools connect
```

---

## Commands

| Command | Requires connection | Description |
|---|---|---|
| `connect` | yes | Test connection and list spaces |
| `download` | yes | Download a dataset by code |
| `download-collection` | yes | Download all datasets in a collection |
| `download-bruker` | yes | Download Bruker .zip datasets and optionally extract to .d folders |
| `info` | yes | Show dataset details and lineage |
| `ingest` | yes | Discover raw MS files, create samples, upload datasets |
| `search` | yes | Search datasets, samples, experiments |
| `upload` | yes | Upload a file (auto-detect type) |
| `upload-fasta` | yes | Upload a FASTA database |
| `upload-lib` | yes | Upload a DIA-NN spectral library |
| `register` | yes | Create BIOL_DDB samples directly in OpenBIS |
| `register-tsv` | **no** | Generate a registration TSV for offline annotation |
| `vocab` | yes | Look up controlled vocabulary terms |

---

## Sample Registration

### Direct registration (`register`)

Creates BIOL_DDB sample objects directly in OpenBIS via the API. Requires write access.

**Interactive** — omit any field and you will be prompted. Controlled-vocabulary fields (BIOLOGICAL_SAMPLE_TYPE, DIGESTION, etc.) are fetched live from OpenBIS and shown as a numbered list.

```bash
obtools register --experiment /DDB/CK/E_Sepsis2025 --n 8
```

**Scripted** — pass all fields as flags to skip prompts entirely:

```bash
obtools register \
  --experiment /DDB/CK/E_Sepsis2025 \
  --n 12 \
  --prefix SP25 \
  --sample-type PLASMA \
  --tax-id 9606 \
  --digestion iST \
  --desalting C18 \
  --labeling LFQ \
  --comment "Sepsis cohort 2025 batch 1" \
  --no-confirm
```

**Dry run** — preview what will be created without writing anything:

```bash
obtools register -e /DDB/CK/E_Sepsis2025 --n 8 --sample-type PLASMA --dry-run
```

**With parent samples:**

```bash
obtools register -e /DDB/CK/E_Sepsis2025 --n 4 \
  --parents "20250502110701494-1323378,20250502110516300-1323376"
```

**All flags:**

| Flag | Description |
|---|---|
| `--experiment`, `-e` | OpenBIS experiment path (required) |
| `--n` | Number of samples to create (required) |
| `--prefix` | Prefix for `$NAME`, e.g. `SP25` → `SP25_01`, `SP25_02`, … |
| `--sample-type` | `BIOLOGICAL_SAMPLE_TYPE` (CV — prompted if omitted) |
| `--tax-id` | `TAX_ID` (e.g. `9606` = *Homo sapiens*, `10090` = *Mus musculus*) |
| `--digestion` | `DIGESTION` (e.g. `SP3`, `iST`, `FASP`) |
| `--desalting` | `DESALTING` (e.g. `C18`, `SDB-RPS`) |
| `--labeling` | `LABELING` (e.g. `LFQ`, `TMT`) |
| `--fractionation` | `FRACTIONATION` (e.g. `High_pH`, `SAX`) |
| `--sample-prep` | `SAMPLE_PREPARATION` free text |
| `--comment` | `COMMENT` — same for all samples |
| `--em-patients` | `EM_PATIENTS` identifiers |
| `--ck-patients` | `CK_PATIENTS` identifiers |
| `--container` | Container sample code |
| `--parents` | Comma-separated parent sample codes |
| `--dry-run` | Preview only, nothing created |
| `--no-confirm` | Skip confirmation prompt (for scripting) |

---

### Offline TSV registration (`register-tsv`)

Generates a correctly structured tab-separated file for OpenBIS batch import — **no connection required**. Useful when outside VPN, or to hand a file to an admin.

**Basic:**

```bash
obtools register-tsv --experiment /DDB/CK/E_Sepsis2025 --n 8
```

Output: `2026-03-06_E_Sepsis2025.txt`

**With treatment annotation columns:**

Use `--treatments N` to append N pairs of `TREATMENT_TYPEn` / `TREATMENT_VALUEn` columns. Fill these in before submitting — see `obtools vocab TREATMENT_TYPE` for valid type values.

```bash
obtools register-tsv \
  --experiment /DDB/CK/E_Sepsis2025 \
  --n 12 \
  --prefix SP25 \
  --sample-type PLASMA \
  --tax-id 9606 \
  --digestion iST \
  --labeling LFQ \
  --treatments 2 \
  --out 2026-03_Sepsis_batch1.txt
```

This produces a file with 18 columns:

```
container  parents  experiment  $NAME  BIOLOGICAL_SAMPLE_TYPE  TAX_ID
SAMPLE_PREPARATION  FRACTIONATION  DIGESTION  DESALTING  LABELING  COMMENT
EM_PATIENTS  CK_PATIENTS  TREATMENT_TYPE1  TREATMENT_VALUE1
TREATMENT_TYPE2  TREATMENT_VALUE2
```

Open the file in Excel or Numbers, fill in the blank columns, then import via **OpenBIS web UI → Admin → Batch register → BIOL_DDB**.

**Additional flags:**

| Flag | Description |
|---|---|
| `--treatments N` | Add N `TREATMENT_TYPEn` / `TREATMENT_VALUEn` column pairs |
| `--out FILE` | Output filename (default: `YYYY-MM-DD_<experiment>.txt`) |
| `--list-types` | Print common `BIOLOGICAL_SAMPLE_TYPE` values and exit |

All `--sample-type`, `--tax-id`, `--digestion` etc. flags from `register` are also available to pre-fill shared values.

---

## Controlled Vocabulary (`vocab`)

Look up valid CV terms from your OpenBIS instance before filling in a registration TSV or the interactive `register` prompts.

```bash
# List all vocabularies defined in this OpenBIS instance
obtools vocab

# Show all valid terms for TREATMENT_TYPE
obtools vocab TREATMENT_TYPE

# Other commonly used vocabularies
obtools vocab BIOLOGICAL_SAMPLE_TYPE
obtools vocab DIGESTION
obtools vocab LABELING
obtools vocab DESALTING
obtools vocab FRACTIONATION
```

Example output for `obtools vocab TREATMENT_TYPE`:

```
📖 TREATMENT_TYPE  (12 terms)

  CODE                                 LABEL
  ───────────────────────────────────  ──────────────────────────────
  ANTIBIOTIC                           Antibiotic treatment
  CYTOKINE                             Cytokine stimulation
  HORMONE                              Hormone treatment
  INHIBITOR                            Enzyme/pathway inhibitor
  ...

  Use these CODE values in your registration TSV.
```

---

## Dataset Upload

### FASTA databases (`upload-fasta`)

Automatically extracts sequence count, species breakdown, and file size from the FASTA file and stores them as dataset properties.

```bash
obtools upload-fasta uniprot_human_20240801.fasta \
  --version "2024.08" \
  --collection /DDB/CK/FASTA
```

Preview before uploading:

```bash
obtools upload-fasta database.fasta --version "1.0" --dry-run
```

With a manually specified parent dataset:

```bash
obtools upload-fasta processed.fasta --version "2.0" \
  --parent-dataset 20250502110701494-1323378
```

### Spectral libraries (`upload-lib`)

Parses a DIA-NN log file to extract metadata (FASTA reference, protein/precursor counts, DIA-NN version, modifications, parameters) and uploads the log alongside the library.

```bash
obtools upload-lib library.tsv \
  --log-file diann.log \
  --collection /DDB/CK/PREDSPECLIB
```

**Auto-link** — searches OpenBIS for the FASTA database referenced in the DIA-NN log and asks you to confirm parent linking interactively:

```bash
obtools upload-lib library.tsv --log-file diann.log --auto-link
```

Manual parent:

```bash
obtools upload-lib library.tsv --log-file diann.log \
  --parent-dataset 20250502110701494-1323378
```

### Generic upload (auto-detect type)

```bash
obtools upload myfile.fasta        # detected as fasta
obtools upload mylib.tsv           # detected as spectral_library
obtools upload datafile.txt        # uploaded as unknown type
```

---

## Raw Data Ingest (`ingest`)

Scans a directory for Thermo `.raw` files and Bruker `.d` directories, creates one `BIOL_DDB` sample per acquisition, and uploads each file as a `RAW_DATA` dataset linked to that sample.

Bruker `.d` directories are automatically compressed to `.zip` before upload (stdlib `zipfile` — no external tools). macOS metadata (`__MACOSX/`, `.DS_Store`, `._*`) is excluded from archives.

Dataset metadata populated automatically:

| Property | Thermo `.raw` | Bruker `.d` |
|---|---|---|
| `File Name` | original filename | original `.d` dir name |
| `File Size` | file size in bytes | zip archive size in bytes |
| `ACQUISITION_DATE` | file modification time | read from `analysis.tdf` |
| `INSTRUMENT_SN` | `MS:1000529` (default) | `MS:1003404` |
| `INSTRUMENT_NAME` | `Q_Exactive_HF-X_Orbitrap` (default) | `timsTOF_HT` |

**Basic usage:**

```bash
obtools ingest /data/runs/ --collection /DDB/CK/E_Sepsis2025
```

**Create the collection if it does not exist:**

```bash
obtools ingest /data/runs/ --collection /DDB/CK/E_NewStudy --create-collection
```

**Preview without writing anything:**

```bash
obtools ingest /data/runs/ --collection /DDB/CK/E_Sepsis2025 --dry-run
```

**Override Thermo instrument defaults** (e.g. if files came from a different instrument):

```bash
obtools ingest /data/runs/ --collection /DDB/CK/E_Sepsis2025 \
  --raw-instrument-sn MS:1000031 \
  --raw-instrument-name "LTQ_Orbitrap"
```

**Upload datasets only, skip sample creation:**

```bash
obtools ingest /data/runs/ --collection /DDB/CK/E_Sepsis2025 --skip-samples
```

**All flags:**

| Flag | Description |
|---|---|
| `--collection`, `-c` | OpenBIS collection path (required) |
| `--create-collection` | Create the collection if it does not exist |
| `--collection-type` | Collection type when creating (default: `MS_EXPERIMENT`) |
| `--dataset-type` | Dataset type for uploaded files (default: `RAW_DATA`) |
| `--sample-type` | Sample type to create (default: `BIOL_DDB`) |
| `--prefix` | Prefix for sample `$NAME` (default: source directory name) |
| `--skip-samples` | Upload datasets only, do not create samples |
| `--raw-instrument-sn` | `INSTRUMENT_SN` for Thermo `.raw` files (default: `MS:1000529`) |
| `--raw-instrument-name` | `INSTRUMENT_NAME` for Thermo `.raw` files (default: `Q_Exactive_HF-X_Orbitrap`) |
| `--dry-run` | Preview everything without writing to OpenBIS |

---

## Download

### Single or multiple datasets

```bash
# List files without downloading
obtools download 20250807085639331-1331542 --list-only

# Download to default directory (~/.openbis/data or OBTOOLS_DOWNLOAD_DIR)
obtools download 20250807085639331-1331542

# Download to specific location
obtools download 20250807085639331-1331542 --output ~/data/sepsis/

# Download multiple datasets at once
obtools download 20250807085639331-1331542 20250807085639331-1331543 20250807085639331-1331544
```

### Entire collection

```bash
# List datasets in a collection
obtools download-collection /DDB/CK/FASTA --list-only

# Download all (cap at 5)
obtools download-collection /DDB/CK/FASTA --limit 5 --output ~/data/fasta/

# Download everything
obtools download-collection /DDB/CK/PREDSPECLIB --output ~/data/libraries/
```

All download commands skip datasets that are already present in the output directory.
Use `--force` to re-download.

### Bruker TimsTOF (.zip → .d)

For Bruker datasets stored as `.zip` archives in OpenBIS, `download-bruker` downloads
and optionally extracts to `.d` folders in one step. Already-downloaded datasets and
already-extracted `.d` folders are skipped automatically.

```bash
# Download a full collection and extract .d folders (4 parallel jobs)
obtools download-bruker --collection /DDB/DI_TANG_MS/E290847 \
    --output input/raw/E290847 \
    --extract-to input/raw/d/E290847 \
    --jobs 4

# Download specific dataset codes only
obtools download-bruker DDBS377561 DDBS377562 \
    --output input/raw/E290847 \
    --extract-to input/raw/d/E290847

# Download without extracting
obtools download-bruker --collection /DDB/DI_TANG_MS/E290847 \
    --output input/raw/E290847

# List datasets without downloading
obtools download-bruker --collection /DDB/DI_TANG_MS/E290847 \
    --output input/raw/E290847 --list-only

# Re-download and re-extract everything
obtools download-bruker --collection /DDB/DI_TANG_MS/E290847 \
    --output input/raw/E290847 \
    --extract-to input/raw/d/E290847 \
    --force
```

The zip contents are extracted directly into `<name>.d/`, mirroring
`unzip file.zip -d name.d`. A zip containing `data/` → `name.d/data/`.

---

## Search

```bash
# Search datasets by keyword
obtools search proteome

# Filter by space and dataset type
obtools search --space DDB --dataset-type BIO_DB --limit 10

# Filter by property value
obtools search --property version --property-value "2024.08"

# Filter by registration date
obtools search --registration-date ">2024-01-01"

# Relationship queries
obtools search --children-of 20250502110701494-1323378
obtools search --parents-of  20250502110516300-1323376

# Save results to CSV
obtools search --space DDB --dataset-type BIO_DB --save results.csv
obtools search --children-of 20250502110701494-1323378 --save children.csv

# Search samples or experiments
obtools search sepsis --type samples
obtools search --type all
```

---

## Dataset Info and Lineage

```bash
# Basic info
obtools info 20250502110516300-1323376

# Full lineage — show parents and children
obtools info 20250502110516300-1323376 --lineage
```

---

## Credential reference

`~/.openbis/credentials` — KEY=VALUE, one per line. Lines starting with `#` are ignored. Values may be quoted or unquoted.

| Key | Required | Description |
|---|---|---|
| `OPENBIS_URL` | yes | Full server URL including `/openbis/` |
| `OPENBIS_USERNAME` | yes | Your OpenBIS username |
| `OPENBIS_PASSWORD` | no* | Password — prefer macOS Keychain (see below) |
| `OBTOOLS_DOWNLOAD_DIR` | no | Default download directory (default: `~/data/openbis`) |
| `OBTOOLS_VERIFY_CERTS` | no | SSL certificate verification: `true` or `false` (default: `false`) |

\* `OPENBIS_PASSWORD` is required but can be stored in the OS keychain instead of the file.

**Credential priority (highest wins):** environment variable → macOS Keychain → credentials file

**Store password in OS keychain:**
```bash
# macOS
security add-generic-password -a your_username -s openbis-tools -w
# Windows
cmdkey /generic:openbis-tools /user:your_username /pass:your_password
# Linux
secret-tool store --label=openbis-tools service openbis-tools username your_username
```
