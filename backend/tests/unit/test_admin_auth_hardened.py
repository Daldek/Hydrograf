"""Tests for hardened admin auth — key must be explicitly configured."""

from api.dependencies.admin_auth import _get_or_generate_admin_key


def test_configured_key_returned():
    """Configured key is returned as-is."""
    assert _get_or_generate_admin_key("my-secret") == "my-secret"


def test_empty_key_generates_fallback():
    """Empty key generates a UUID fallback (for dev convenience)."""
    import api.dependencies.admin_auth as mod
    mod._generated_key = None  # Reset module state
    result = _get_or_generate_admin_key("")
    assert len(result) == 36  # UUID format
    mod._generated_key = None  # Cleanup


def test_generated_key_not_logged_in_full(caplog):
    """Generated key must NOT appear in full in log messages."""
    import api.dependencies.admin_auth as mod
    mod._generated_key = None
    with caplog.at_level("WARNING"):
        key = _get_or_generate_admin_key("")
    # Key should NOT appear in full in any log message
    for record in caplog.records:
        assert key not in record.getMessage(), "Full admin key leaked in logs!"
    mod._generated_key = None
