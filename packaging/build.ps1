# Build a standalone obtools.exe on Windows.
# Run from any directory:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

python -m pip install --upgrade pip
python -m pip install -e ".[secure]" pyinstaller

python -m PyInstaller --clean --noconfirm packaging/obtools.spec

# Seed a portable config folder next to the exe so the artifact is
# portable-by-default: config_root() picks up <dir>\.obtools when present.
New-Item -ItemType Directory -Force -Path dist\.obtools | Out-Null
Copy-Item packaging\portable-readme.txt dist\.obtools\README.txt -Force

Write-Host ""
Write-Host "Built: dist\obtools.exe"
Write-Host "Copy dist\obtools.exe and dist\.obtools\ to the same folder on the stick,"
Write-Host "then run:  .\obtools.exe cred set"
