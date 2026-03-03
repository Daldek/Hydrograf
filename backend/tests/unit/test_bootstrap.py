"""Tests for scripts/bootstrap.py: parse_bbox and StepTracker."""

import pytest

from scripts.bootstrap import StepTracker, parse_bbox


class TestParseBbox:
    """Tests for parse_bbox()."""

    def test_valid_bbox(self):
        """Valid bbox string returns a tuple of 4 floats."""
        result = parse_bbox("16.9,52.3,17.1,52.5")
        assert len(result) == 4
        assert all(isinstance(v, float) for v in result)
        assert result == (16.9, 52.3, 17.1, 52.5)

    def test_with_spaces(self):
        """Bbox string with spaces around values is handled."""
        result = parse_bbox("16.9 , 52.3 , 17.1 , 52.5")
        assert result == (16.9, 52.3, 17.1, 52.5)

    def test_integer_values(self):
        """Integer values in bbox string are converted to float."""
        result = parse_bbox("17,52,18,53")
        assert result == (17.0, 52.0, 18.0, 53.0)
        assert all(isinstance(v, float) for v in result)

    def test_insufficient_values_raises(self):
        """Fewer than 4 values raises ValueError."""
        with pytest.raises(ValueError, match="4 wartosci"):
            parse_bbox("16.9,52.3,17.1")

    def test_too_many_values_raises(self):
        """More than 4 values raises ValueError."""
        with pytest.raises(ValueError, match="4 wartosci"):
            parse_bbox("16.9,52.3,17.1,52.5,99.0")

    def test_non_numeric_raises(self):
        """Non-numeric values raise ValueError."""
        with pytest.raises(ValueError):
            parse_bbox("abc,52.3,17.1,52.5")

    def test_empty_string_raises(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError):
            parse_bbox("")

    def test_negative_values(self):
        """Negative coordinate values are accepted."""
        result = parse_bbox("-10.5,48.0,-9.5,49.0")
        assert result == (-10.5, 48.0, -9.5, 49.0)


class TestStepTracker:
    """Tests for StepTracker class."""

    def test_init_sets_total(self):
        """StepTracker initializes with correct total."""
        tracker = StepTracker(total=5, skipped=set())
        assert tracker.total == 5

    def test_init_pending_statuses(self):
        """All statuses start as None (pending) by default."""
        tracker = StepTracker(total=3, skipped=set())
        assert tracker.statuses == [None, None, None]

    def test_init_skipped_steps(self):
        """Skipped steps are marked as 'skip' at init."""
        tracker = StepTracker(total=5, skipped={2, 4})
        assert tracker.statuses[0] is None
        assert tracker.statuses[1] == "skip"
        assert tracker.statuses[2] is None
        assert tracker.statuses[3] == "skip"
        assert tracker.statuses[4] is None

    def test_start_sets_active(self):
        """start() sets status to 'active' and returns a timestamp."""
        tracker = StepTracker(total=3, skipped=set())
        t0 = tracker.start(1)
        assert tracker.statuses[0] == "active"
        assert isinstance(t0, float)

    def test_done_sets_done_and_records_timing(self):
        """done() sets status to 'done' and records elapsed time."""
        tracker = StepTracker(total=3, skipped=set())
        t0 = tracker.start(1)
        tracker.done(1, t0, detail="completed")
        assert tracker.statuses[0] == "done"
        assert tracker.timings[0] >= 0.0
        assert tracker.details[0] == "completed"

    def test_fail_records_error(self):
        """fail() sets status to 'fail' and records error in errors list."""
        tracker = StepTracker(total=3, skipped=set())
        t0 = tracker.start(2)
        tracker.fail(2, t0, error="connection refused")
        assert tracker.statuses[1] == "fail"
        assert tracker.details[1] == "connection refused"
        assert len(tracker.errors) == 1
        assert "connection refused" in tracker.errors[0]

    def test_is_skipped(self):
        """is_skipped() returns True for skipped steps, False otherwise."""
        tracker = StepTracker(total=5, skipped={3})
        assert tracker.is_skipped(3) is True
        assert tracker.is_skipped(1) is False
        assert tracker.is_skipped(5) is False

    def test_multiple_steps_workflow(self):
        """Full workflow: start -> done for multiple steps."""
        tracker = StepTracker(total=3, skipped=set())

        t0 = tracker.start(1)
        tracker.done(1, t0, detail="step 1 OK")

        t1 = tracker.start(2)
        tracker.done(2, t1, detail="step 2 OK")

        t2 = tracker.start(3)
        tracker.done(3, t2, detail="step 3 OK")

        assert all(s == "done" for s in tracker.statuses)
        assert len(tracker.errors) == 0

    def test_mixed_done_fail_skip(self):
        """Mix of done, fail, and skip statuses tracked correctly."""
        tracker = StepTracker(total=4, skipped={2})

        t0 = tracker.start(1)
        tracker.done(1, t0, detail="OK")

        # Step 2 is skipped
        assert tracker.is_skipped(2)

        t2 = tracker.start(3)
        tracker.fail(3, t2, error="timeout")

        t3 = tracker.start(4)
        tracker.done(4, t3, detail="OK")

        assert tracker.statuses[0] == "done"
        assert tracker.statuses[1] == "skip"
        assert tracker.statuses[2] == "fail"
        assert tracker.statuses[3] == "done"
        assert len(tracker.errors) == 1

    def test_errors_list_empty_initially(self):
        """Errors list starts empty."""
        tracker = StepTracker(total=3, skipped=set())
        assert tracker.errors == []

    def test_timings_initialized_to_zero(self):
        """All timings start at 0.0."""
        tracker = StepTracker(total=3, skipped=set())
        assert tracker.timings == [0.0, 0.0, 0.0]

    def test_details_initialized_empty(self):
        """All details start as empty strings."""
        tracker = StepTracker(total=3, skipped=set())
        assert tracker.details == ["", "", ""]
