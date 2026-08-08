"""
Admin API key authentication dependency.

Verifies the X-Admin-Key header against the configured admin_api_key.
If no key is configured, a random UUID is generated and logged as WARNING.
"""

import contextlib
import logging
import secrets
import uuid
from pathlib import Path

from fastapi import Header, HTTPException

from core.config import get_settings

logger = logging.getLogger(__name__)

# Module-level generated key (stable for process lifetime)
_generated_key: str | None = None


def _get_or_generate_admin_key(configured_key: str) -> str:
    """Return configured key, or generate and log a random one."""
    global _generated_key
    if configured_key:
        return configured_key
    if _generated_key is None:
        _generated_key = str(uuid.uuid4())
        logger.warning(
            "ADMIN_API_KEY not configured — generated random key "
            "(set ADMIN_API_KEY or ADMIN_API_KEY_FILE env var for persistent key)"
        )
    return _generated_key


def _resolve_expected_key() -> str:
    """Load the configured admin key from settings, key file, or generate one."""
    settings = get_settings()
    expected_key = settings.admin_api_key

    if not expected_key and settings.admin_api_key_file:
        with contextlib.suppress(OSError):
            expected_key = Path(settings.admin_api_key_file).read_text().strip()

    return _get_or_generate_admin_key(expected_key or "")


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
        Expected value; when None it is resolved from settings/key file.

    Raises
    ------
    HTTPException
        401 if key is missing, 403 if key is wrong.
    """
    if expected_key is None:
        expected_key = _resolve_expected_key()

    if not x_admin_key:
        raise HTTPException(status_code=401, detail="Missing admin API key")

    supplied = x_admin_key.encode("utf-8")
    expected = expected_key.encode("utf-8")
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Invalid admin API key")


def verify_admin_key(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
) -> None:
    """FastAPI dependency: verify the X-Admin-Key header against the configured key."""
    _check_admin_key(x_admin_key)
