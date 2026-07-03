# qc-dashboard-sync.ps1 - headless: copy QC dashboard HTML from the LU SMB share.
# Runs whether-logged-on-or-not; authenticates with a DPAPI-encrypted credential
# (lu-share.cred.xml) that only medk-cka on this machine can decrypt.
# See deploy/README.md for the credential-seeding and task-registration steps.
$ErrorActionPreference = "Stop"
$log = "$env:USERPROFILE\qc-dashboard-sync.log"
"==== $(Get-Date) sync start ====" | Add-Content $log
try {
    $cred = Import-Clixml "$env:USERPROFILE\lu-share.cred.xml"
    New-PSDrive -Name Q -PSProvider FileSystem -Root "\\uw.lu.se\research" -Credential $cred -ErrorAction Stop | Out-Null
    Copy-Item "Q:\LU25D1040-imp_arch\General\Data\imp\minerva\qc\qc-dashboard.html" "C:\QC\dashboard\qc-dashboard.html" -Force
    $ts = (Get-Item "C:\QC\dashboard\qc-dashboard.html").LastWriteTime
    "copied OK (mtime $ts)" | Add-Content $log
}
catch {
    "ERROR: $($_.Exception.Message)" | Add-Content $log
    exit 1
}
finally {
    Remove-PSDrive -Name Q -ErrorAction SilentlyContinue
}
