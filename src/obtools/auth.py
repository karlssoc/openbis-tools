"""
Credential loading — single source of truth.

Priority (lowest to highest):
  1. ~/.openbis/credentials  (KEY=VALUE file)
  2. OS keychain             (macOS Keychain, Windows Credential Manager, Linux SecretService)
  3. Environment variables   (OPENBIS_URL, OPENBIS_USERNAME, OPENBIS_PASSWORD)

Keychain service name: "openbis-tools"
Account:               value of OPENBIS_USERNAME from file or env

Store your password (platform-specific):
  macOS:   security add-generic-password -a <username> -s openbis-tools -w
  Windows: cmdkey /generic:openbis-tools /user:<username> /pass:<password>
  Linux:   secret-tool store --label="openbis-tools" service openbis-tools username <username>
           (requires libsecret-tools)
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

CREDS_FILE = Path.home() / ".openbis" / "credentials"
_KEYCHAIN_SERVICE = "openbis-tools"

_KEYS = {
    "OPENBIS_URL",
    "OPENBIS_USERNAME",
    "OPENBIS_PASSWORD",
    "OBTOOLS_DOWNLOAD_DIR",
    "OBTOOLS_VERIFY_CERTS",
}

_SYSTEM = platform.system()   # "Darwin", "Windows", "Linux"


# ---------------------------------------------------------------------------
# OS keychain read / write
# ---------------------------------------------------------------------------

def _keychain_get(username: str) -> str | None:
    """
    Look up the OpenBIS password for *username* from the OS keychain.
    Returns the password string, or None if not found / not supported.
    """
    try:
        if _SYSTEM == "Darwin":
            r = subprocess.run(
                ["security", "find-generic-password",
                 "-a", username, "-s", _KEYCHAIN_SERVICE, "-w"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                return r.stdout.strip() or None

        elif _SYSTEM == "Windows":
            # Windows Credential Manager via PowerShell
            script = (
                f"(Get-StoredCredential -Target '{_KEYCHAIN_SERVICE}' "
                f"-UserName '{username}').GetNetworkCredential().Password"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                return r.stdout.strip() or None

        elif _SYSTEM == "Linux":
            # GNOME libsecret via secret-tool
            r = subprocess.run(
                ["secret-tool", "lookup",
                 "service", _KEYCHAIN_SERVICE, "username", username],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                return r.stdout.strip() or None

    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def keychain_set(username: str, password: str) -> bool:
    """
    Store (or update) the password in the OS keychain.
    Returns True on success, False if the platform tool is unavailable.
    """
    try:
        if _SYSTEM == "Darwin":
            r = subprocess.run(
                ["security", "add-generic-password",
                 "-a", username, "-s", _KEYCHAIN_SERVICE, "-w", password,
                 "-U"],      # -U = update if already exists
                capture_output=True, text=True, timeout=5,
            )
            return r.returncode == 0

        elif _SYSTEM == "Windows":
            script = (
                f"cmdkey /generic:'{_KEYCHAIN_SERVICE}' "
                f"/user:'{username}' /pass:'{password}'"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0

        elif _SYSTEM == "Linux":
            r = subprocess.run(
                ["secret-tool", "store", "--label", _KEYCHAIN_SERVICE,
                 "service", _KEYCHAIN_SERVICE, "username", username],
                input=password, capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0

    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------

def load() -> dict:
    """Return credentials dict. Priority: file < keychain < env vars."""
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

    # 2. Keychain — fill in password if username is known and password missing
    if "OPENBIS_PASSWORD" not in creds:
        username = creds.get("OPENBIS_USERNAME") or os.environ.get("OPENBIS_USERNAME")
        if username:
            pw = _keychain_get(username)
            if pw:
                creds["OPENBIS_PASSWORD"] = pw

    # 3. Env vars override everything
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
        print("   Or store your password in the OS keychain:")
        if _SYSTEM == "Darwin":
            print("     security add-generic-password -a <username> -s openbis-tools -w")
        elif _SYSTEM == "Windows":
            print("     cmdkey /generic:openbis-tools /user:<username> /pass:<password>")
        elif _SYSTEM == "Linux":
            print("     secret-tool store --label=openbis-tools service openbis-tools username <username>")
        sys.exit(1)
    return creds
