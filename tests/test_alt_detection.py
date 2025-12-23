"""
Azab Discord Bot - Alt Detection Tests
=======================================

Tests for the alt detection service.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

# Import after conftest mocks are set up
from src.services.alt_detection import (
    AltDetectionService,
    SignalWeights,
    CONFIDENCE_THRESHOLDS,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_config():
    """Create a mock config."""
    config = MagicMock()
    config.case_log_forum_id = 123456789
    config.developer_id = 111222333
    return config


@pytest.fixture
def mock_db():
    """Create a mock database."""
    db = MagicMock()
    db.get_user_join_info = MagicMock(return_value=None)
    db.get_member_activity = MagicMock(return_value=None)
    db.get_all_nicknames = MagicMock(return_value=[])
    db.get_user_mute_history = MagicMock(return_value=[])
    db.save_alt_link = MagicMock()
    return db


@pytest.fixture
def mock_bot(mock_config, mock_db):
    """Create a mock bot."""
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=None)
    bot.fetch_channel = AsyncMock(return_value=MagicMock())
    return bot


@pytest.fixture
def alt_service(mock_bot, mock_config, mock_db):
    """Create an AltDetectionService instance."""
    with patch('src.services.alt_detection.get_config', return_value=mock_config):
        with patch('src.services.alt_detection.get_db', return_value=mock_db):
            service = AltDetectionService(mock_bot)
            service.db = mock_db
            return service


@pytest.fixture
def create_mock_member():
    """Factory for creating mock members with specific attributes."""
    def _create(
        user_id: int = 123456789,
        name: str = "testuser",
        display_name: str = "Test User",
        created_at: datetime = None,
        joined_at: datetime = None,
        avatar_key: str = None,
        activities: list = None,
        bot: bool = False,
    ):
        member = MagicMock()
        member.id = user_id
        member.name = name
        member.display_name = display_name
        member.created_at = created_at or datetime(2020, 1, 1, 12, 0, 0)
        member.joined_at = joined_at or datetime(2023, 1, 1, 12, 0, 0)
        member.bot = bot

        if avatar_key:
            member.avatar = MagicMock()
            member.avatar.key = avatar_key
        else:
            member.avatar = None

        member.activities = activities or []

        return member
    return _create


# =============================================================================
# Signal Weight Tests
# =============================================================================

class TestSignalWeights:
    """Test signal weight constants are properly defined."""

    def test_account_age_weights(self):
        """Test account age signal weights."""
        assert SignalWeights.ACCOUNT_AGE_UNDER_7_DAYS == 30
        assert SignalWeights.ACCOUNT_AGE_UNDER_30_DAYS == 15
        assert SignalWeights.ACCOUNT_AGE_UNDER_90_DAYS == 5

    def test_username_similarity_weights(self):
        """Test username similarity signal weights."""
        assert SignalWeights.USERNAME_EXACT_MATCH == 50
        assert SignalWeights.USERNAME_HIGH_SIMILARITY == 35
        assert SignalWeights.USERNAME_MEDIUM_SIMILARITY == 20

    def test_join_timing_weights(self):
        """Test join timing signal weights."""
        assert SignalWeights.JOINED_WITHIN_1_HOUR == 40
        assert SignalWeights.JOINED_WITHIN_6_HOURS == 25
        assert SignalWeights.JOINED_WITHIN_24_HOURS == 15
        assert SignalWeights.JOINED_WITHIN_7_DAYS == 5

    def test_other_signal_weights(self):
        """Test other signal weights."""
        assert SignalWeights.SAME_INVITER == 35
        assert SignalWeights.SAME_AVATAR == 45
        assert SignalWeights.NICKNAME_OVERLAP == 25
        assert SignalWeights.JOIN_COUNT_3_PLUS == 20
        assert SignalWeights.JOIN_COUNT_5_PLUS == 35

    def test_new_signal_weights(self):
        """Test newly added signal weights."""
        assert SignalWeights.CREATED_WITHIN_1_HOUR == 45
        assert SignalWeights.CREATED_WITHIN_24_HOURS == 30
        assert SignalWeights.CREATED_WITHIN_7_DAYS == 15
        assert SignalWeights.SAME_BIO == 40
        assert SignalWeights.SIMILAR_BIO == 20
        assert SignalWeights.BOTH_PREVIOUSLY_PUNISHED == 25
        assert SignalWeights.BOTH_PUNISHED_SAME_DAY == 40


class TestConfidenceThresholds:
    """Test confidence threshold constants."""

    def test_thresholds(self):
        """Test confidence thresholds are properly defined."""
        assert CONFIDENCE_THRESHOLDS['HIGH'] == 80
        assert CONFIDENCE_THRESHOLDS['MEDIUM'] == 50
        assert CONFIDENCE_THRESHOLDS['LOW'] == 30


# =============================================================================
# Account Age Signal Tests
# =============================================================================

class TestAccountAgeSignal:
    """Test account age detection signal."""

    def test_account_under_7_days(self, alt_service, create_mock_member):
        """Test detection of very new accounts."""
        member = create_mock_member(
            created_at=datetime.now() - timedelta(days=3)
        )
        score, signal = alt_service._check_account_age(member)
        assert score == SignalWeights.ACCOUNT_AGE_UNDER_7_DAYS
        assert "3 days old" in signal

    def test_account_under_30_days(self, alt_service, create_mock_member):
        """Test detection of new accounts."""
        member = create_mock_member(
            created_at=datetime.now() - timedelta(days=15)
        )
        score, signal = alt_service._check_account_age(member)
        assert score == SignalWeights.ACCOUNT_AGE_UNDER_30_DAYS
        assert "15 days old" in signal

    def test_account_under_90_days(self, alt_service, create_mock_member):
        """Test detection of relatively new accounts."""
        member = create_mock_member(
            created_at=datetime.now() - timedelta(days=60)
        )
        score, signal = alt_service._check_account_age(member)
        assert score == SignalWeights.ACCOUNT_AGE_UNDER_90_DAYS
        assert "60 days old" in signal

    def test_account_old_enough(self, alt_service, create_mock_member):
        """Test old accounts don't trigger signal."""
        member = create_mock_member(
            created_at=datetime.now() - timedelta(days=365)
        )
        score, signal = alt_service._check_account_age(member)
        assert score == 0
        assert signal == ""


# =============================================================================
# Username Similarity Signal Tests
# =============================================================================

class TestUsernameSimilaritySignal:
    """Test username similarity detection signal."""

    def test_exact_match(self, alt_service):
        """Test exact username match."""
        banned_data = {'username': 'testuser', 'display_name': 'test user'}
        candidate_data = {'username': 'testuser', 'display_name': 'other name'}

        score, signal = alt_service._check_username_similarity(banned_data, candidate_data)
        assert score == SignalWeights.USERNAME_EXACT_MATCH
        assert "Exact name match" in signal

    def test_high_similarity(self, alt_service):
        """Test high username similarity (80%+)."""
        banned_data = {'username': 'testuser123', 'display_name': 'test'}
        candidate_data = {'username': 'testuser124', 'display_name': 'other'}

        score, signal = alt_service._check_username_similarity(banned_data, candidate_data)
        assert score == SignalWeights.USERNAME_HIGH_SIMILARITY
        assert "% name similarity" in signal

    def test_medium_similarity(self, alt_service):
        """Test medium username similarity (60-80%)."""
        banned_data = {'username': 'abcdefgh', 'display_name': 'abc'}
        candidate_data = {'username': 'abcxyz', 'display_name': 'xyz'}

        score, signal = alt_service._check_username_similarity(banned_data, candidate_data)
        assert score == SignalWeights.USERNAME_MEDIUM_SIMILARITY
        assert "% name similarity" in signal

    def test_no_similarity(self, alt_service):
        """Test completely different usernames."""
        banned_data = {'username': 'alice', 'display_name': 'alice'}
        candidate_data = {'username': 'bob', 'display_name': 'bob'}

        score, signal = alt_service._check_username_similarity(banned_data, candidate_data)
        assert score == 0
        assert signal == ""


# =============================================================================
# Join Timing Signal Tests
# =============================================================================

class TestJoinTimingSignal:
    """Test join timing detection signal."""

    def test_joined_within_1_hour(self, alt_service):
        """Test accounts that joined within 1 hour."""
        base_time = datetime(2023, 6, 15, 12, 0, 0)
        banned_data = {'joined_at': base_time}
        candidate_data = {'joined_at': base_time + timedelta(minutes=30)}

        score, signal = alt_service._check_join_timing(banned_data, candidate_data)
        assert score == SignalWeights.JOINED_WITHIN_1_HOUR
        assert "within 1 hour" in signal

    def test_joined_within_6_hours(self, alt_service):
        """Test accounts that joined within 6 hours."""
        base_time = datetime(2023, 6, 15, 12, 0, 0)
        banned_data = {'joined_at': base_time}
        candidate_data = {'joined_at': base_time + timedelta(hours=3)}

        score, signal = alt_service._check_join_timing(banned_data, candidate_data)
        assert score == SignalWeights.JOINED_WITHIN_6_HOURS
        assert "within 6 hours" in signal

    def test_joined_within_24_hours(self, alt_service):
        """Test accounts that joined within 24 hours."""
        base_time = datetime(2023, 6, 15, 12, 0, 0)
        banned_data = {'joined_at': base_time}
        candidate_data = {'joined_at': base_time + timedelta(hours=12)}

        score, signal = alt_service._check_join_timing(banned_data, candidate_data)
        assert score == SignalWeights.JOINED_WITHIN_24_HOURS
        assert "within 24 hours" in signal

    def test_joined_far_apart(self, alt_service):
        """Test accounts that joined far apart."""
        base_time = datetime(2023, 6, 15, 12, 0, 0)
        banned_data = {'joined_at': base_time}
        candidate_data = {'joined_at': base_time + timedelta(days=30)}

        score, signal = alt_service._check_join_timing(banned_data, candidate_data)
        assert score == 0
        assert signal == ""


# =============================================================================
# Creation Proximity Signal Tests
# =============================================================================

class TestCreationProximitySignal:
    """Test account creation proximity detection signal."""

    def test_created_within_1_hour(self, alt_service):
        """Test accounts created within 1 hour."""
        base_time = datetime(2023, 1, 1, 12, 0, 0)
        banned_data = {'created_at': base_time}
        candidate_data = {'created_at': base_time + timedelta(minutes=30)}

        score, signal = alt_service._check_creation_proximity(banned_data, candidate_data)
        assert score == SignalWeights.CREATED_WITHIN_1_HOUR
        assert "within 1 hour" in signal

    def test_created_within_24_hours(self, alt_service):
        """Test accounts created within 24 hours."""
        base_time = datetime(2023, 1, 1, 12, 0, 0)
        banned_data = {'created_at': base_time}
        candidate_data = {'created_at': base_time + timedelta(hours=12)}

        score, signal = alt_service._check_creation_proximity(banned_data, candidate_data)
        assert score == SignalWeights.CREATED_WITHIN_24_HOURS
        assert "within 24 hours" in signal

    def test_created_far_apart(self, alt_service):
        """Test accounts created far apart."""
        banned_data = {'created_at': datetime(2020, 1, 1)}
        candidate_data = {'created_at': datetime(2023, 1, 1)}

        score, signal = alt_service._check_creation_proximity(banned_data, candidate_data)
        assert score == 0
        assert signal == ""


# =============================================================================
# Bio Similarity Signal Tests
# =============================================================================

class TestBioSimilaritySignal:
    """Test bio/status similarity detection signal."""

    def test_identical_bio(self, alt_service):
        """Test identical bio/status."""
        banned_data = {'bio': 'hello world'}
        candidate_data = {'bio': 'hello world'}

        score, signal = alt_service._check_bio_similarity(banned_data, candidate_data)
        assert score == SignalWeights.SAME_BIO
        assert "Identical status" in signal

    def test_similar_bio(self, alt_service):
        """Test similar bio/status (70%+)."""
        banned_data = {'bio': 'i love discord'}
        candidate_data = {'bio': 'i love discord servers'}

        score, signal = alt_service._check_bio_similarity(banned_data, candidate_data)
        assert score == SignalWeights.SIMILAR_BIO
        assert "% status similarity" in signal

    def test_different_bio(self, alt_service):
        """Test completely different bio."""
        banned_data = {'bio': 'hello'}
        candidate_data = {'bio': 'goodbye'}

        score, signal = alt_service._check_bio_similarity(banned_data, candidate_data)
        assert score == 0
        assert signal == ""

    def test_no_bio(self, alt_service):
        """Test when one or both have no bio."""
        banned_data = {'bio': None}
        candidate_data = {'bio': 'hello'}

        score, signal = alt_service._check_bio_similarity(banned_data, candidate_data)
        assert score == 0
        assert signal == ""


# =============================================================================
# Punishment Correlation Signal Tests
# =============================================================================

class TestPunishmentCorrelationSignal:
    """Test punishment history correlation detection signal."""

    def test_punished_same_day(self, alt_service):
        """Test both punished within 24 hours of each other."""
        base_time = 1700000000.0  # Unix timestamp
        banned_data = {'punishment_dates': [base_time]}
        candidate_data = {'punishment_dates': [base_time + 3600]}  # 1 hour later

        score, signal = alt_service._check_punishment_correlation(banned_data, candidate_data)
        assert score == SignalWeights.BOTH_PUNISHED_SAME_DAY
        assert "within 24 hours" in signal

    def test_both_punished_different_times(self, alt_service):
        """Test both have punishment history but different times."""
        banned_data = {'punishment_dates': [1700000000.0]}
        candidate_data = {'punishment_dates': [1700500000.0]}  # Days later

        score, signal = alt_service._check_punishment_correlation(banned_data, candidate_data)
        assert score == SignalWeights.BOTH_PREVIOUSLY_PUNISHED
        assert "previous punishments" in signal

    def test_no_punishment_history(self, alt_service):
        """Test when no punishment history."""
        banned_data = {'punishment_dates': []}
        candidate_data = {'punishment_dates': []}

        score, signal = alt_service._check_punishment_correlation(banned_data, candidate_data)
        assert score == 0
        assert signal == ""


# =============================================================================
# Service Enable/Disable Tests
# =============================================================================

class TestServiceEnabled:
    """Test service enable/disable logic."""

    def test_enabled_with_forum_id(self, mock_bot, mock_db):
        """Test service is enabled when forum ID is configured."""
        config = MagicMock()
        config.case_log_forum_id = 123456789

        with patch('src.services.alt_detection.get_config', return_value=config):
            with patch('src.services.alt_detection.get_db', return_value=mock_db):
                service = AltDetectionService(mock_bot)
                assert service.enabled is True

    def test_disabled_without_forum_id(self, mock_bot, mock_db):
        """Test service is disabled when forum ID is not configured."""
        config = MagicMock()
        config.case_log_forum_id = None

        with patch('src.services.alt_detection.get_config', return_value=config):
            with patch('src.services.alt_detection.get_db', return_value=mock_db):
                service = AltDetectionService(mock_bot)
                assert service.enabled is False


# =============================================================================
# Confidence Level Tests
# =============================================================================

class TestConfidenceLevels:
    """Test confidence level determination."""

    def test_high_confidence(self):
        """Test HIGH confidence for 80+ points."""
        assert 95 >= CONFIDENCE_THRESHOLDS['HIGH']
        assert 80 >= CONFIDENCE_THRESHOLDS['HIGH']

    def test_medium_confidence(self):
        """Test MEDIUM confidence for 50-79 points."""
        assert 60 >= CONFIDENCE_THRESHOLDS['MEDIUM']
        assert 60 < CONFIDENCE_THRESHOLDS['HIGH']

    def test_low_confidence(self):
        """Test LOW confidence for 30-49 points."""
        assert 40 >= CONFIDENCE_THRESHOLDS['LOW']
        assert 40 < CONFIDENCE_THRESHOLDS['MEDIUM']

    def test_below_threshold(self):
        """Test scores below LOW threshold are not flagged."""
        assert 20 < CONFIDENCE_THRESHOLDS['LOW']
