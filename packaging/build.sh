#!/usr/bin/env bash
# Build a standalone obtools binary for the current OS (macOS / Linux).
# For a Windows .exe, run packaging/build.ps1 on Windows (PyInstaller does not
# cross-compile) — or use the GitHub Actions workflow.
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m pip install --upgrade pip
python3 -m pip install -e '.[secure]' pyinstaller

python3 -m PyInstaller --clean --noconfirm packaging/obtools.spec

# Seed a portable config folder next to the binary so the artifact is
# portable-by-default: config_root() picks up <dir>/.obtools when present.
mkdir -p dist/.obtools
cp packaging/portable-readme.txt dist/.obtools/README.txt

echo
echo "✅ Built: dist/obtools"
echo "   Copy dist/obtools and dist/.obtools/ to the same folder on the stick,"
echo "   then run:  ./obtools cred set"
