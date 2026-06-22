"""
Portable config-root resolution.

`obtools` is designed to run from a USB stick on shared acquisition PCs.
To avoid leaving credentials or session tokens behind in the host PC's user
profile, all per-user state (credentials file, pybis token cache, default
download dir) is anchored to a single *config root* resolved here.

Resolution order (first match wins):
  1. $OBTOOLS_HOME                       — explicit override
  2. <dir of obtools executable>/.obtools — a `.obtools/` folder sitting next
     to the obtools.exe / launcher on the stick (the portable case)
  3. ~/.openbis                          — backward-compatible default install

On a normal pip/pipx install nothing changes: the root is ~/.openbis as
before. Drop a `.obtools/` folder next to the executable on a USB stick and
the same binary becomes fully portable with no host-profile footprint.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ENV_HOME = "OBTOOLS_HOME"


def _executable_dir() -> Path | None:
    """Directory holding the running obtools executable / launcher, if known."""
    # PyInstaller / frozen single-file build
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Console-script launcher (e.g. .venv/bin/obtools, Scripts\obtools.exe)
    argv0 = sys.argv[0] if sys.argv else ""
    if argv0:
        p = Path(argv0)
        if p.exists():
            return p.resolve().parent
    return None


def config_root() -> Path:
    """Return the resolved config root (not guaranteed to exist yet)."""
    env = os.environ.get(_ENV_HOME)
    if env:
        return Path(env).expanduser()

    exe_dir = _executable_dir()
    if exe_dir is not None and (exe_dir / ".obtools").is_dir():
        return exe_dir / ".obtools"

    return Path.home() / ".openbis"


def ensure_config_root() -> Path:
    """Return the config root, creating it (mode 0700) if missing."""
    root = config_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass  # e.g. FAT32 on a USB stick — no POSIX perms
    return root


def token_dir() -> Path:
    """Directory for the pybis session-token cache, under the config root."""
    return config_root() / ".pybis"
