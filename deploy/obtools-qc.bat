@echo off
REM ============================================================================
REM  obtools-qc.bat - unattended QC raw-file upload to OpenBIS
REM
REM  Run by Windows Task Scheduler as a dedicated standard user (e.g. medk-cka)
REM  on the instrument PC, every ~15 min. See deploy/README.md for full setup.
REM
REM  The decryption passphrase is read from the OBTOOLS_PASSPHRASE environment
REM  variable (set once per user with:  setx OBTOOLS_PASSPHRASE "...").
REM  Keep the secret OUT of this file unless the task cannot inherit the env
REM  var, in which case uncomment the line below and lock the file with icacls.
REM ============================================================================

setlocal

REM --- edit these for your setup ---------------------------------------------
set "RAW_DIR=D:\QC\raw"
set "COLLECTION=/DDB/CK/E290597"
set "SINCE=2026-06-26"
set "MIN_AGE_MINUTES=15"
REM ---------------------------------------------------------------------------

REM Fallback only: uncomment if the scheduled task cannot see the user env var.
REM set "OBTOOLS_PASSPHRASE=your-passphrase"

REM Force UTF-8 so emoji progress output never hits the cp1252 console codec
REM (obtools >= 0.2.6 also handles this itself; harmless to keep).
set "PYTHONUTF8=1"

set "OBTOOLS=%USERPROFILE%\.local\bin\obtools.exe"
set "LOG=%USERPROFILE%\obtools-qc.log"

echo ==== %DATE% %TIME% ingest start ==== >> "%LOG%"
"%OBTOOLS%" ingest "%RAW_DIR%" --collection %COLLECTION% ^
  --skip-samples --skip-existing --min-age-minutes %MIN_AGE_MINUTES% --since %SINCE% >> "%LOG%" 2>&1
echo ==== exit %ERRORLEVEL% ==== >> "%LOG%"

endlocal
