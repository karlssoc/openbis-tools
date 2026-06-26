# Unattended QC raw-file upload (Windows instrument PC)

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
