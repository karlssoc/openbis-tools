@echo off
REM ============================================================================
REM  qc-dashboard-sync.bat - pull the QC dashboard HTML from the LU SMB share
REM  to a local copy on the instrument PC, for viewing at the bench.
REM
REM  The dashboard is a single self-contained HTML (Plotly, data embedded); only
REM  that one file is copied. See deploy/README.md for full setup.
REM
REM  Runs as medk-cka with /IT (logged-on session), relying on that session's
REM  existing authentication to \\uw.lu.se - no stored credential needed. For a
REM  headless (nobody-logged-in) variant, use the .ps1 + DPAPI approach in the
REM  README instead.
REM ============================================================================

setlocal

set "SRC=\\uw.lu.se\research\LU25D1040-imp_arch\General\Data\imp\minerva\qc"
set "DST=C:\QC\dashboard"
set "LOG=%USERPROFILE%\qc-dashboard-sync.log"

echo ==== %DATE% %TIME% sync start ==== >> "%LOG%"
robocopy "%SRC%" "%DST%" qc-dashboard.html /R:3 /W:5 /NP /NFL /NDL >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo ==== robocopy rc=%RC% ==== >> "%LOG%"

REM robocopy rc < 8 is success (1 = copied, 0 = already current); >= 8 is failure.
if %RC% GEQ 8 (exit /b 1) else (exit /b 0)

endlocal
