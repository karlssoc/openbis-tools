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
from .auth import require
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
    """Return an authenticated OpenBIS connection."""
    creds = require()

    verify_certs = creds.get("OBTOOLS_VERIFY_CERTS", "false").lower() in ("true", "1", "yes")

    o = Openbis(creds["OPENBIS_URL"], verify_certificates=verify_certs, use_cache=use_cache)
    _redirect_token_cache(o)

    try:
        # Reuse existing session token if valid
        o.get_spaces()
    except Exception:
        # Token missing or expired — log in fresh
        try:
            o.login(creds["OPENBIS_USERNAME"], creds["OPENBIS_PASSWORD"], save_token=True)
        except Exception as exc:
            print(f"❌ Login failed: {exc}")
            sys.exit(1)

    return o
