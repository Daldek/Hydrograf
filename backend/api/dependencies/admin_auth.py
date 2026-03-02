"""
Admin API key authentication dependency.

Verifies the X-Admin-Key header against the configured admin_api_key.
If no key is configured, a random UUID is generated and logged as WARNING.
"""

import logging
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


def verify_admin_key(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    *,
    expected_key: str | None = None,
) -> None:
    """
    Verify admin API key from request header.

    Parameters
    ----------
    x_admin_key : str | None
        API key from X-Admin-Key header
    expected_key : str | None
        Override for testing; if None, loads from settings

    Raises
    ------
    HTTPException
        401 if key is missing, 403 if key is wrong
    """
    if expected_key is None:
        settings = get_settings()
        expected_key = settings.admin_api_key

        if not expected_key and settings.admin_api_key_file:
            try:
                expected_key = Path(settings.admin_api_key_file).read_text().strip()
            except (OSError, IOError):
                pass

        expected_key = _get_or_generate_admin_key(expected_key or "")

    if not x_admin_key:
        raise HTTPException(status_code=401, detail="Missing admin API key")

    if x_admin_key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid admin API key")
