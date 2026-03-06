"""
OpenBIS connection management.

Single function: get() returns an authenticated Openbis instance.
Uses pybis token caching — login once, reuse token automatically.
"""

import sys
from pybis import Openbis
from .auth import require


def get(use_cache: bool = True) -> Openbis:
    """Return an authenticated OpenBIS connection."""
    creds = require()

    verify_certs = creds.get("OBTOOLS_VERIFY_CERTS", "false").lower() in ("true", "1", "yes")

    o = Openbis(creds["OPENBIS_URL"], verify_certificates=verify_certs, use_cache=use_cache)

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
