"""Tests for feedback Pydantic schemas."""

import pytest
from pydantic import ValidationError

from models.schemas import FeedbackRequest


class TestFeedbackRequest:
    def test_minimal_valid(self):
        req = FeedbackRequest(message="Mapa nie laduje warstwy")
        assert req.contact is None
        assert req.diagnostics is None

    def test_full_valid(self):
        req = FeedbackRequest(
            message="x",
            contact="jan@example.com",
            page_url="http://localhost:8080/",
            diagnostics={"events": [], "env": {"userAgent": "UA"}},
        )
        assert req.diagnostics["env"]["userAgent"] == "UA"

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(message="")

    def test_message_too_long_rejected(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(message="x" * 5001)

    def test_contact_too_long_rejected(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(message="x", contact="a" * 201)

    def test_diagnostics_over_100kb_rejected(self):
        big = {"events": ["e" * 100] * 1100}
        with pytest.raises(ValidationError):
            FeedbackRequest(message="x", diagnostics=big)

    def test_diagnostics_under_100kb_accepted(self):
        ok = {"events": ["e" * 100] * 100}
        req = FeedbackRequest(message="x", diagnostics=ok)
        assert req.diagnostics is not None
