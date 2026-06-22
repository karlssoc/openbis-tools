# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for a single-file `obtools` executable.

Build (from the repo root, after `pip install -e '.[secure]' pyinstaller`):
    pyinstaller --clean --noconfirm packaging/obtools.spec

Produces dist/obtools (macOS/Linux) or dist/obtools.exe (Windows).
PyInstaller is NOT a cross-compiler: build on the OS you want to target.
"""

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

# pybis ships data files and many submodules — pull everything it needs.
datas, binaries, hiddenimports = collect_all("pybis")

# obtools uses lazy imports inside handler functions; collect them explicitly
# so nothing is dropped from the frozen bundle.
hiddenimports += collect_submodules("obtools")
# cryptography is loaded lazily for encrypted credentials.
hiddenimports += ["cryptography"]

a = Analysis(
    [os.path.join(SPECPATH, "launch.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="obtools",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
