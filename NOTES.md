# Notes

Field notes from using obtools on real lookups: bugs, gaps and feature ideas. Not a changelog.

## 2026-10-10 — `locate` while staging septoform mouse DIA (142 runs, v0.2.6)

**Status (2026-10-10, verified live and fixed):** `--collection` is now optional for both
modes. Without it, `locate` runs one bulk `FILE_NAME` query, which takes about 25 s for all 62,642 RAW_DATA
datasets. Every one of them has `FILE_NAME` set. The new `--registration-date` flag narrows the query. The
output now has `md5`, `size`, `registration_date` and `duplicate` columns. `--save` streams rows
while the scan runs, and filenames that were not found are listed. Correction: the help didn't
claim the collection was optional. It said it was required, which matched the code. The wrong
part was "requires datasets ingested with obtools". Also fixed an unreported bug:
inline-prop matching never ran, because pybis returns `Things`, not a DataFrame. So
per-collection `--from-file` always fell back to one fetch per dataset.

### Bug: `locate --from-file` requires `--collection`, though the help says it's optional

The CLI help (`cli.py`, locate epilog) says "--collection is optional (used as post-filter)",
but `locate_datasets()` exits with "At least one --collection is required" before checking
the mode (`locate.py:39`). The module docstring says `--from-file` requires `--collection`.
Choose one: make `--from-file` work without a collection (see below) or fix the help.

### `file_name` is not specific to obtools ingest

The help says `--from-file` "requires datasets to have been ingested with obtools". In fact
datamover-registered RAW datasets (`/MS_DATA/...`) have `FILE_NAME` set too. This single bulk
query on al found runs in any collection:

```python
o.get_datasets(type="RAW_DATA", registrationDate=">2020-01-15", count=None,
               props=["FILE_NAME"]).df
```

So `--from-file` without `--collection` could run one bulk query (optionally bounded by
`--registration-date`) and match client-side, so you don't need to know the collection.

### Runs aren't always in the collection the run name implies

`CK_P2209_*` and `CK_P2304_*` sample runs are registered against BIOL_DDB samples in
`/DDB/CK/E290520` and `/DDB/CK/E290549`, not under `/MS_DATA/PYTHIA/2022-09` or `2023-04`.
A collection-scoped `--pattern` scan silently returns 0 for them. The global `file_name`
query above would have found them in one step.

### Duplicates and reused samples

- Some runs are registered twice with the same MD5 (e.g. `CK_P2304_010–021`). `locate`
  prints both, which is fine; the saved CSV should keep both with a flag (or prefer the oldest).
- A DDB sample can hold unrelated runs (`DDBS333935`: CK_P2304_028, CK_P2210_253,
  CK_P2303_172). Resolve runs by file name, never by sample.

### Feature: include MD5 and size in `locate` output

RAW datasets carry `md5_checksum`, `file_size` and `file_name` properties (datamover and DDB
registrations alike). With `props="*"` they come back inline, so adding `md5`/`size` columns
to the CSV costs no extra calls. This makes download verification and the gap check
(see vault `intelligence/openbis-reliability`) possible without the grid export.

### Run lookups on al, not over the VPN

The same 6-collection `--pattern` scan took about 1 min on al and more than 10 min from the
laptop over VPN, and it died when the VPN dropped. Long lookups and downloads should run on
an LU host under `nohup`. Smaller related issue: `--save` only writes at the end, so an
interrupted scan loses everything. Writing per collection or appending rows would help.

### pybis snippets that worked

```python
from obtools import connection
o = connection.get()
d = o.get_dataset(permid); d.props.all()          # md5_checksum, file_size, file_name
o.get_datasets(sample="/DDB/CK/DDBS333935")       # all runs on a sample
o.get_experiments(project="/DDB/ALE_MS")          # experiments in a DDB project
```
