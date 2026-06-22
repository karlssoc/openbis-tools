"""
Credential loading — single source of truth.

The credentials file lives under the portable config root (see paths.py):
normally ~/.openbis/credentials, or <stick>/.obtools/credentials when run
portably from a USB stick.

Password resolution priority (lowest to highest):
  1. credentials file plaintext   OPENBIS_PASSWORD=...
  2. credentials file encrypted   OPENBIS_PASSWORD_ENC=...  (prompts passphrase)
  3. OS keychain                  (macOS/Windows/Linux; opportunistic)
  4. environment variable         OPENBIS_PASSWORD

For the portable USB case prefer the encrypted form: `obtools cred set` writes
an OPENBIS_PASSWORD_ENC token (passphrase-derived, scrypt + Fernet) so no
readable password is left on the stick, and nothing touches the host PC's
keychain or profile.

Store the password in the OS keychain instead (non-portable installs):
  macOS:   security add-generic-password -a <username> -s openbis-tools -w
  Windows: cmdkey /generic:openbis-tools /user:<username> /pass:<password>
  Linux:   secret-tool store --label="openbis-tools" service openbis-tools username <username>
"""

from __future__ import annotations

import base64
import getpass
import os
import platform
import subprocess
import sys
from pathlib import Path

from .paths import config_root, ensure_config_root

_KEYCHAIN_SERVICE = "openbis-tools"

_KEYS = {
    "OPENBIS_URL",
    "OPENBIS_USERNAME",
    "OPENBIS_PASSWORD",
    "OPENBIS_PASSWORD_ENC",
    "OBTOOLS_DOWNLOAD_DIR",
    "OBTOOLS_VERIFY_CERTS",
}

_SYSTEM = platform.system()   # "Darwin", "Windows", "Linux"


def creds_file() -> Path:
    """Path to the credentials file under the current config root."""
    return config_root() / "credentials"


# ---------------------------------------------------------------------------
# Passphrase-encrypted password (scrypt KDF + Fernet)
# ---------------------------------------------------------------------------

def _require_cryptography():
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError:
        print("❌ Encrypted passwords need the 'cryptography' package.")
        print("   Install it with:  pip install 'openbis-tools[secure]'")
        sys.exit(1)
    return Fernet, Scrypt


def _derive_key(passphrase: str, salt: bytes):
    Fernet, Scrypt = _require_cryptography()
    kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def encrypt_password(password: str, passphrase: str) -> str:
    """Return a 'salt:token' string safe to store in the credentials file."""
    from cryptography.fernet import Fernet
    salt = os.urandom(16)
    token = Fernet(_derive_key(passphrase, salt)).encrypt(password.encode())
    return f"{base64.urlsafe_b64encode(salt).decode()}:{token.decode()}"


def decrypt_password(enc: str, passphrase: str) -> str | None:
    """Decrypt a 'salt:token' string. Returns None on wrong passphrase / corrupt token."""
    from cryptography.fernet import Fernet, InvalidToken
    try:
        salt_b64, token = enc.split(":", 1)
        salt = base64.urlsafe_b64decode(salt_b64)
        return Fernet(_derive_key(passphrase, salt)).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


# ---------------------------------------------------------------------------
# OS keychain read / write
# ---------------------------------------------------------------------------

def _keychain_get(username: str) -> str | None:
    """Look up the OpenBIS password for *username* from the OS keychain."""
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
            # Windows Credential Manager via the CredentialManager PS module.
            # Not present on a stock machine — fails closed, returns None.
            script = (
                f"(Get-StoredCredential -Target '{_KEYCHAIN_SERVICE}')"
                f".GetNetworkCredential().Password"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                return r.stdout.strip() or None

        elif _SYSTEM == "Linux":
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
    """Store (or update) the password in the OS keychain."""
    try:
        if _SYSTEM == "Darwin":
            r = subprocess.run(
                ["security", "add-generic-password",
                 "-a", username, "-s", _KEYCHAIN_SERVICE, "-w", password, "-U"],
                capture_output=True, text=True, timeout=5,
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
# Credentials file write
# ---------------------------------------------------------------------------

def write_creds_file(values: dict) -> Path:
    """Write KEY=VALUE credentials to the config-root credentials file (mode 0600)."""
    ensure_config_root()
    path = creds_file()
    lines = ["# obtools credentials — see `obtools cred show`"]
    for key in ("OPENBIS_URL", "OPENBIS_USERNAME", "OPENBIS_PASSWORD",
                "OPENBIS_PASSWORD_ENC", "OBTOOLS_DOWNLOAD_DIR", "OBTOOLS_VERIFY_CERTS"):
        if values.get(key):
            lines.append(f"{key}={values[key]}")
    path.write_text("\n".join(lines) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass  # FAT32 on a USB stick — no POSIX perms
    return path


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------

def load() -> dict:
    """Return credentials dict (non-interactive). Priority: file < keychain < env.

    Does NOT prompt for a passphrase; an encrypted password is left as
    OPENBIS_PASSWORD_ENC for require() to resolve interactively.
    """
    creds: dict = {}

    # 1. Read credentials file
    path = creds_file()
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key in _KEYS:
                creds[key] = value

    # 2. Keychain — fill in password if username known and no password set at all
    if not creds.get("OPENBIS_PASSWORD") and not creds.get("OPENBIS_PASSWORD_ENC"):
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


def unlock_password(creds: dict) -> dict:
    """Resolve an encrypted password in-place (prompts for the passphrase once).

    No-op if a plaintext password is already present or no encrypted password
    is stored. Call this only when a password is actually needed (i.e. a fresh
    login), so a valid cached session token never triggers a passphrase prompt.
    """
    if creds.get("OPENBIS_PASSWORD") or not creds.get("OPENBIS_PASSWORD_ENC"):
        return creds

    for attempt in range(3):
        try:
            passphrase = getpass.getpass("Passphrase to unlock OpenBIS password: ")
        except (EOFError, KeyboardInterrupt):
            print("\n❌ No passphrase provided.")
            sys.exit(1)
        pw = decrypt_password(creds["OPENBIS_PASSWORD_ENC"], passphrase)
        if pw:
            creds["OPENBIS_PASSWORD"] = pw
            return creds
        print("  ❌ Wrong passphrase." + (" Try again." if attempt < 2 else ""))
    sys.exit(1)


def require() -> dict:
    """Load credentials, decrypt the password if needed, and exit on missing keys."""
    creds = unlock_password(load())
    missing = [k for k in ("OPENBIS_URL", "OPENBIS_USERNAME", "OPENBIS_PASSWORD") if not creds.get(k)]
    if missing:
        print(f"❌ Missing credentials: {', '.join(missing)}")
        print(f"   Run `obtools cred set`, edit {creds_file()}, or set environment variables.")
        sys.exit(1)
    return creds
