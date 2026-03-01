"""
Admin API key authentication dependency.

Verifies the X-Admin-Key header against the configured admin_api_key.
If no key is configured (empty string), authentication is disabled.
"""

from fastapi import Header, HTTPException

from core.config import get_settings


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
        expected_key = get_settings().admin_api_key

    # If no key is configured, auth is disabled
    if not expected_key:
        return

    if not x_admin_key:
        raise HTTPException(status_code=401, detail="Missing admin API key")

    if x_admin_key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid admin API key")
