"""
Tests for src/utils/duration.py

Covers parsing and formatting of duration strings used throughout
the bot for mutes, bans, and other time-based operations.
"""

import pytest
from src.utils.duration import (
    parse_duration,
    format_duration,
    format_duration_short,
    format_duration_from_minutes,
    SECONDS_PER_MINUTE,
    SECONDS_PER_HOUR,
    SECONDS_PER_DAY,
    SECONDS_PER_WEEK,
    SECONDS_PER_YEAR,
)


# =============================================================================
# parse_duration() Tests
# =============================================================================

class TestParseDuration:
    """Tests for parse_duration function."""

    # -------------------------------------------------------------------------
    # Basic single-unit parsing
    # -------------------------------------------------------------------------

    def test_parse_seconds(self):
        assert parse_duration("30s") == 30
        assert parse_duration("1s") == 1
        assert parse_duration("60s") == 60

    def test_parse_minutes(self):
        assert parse_duration("1m") == 60
        assert parse_duration("30m") == 1800
        assert parse_duration("60m") == 3600

    def test_parse_hours(self):
        assert parse_duration("1h") == 3600
        assert parse_duration("6h") == 21600
        assert parse_duration("24h") == 86400

    def test_parse_days(self):
        assert parse_duration("1d") == 86400
        assert parse_duration("7d") == 604800
        assert parse_duration("30d") == 2592000

    def test_parse_weeks(self):
        assert parse_duration("1w") == 604800
        assert parse_duration("2w") == 1209600
        assert parse_duration("4w") == 2419200

    def test_parse_years(self):
        assert parse_duration("1y") == 31536000
        assert parse_duration("2y") == 63072000

    # -------------------------------------------------------------------------
    # Plain numbers (default to minutes)
    # -------------------------------------------------------------------------

    def test_parse_plain_number_defaults_to_minutes(self):
        assert parse_duration("30") == 1800  # 30 minutes
        assert parse_duration("60") == 3600  # 60 minutes
        assert parse_duration("1") == 60     # 1 minute

    # -------------------------------------------------------------------------
    # Combined formats
    # -------------------------------------------------------------------------

    def test_parse_combined_hours_minutes(self):
        assert parse_duration("1h30m") == 5400
        assert parse_duration("2h15m") == 8100

    def test_parse_combined_days_hours(self):
        assert parse_duration("1d12h") == 129600
        assert parse_duration("2d6h") == 194400

    def test_parse_combined_days_hours_minutes(self):
        assert parse_duration("1d12h30m") == 131400

    def test_parse_combined_weeks_days(self):
        assert parse_duration("2w3d") == 1468800

    def test_parse_combined_all_units(self):
        # 1y2w3d4h5m6s
        expected = (
            1 * SECONDS_PER_YEAR +
            2 * SECONDS_PER_WEEK +
            3 * SECONDS_PER_DAY +
            4 * SECONDS_PER_HOUR +
            5 * SECONDS_PER_MINUTE +
            6
        )
        assert parse_duration("1y2w3d4h5m6s") == expected

    # -------------------------------------------------------------------------
    # Permanent durations
    # -------------------------------------------------------------------------

    def test_parse_permanent(self):
        assert parse_duration("permanent") is None

    def test_parse_perm(self):
        assert parse_duration("perm") is None

    def test_parse_forever(self):
        assert parse_duration("forever") is None

    def test_parse_indefinite(self):
        assert parse_duration("indefinite") is None

    # -------------------------------------------------------------------------
    # Case insensitivity
    # -------------------------------------------------------------------------

    def test_parse_uppercase(self):
        assert parse_duration("1H") == 3600
        assert parse_duration("1D") == 86400
        assert parse_duration("PERMANENT") is None

    def test_parse_mixed_case(self):
        assert parse_duration("1d12H30M") == 131400
        assert parse_duration("Perm") is None
        assert parse_duration("FOREVER") is None

    # -------------------------------------------------------------------------
    # Whitespace handling
    # -------------------------------------------------------------------------

    def test_parse_with_leading_whitespace(self):
        assert parse_duration("  1h") == 3600

    def test_parse_with_trailing_whitespace(self):
        assert parse_duration("1h  ") == 3600

    def test_parse_with_surrounding_whitespace(self):
        assert parse_duration("  1h  ") == 3600

    # -------------------------------------------------------------------------
    # Edge cases and invalid input
    # -------------------------------------------------------------------------

    def test_parse_empty_string(self):
        assert parse_duration("") is None

    def test_parse_zero(self):
        assert parse_duration("0m") is None
        assert parse_duration("0h") is None
        assert parse_duration("0") == 0  # Plain "0" → 0 minutes → 0 seconds

    def test_parse_invalid_format(self):
        assert parse_duration("abc") is None
        assert parse_duration("1x") is None  # Invalid unit
        assert parse_duration("one hour") is None

    def test_parse_negative_not_supported(self):
        # Negative durations should not parse
        assert parse_duration("-1h") is None


# =============================================================================
# format_duration() Tests
# =============================================================================

class TestFormatDuration:
    """Tests for format_duration function."""

    # -------------------------------------------------------------------------
    # Permanent and zero
    # -------------------------------------------------------------------------

    def test_format_none_is_permanent(self):
        assert format_duration(None) == "Permanent"

    def test_format_zero(self):
        assert format_duration(0) == "0m"

    def test_format_zero_with_show_seconds(self):
        assert format_duration(0, show_seconds=True) == "0s"

    def test_format_negative(self):
        assert format_duration(-100) == "0m"

    # -------------------------------------------------------------------------
    # Less than a minute
    # -------------------------------------------------------------------------

    def test_format_under_minute_default(self):
        assert format_duration(30) == "< 1m"
        assert format_duration(59) == "< 1m"

    def test_format_under_minute_with_seconds(self):
        assert format_duration(30, show_seconds=True) == "30s"
        assert format_duration(59, show_seconds=True) == "59s"

    # -------------------------------------------------------------------------
    # Basic formatting
    # -------------------------------------------------------------------------

    def test_format_minutes(self):
        assert format_duration(60) == "1m"
        assert format_duration(300) == "5m"
        assert format_duration(1800) == "30m"

    def test_format_hours(self):
        assert format_duration(3600) == "1h"
        assert format_duration(7200) == "2h"

    def test_format_hours_and_minutes(self):
        assert format_duration(3660) == "1h 1m"
        assert format_duration(5400) == "1h 30m"

    def test_format_days(self):
        assert format_duration(86400) == "1d"
        assert format_duration(172800) == "2d"

    def test_format_days_hours_minutes(self):
        assert format_duration(90060) == "1d 1h 1m"

    def test_format_weeks(self):
        assert format_duration(604800) == "1w"
        assert format_duration(1209600) == "2w"

    def test_format_years(self):
        assert format_duration(31536000) == "1y"

    # -------------------------------------------------------------------------
    # max_units parameter
    # -------------------------------------------------------------------------

    def test_format_max_units_1(self):
        # 1d 1h 1m 1s = 90061 seconds, should only show 1d
        assert format_duration(90061, max_units=1) == "1d"

    def test_format_max_units_2(self):
        # 1d 1h 1m 1s = 90061 seconds, should show 1d 1h
        assert format_duration(90061, max_units=2) == "1d 1h"

    def test_format_max_units_3_default(self):
        # 1d 1h 1m 1s = 90061 seconds, should show 1d 1h 1m
        assert format_duration(90061, max_units=3) == "1d 1h 1m"

    def test_format_max_units_4(self):
        # 1d 1h 1m 1s with show_seconds
        assert format_duration(90061, max_units=4, show_seconds=True) == "1d 1h 1m 1s"

    # -------------------------------------------------------------------------
    # show_seconds parameter
    # -------------------------------------------------------------------------

    def test_format_with_seconds(self):
        assert format_duration(3661, show_seconds=True) == "1h 1m 1s"

    def test_format_exact_minute_no_trailing_seconds(self):
        # 1h exactly, no seconds to show
        assert format_duration(3600, show_seconds=True) == "1h"


# =============================================================================
# format_duration_short() Tests
# =============================================================================

class TestFormatDurationShort:
    """Tests for format_duration_short function."""

    def test_short_is_max_2_units(self):
        # 1d 1h 1m should become 1d 1h
        assert format_duration_short(90061) == "1d 1h"

    def test_short_permanent(self):
        assert format_duration_short(None) == "Permanent"

    def test_short_single_unit(self):
        assert format_duration_short(3600) == "1h"
        assert format_duration_short(86400) == "1d"


# =============================================================================
# format_duration_from_minutes() Tests
# =============================================================================

class TestFormatDurationFromMinutes:
    """Tests for format_duration_from_minutes function."""

    def test_from_minutes_basic(self):
        assert format_duration_from_minutes(30) == "30m"
        assert format_duration_from_minutes(60) == "1h"
        assert format_duration_from_minutes(90) == "1h 30m"

    def test_from_minutes_hours(self):
        assert format_duration_from_minutes(120) == "2h"
        assert format_duration_from_minutes(150) == "2h 30m"

    def test_from_minutes_days(self):
        assert format_duration_from_minutes(1440) == "1d"  # 24 * 60
        assert format_duration_from_minutes(1500) == "1d 1h"  # 25 * 60

    def test_from_minutes_zero(self):
        assert format_duration_from_minutes(0) == "0m"


# =============================================================================
# Round-trip Tests (parse then format)
# =============================================================================

class TestRoundTrip:
    """Tests that verify parse and format are consistent."""

    def test_roundtrip_1h(self):
        seconds = parse_duration("1h")
        assert "1h" in format_duration(seconds)

    def test_roundtrip_1d(self):
        seconds = parse_duration("1d")
        assert "1d" in format_duration(seconds)

    def test_roundtrip_1d12h(self):
        seconds = parse_duration("1d12h")
        formatted = format_duration(seconds)
        assert "1d" in formatted
        assert "12h" in formatted

    def test_roundtrip_permanent(self):
        seconds = parse_duration("permanent")
        assert format_duration(seconds) == "Permanent"
