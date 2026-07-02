# Minerva instrument-PC scheduled tasks

Two scheduled tasks run on the Minerva (HF-X) instrument PC under a dedicated
standard user (`medk-cka`), not the shared `admin` account:

1. **QC raw-file upload** (`obtools-qc.bat`) — uploads QC `.raw` files to
   OpenBIS via `obtools ingest`. Runs headless (whether logged on or not).
2. **QC dashboard sync** (`qc-dashboard-sync.bat`) — pulls the QC dashboard
   HTML from the LU SMB share to a local copy for viewing at the bench.

---

# 1. Unattended QC raw-file upload

Continuously upload QC `.raw` files from an acquisition PC to OpenBIS using a
scheduled `obtools ingest` run. Designed for a locked-down instrument PC where
the tool runs as a dedicated standard user (not the shared `admin` account).

## Prerequisites

- A dedicated, password-protected **standard** user account (e.g. `medk-cka`),
  separate from the instrument's default `admin`.
- `obtools` installed for that user via pipx (the `[secure]` extra is required
  for encrypted-password support):
  ```powershell
  pipx install --force ".\openbis_tools-<version>-py3-none-any.whl[secure]"
  obtools --version
  ```
- Credentials stored once: `obtools cred set` (encrypted, passphrase-derived).
  Prefer a **dedicated OpenBIS service account scoped to the QC space**, not a
  personal login — it limits blast radius if the PC is compromised.

## 1. Persist the decryption passphrase

The scheduled task has no console, so the passphrase must come from the
environment, not an interactive prompt. `setx` writes it to the user's
environment (a session-only `$env:` var will NOT be inherited by the task):

```powershell
setx OBTOOLS_PASSPHRASE "your-real-passphrase"
```

`obtools` reads `OBTOOLS_PASSPHRASE` and decrypts `OPENBIS_PASSWORD_ENC`
non-interactively. The secret is recoverable by whoever controls this account
(or an admin) — that is inherent to any unattended unlock; the scoped service
account above is the real mitigation.

## 2. Install the wrapper script

Copy `obtools-qc.bat` to `C:\Tools\obtools-qc.bat` and edit the variables at the
top (`RAW_DIR`, `COLLECTION`, `SINCE`, `MIN_AGE_MINUTES`).

- `--skip-existing` makes repeated runs idempotent via a local ledger at
  `%USERPROFILE%\.openbis\ingested.json` (matched on name + size + mtime).
- `--min-age-minutes` skips files still being acquired. Set it comfortably
  longer than your longest gradient.
- `--since` is the go-live cutoff so the backlog of old QC files is ignored.
- `--skip-samples` uploads the RAW_DATA dataset only (no BIOL_DDB sample).

## 3. Register the scheduled task

Every 15 minutes, as the dedicated user, non-elevated:

```powershell
schtasks /Create /TN "obtools-qc-upload" /TR "C:\Tools\obtools-qc.bat" `
  /SC MINUTE /MO 15 /RU medk-cka /RP * /RL LIMITED /F
```

`/RP *` prompts once for the account password and stores it so the task runs
whether the user is logged on or not.

## 4. Verify

```powershell
schtasks /Run /TN "obtools-qc-upload"
Get-Content $env:USERPROFILE\obtools-qc.log -Tail 40 -Wait
```

Confirm: new files upload with `acquisition_date` / `file_size` /
`instrument_*` populated, already-uploaded files report *Already ingested*,
the run ends with `exit 0`, and no passphrase prompt appears.

## Management

```powershell
schtasks /Query  /TN "obtools-qc-upload" /V /FO LIST   # status / last result
schtasks /End    /TN "obtools-qc-upload"               # stop a running instance
schtasks /Change /TN "obtools-qc-upload" /DISABLE      # pause the schedule
schtasks /Delete /TN "obtools-qc-upload" /F            # remove
```

## Notes

- **If the log shows a passphrase failure**, the task is not inheriting the
  user env var. Fallback: uncomment the `set "OBTOOLS_PASSPHRASE=..."` line in
  the `.bat` and restrict the file:
  ```powershell
  icacls C:\Tools\obtools-qc.bat /inheritance:r /grant:r "medk-cka:R" "SYSTEM:F" "Administrators:F"
  ```
- **Log growth**: `obtools-qc.log` is appended every run. Rotate or truncate
  periodically (e.g. a second daily task that keeps the last N lines).
- If `obtools` is not found, the pipx shim PATH may not load for the task;
  the `.bat` already calls it by full path (`%USERPROFILE%\.local\bin\obtools.exe`).

---

# 2. QC dashboard sync

An automated QC analysis on the LU Linux HPC writes a dashboard HTML to an SMB
share. This task copies that dashboard to a local folder on the instrument PC so
it can be viewed at the bench without keeping the share open.

- Source (LU SMB, Windows UNC form):
  `\\uw.lu.se\research\LU25D1040-imp_arch\General\Data\imp\minerva\qc\qc-dashboard.html`
- The dashboard is a single **self-contained** HTML (Plotly with embedded data);
  only that one file is copied — the sibling `qc.sqlite` is not needed to view it.

## Authentication

The share requires the LU login (`medk-cka@uw.lu.se`). Because the task runs
**in the logged-on `medk-cka` session** (`/IT`), it reuses that session's
existing authentication to `\\uw.lu.se` — **no stored credential is needed** and
the UNC path is accessed directly (no mapped drive).

> Only one connection per server per session is allowed. If a
> `New-PSDrive`/`net use` to `\\uw.lu.se` already exists with different
> credentials you get *"Multiple connections ... not allowed"* — clear it with
> `net use \\uw.lu.se\research /delete` first.

## Install and register

Copy `qc-dashboard-sync.bat` to the PC (e.g. `C:\QC\qc-dashboard-sync.bat`),
create the destination, and register the task:

```powershell
New-Item -ItemType Directory -Force C:\QC\dashboard | Out-Null

schtasks /Create /TN "qc-dashboard-sync" /TR "C:\QC\qc-dashboard-sync.bat" `
  /SC MINUTE /MO 30 /RU medk-cka /IT /RL LIMITED /F
```

## Verify

```powershell
schtasks /Run /TN "qc-dashboard-sync"
Get-Content $env:USERPROFILE\qc-dashboard-sync.log -Tail 20
```

Confirm `C:\QC\dashboard\qc-dashboard.html` appears/updates. robocopy exit
codes < 8 are success (`1` = copied, `0` = already current).

## Headless variant (nobody logged in)

Bare UNC access works only because the interactive session carries the LU auth.
To run with nobody logged in, drop `/IT` and instead authenticate inside the
task with a DPAPI-encrypted credential (only `medk-cka` on this machine can
decrypt it):

```powershell
# once, in an interactive medk-cka session:
Get-Credential -UserName "medk-cka@uw.lu.se" -Message "LU share" |
  Export-Clixml "$env:USERPROFILE\lu-share.cred.xml"
```

Then use a `.ps1` task that does
`Import-Clixml` → `New-PSDrive -Credential` → `Copy-Item` → `Remove-PSDrive`,
registered with `/RU medk-cka /RP *` (no `/IT`).
