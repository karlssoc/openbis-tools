"""
Credential loading — single source of truth.

Priority (lowest to highest):
  1. ~/.openbis/credentials  (KEY=VALUE file)
  2. Environment variables   (OPENBIS_URL, OPENBIS_USERNAME, OPENBIS_PASSWORD)

No JSON config, no priority chains, no surprises.
"""

import os
import sys
from pathlib import Path

CREDS_FILE = Path.home() / ".openbis" / "credentials"

_KEYS = {
    "OPENBIS_URL",
    "OPENBIS_USERNAME",
    "OPENBIS_PASSWORD",
    "OBTOOLS_DOWNLOAD_DIR",
    "OBTOOLS_VERIFY_CERTS",
}


def load() -> dict:
    """Return credentials dict. Env vars override file values."""
    creds: dict = {}

    # 1. Read credentials file
    if CREDS_FILE.exists():
        with open(CREDS_FILE) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key in _KEYS:
                    creds[key] = value

    # 2. Env vars override
    for key in _KEYS:
        if key in os.environ:
            creds[key] = os.environ[key]

    return creds


def require() -> dict:
    """Load credentials and exit with a clear message if any required key is missing."""
    creds = load()
    missing = [k for k in ("OPENBIS_URL", "OPENBIS_USERNAME", "OPENBIS_PASSWORD") if not creds.get(k)]
    if missing:
        print(f"❌ Missing credentials: {', '.join(missing)}")
        print(f"   Edit {CREDS_FILE} or set environment variables.")
        print(f"   Run:  cp credentials.example ~/.openbis/credentials")
        sys.exit(1)
    return creds
