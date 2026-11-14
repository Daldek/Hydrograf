"""
The sign-in of every admin route (Nogat DEV-15.13, ADR-086).

The header X-Admin-Key is compared in constant time with the key of ADMIN_API_KEY or,
without it, with the text of the file that ADMIN_API_KEY_FILE names (a Docker secret in
production). The file is read on every request, so a rotated key applies at once. A
refusal is ``unauthorized`` (401) with the reason ``admin_key_not_configured`` (the
server has no key: every admin route refuses), ``admin_key_missing`` or
``admin_key_invalid``. No key is generated and none is ever logged.
"""

import contextlib
import secrets
from pathlib import Path

from fastapi import Header

from core.config import get_settings
from core.errors import UnauthorizedError


def _resolve_expected_key() -> str | None:
    """Return the configured admin key, or None when the server has none.

    ADMIN_API_KEY, else the text of the file of ADMIN_API_KEY_FILE without its
    surrounding whitespace; a missing, unreadable or blank file is no key.
    """
    settings = get_settings()
    key = settings.admin_api_key.strip()
    if not key and settings.admin_api_key_file:
        with contextlib.suppress(OSError, UnicodeDecodeError):
            key = Path(settings.admin_api_key_file).read_text(encoding="utf-8").strip()
    return key or None


def _check_admin_key(x_admin_key: str | None, expected_key: str | None = None) -> None:
    """
    Verify an admin API key against the expected value.

    This is the internal, non-FastAPI implementation. `expected_key` is a test
    seam kept off the request-facing dependency so it cannot be bound as a query
    parameter (an attacker-controlled `expected_key` was a full auth bypass).

    Parameters
    ----------
    x_admin_key : str | None
        API key supplied by the client (X-Admin-Key header).
    expected_key : str | None
        Expected value; when None it is resolved from the settings and the key file.

    Raises
    ------
    UnauthorizedError
        ``unauthorized`` (401) when the server has no key or the key is missing or
        wrong.
    """
    if expected_key is None:
        expected_key = _resolve_expected_key()
    if not expected_key:
        raise UnauthorizedError(
            "admin_key_not_configured", reason="admin_key_not_configured"
        )

    if not x_admin_key:
        raise UnauthorizedError("admin_key_missing", reason="admin_key_missing")

    supplied = x_admin_key.encode("utf-8")
    expected = expected_key.encode("utf-8")
    if not secrets.compare_digest(supplied, expected):
        raise UnauthorizedError("admin_key_invalid", reason="admin_key_invalid")


def verify_admin_key(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
) -> None:
    """FastAPI dependency: verify the X-Admin-Key header against the configured key."""
    _check_admin_key(x_admin_key)
