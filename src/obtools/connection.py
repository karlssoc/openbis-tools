"""
OpenBIS connection management.

Single function: get() returns an authenticated Openbis instance.
Uses pybis token caching — login once, reuse token automatically.

pybis hardcodes its token cache to ~/.pybis. For the portable USB case we
redirect it under the config root (paths.token_dir()) so no session token is
left behind in a shared acquisition PC's user profile.
"""

import sys
from pybis import Openbis
from .auth import load, unlock_password, creds_file
from .paths import token_dir


def _redirect_token_cache(o: Openbis) -> None:
    """Point pybis's token file at the config root instead of ~/.pybis."""
    hostname = getattr(o, "hostname", None)
    if not hostname:
        return
    tdir = token_dir()
    try:
        tdir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return  # e.g. read-only media — fall back to pybis default
    path = str(tdir / f"{hostname}.token")
    # Instance-level override shadows the class method for save/load/delete.
    o.gen_token_path = lambda os_home=None, _p=path: _p
    # __init__ already tried the default location; re-read from the new path.
    try:
        tok = o._get_saved_token()
        if tok:
            o.set_token(tok)   # validates against the server; raises if stale
    except Exception:
        pass


def get(use_cache: bool = True) -> Openbis:
    """Return an authenticated OpenBIS connection.

    A valid cached session token is reused without resolving the password, so
    an encrypted password never prompts for its passphrase on the happy path.
    The password is only unlocked when a fresh login is actually required.
    """
    creds = load()  # non-interactive

    url = creds.get("OPENBIS_URL")
    username = creds.get("OPENBIS_USERNAME")
    if not url or not username:
        missing = [k for k, v in (("OPENBIS_URL", url), ("OPENBIS_USERNAME", username)) if not v]
        print(f"❌ Missing credentials: {', '.join(missing)}")
        print(f"   Run `obtools cred set`, edit {creds_file()}, or set environment variables.")
        sys.exit(1)

    verify_certs = creds.get("OBTOOLS_VERIFY_CERTS", "false").lower() in ("true", "1", "yes")

    o = Openbis(url, verify_certificates=verify_certs, use_cache=use_cache)
    _redirect_token_cache(o)

    try:
        # Reuse existing session token if valid — no password / passphrase needed
        o.get_spaces()
        return o
    except Exception:
        pass

    # Token missing or expired — unlock the password (may prompt) and log in fresh
    creds = unlock_password(creds)
    if not creds.get("OPENBIS_PASSWORD"):
        print("❌ No password available. Run `obtools cred set` or set OPENBIS_PASSWORD.")
        sys.exit(1)
    try:
        o.login(username, creds["OPENBIS_PASSWORD"], save_token=True)
    except Exception as exc:
        print(f"❌ Login failed: {exc}")
        sys.exit(1)

    return o
