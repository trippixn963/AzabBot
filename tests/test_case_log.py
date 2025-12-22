"""
Azab Discord Bot - Case Log Service Tests
==========================================

Tests for the case log service logic.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch


class TestCaseLogServiceInit:
    """Tests for CaseLogService initialization."""

    def test_service_disabled_without_forum_id(self, test_db, mock_bot, monkeypatch):
        """Test service is disabled when forum ID is not configured."""
        from src.core import config as config_module

        # Create a config mock without case_log_forum_id
        mock_config = MagicMock()
        mock_config.case_log_forum_id = None

        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        service = CaseLogService(mock_bot)

        assert service.enabled is False

    def test_service_enabled_with_forum_id(self, test_db, mock_bot, monkeypatch):
        """Test service is enabled when forum ID is configured."""
        from src.core import config as config_module

        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789

        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        service = CaseLogService(mock_bot)

        assert service.enabled is True


class TestCaseIdGeneration:
    """Tests for case ID generation."""

    def test_case_id_format(self, test_db):
        """Test case IDs are 4 uppercase alphanumeric characters."""
        for _ in range(50):
            case_id = test_db.get_next_case_id()
            assert len(case_id) == 4
            assert case_id.isalnum()
            # All uppercase letters and digits
            for char in case_id:
                assert char.isupper() or char.isdigit()

    def test_case_id_uniqueness(self, test_db):
        """Test case IDs don't collide."""
        generated = set()
        for i in range(100):
            case_id = test_db.get_next_case_id()
            assert case_id not in generated, f"Duplicate case_id: {case_id}"
            generated.add(case_id)
            # Simulate creating the case
            test_db.create_case_log(i + 1000, case_id, i + 2000)


class TestMuteEmbedBuilding:
    """Tests for mute embed building.

    NOTE: These tests require real discord.py to verify embed content.
    They are skipped in the mock environment but the method calls are verified.
    """

    @pytest.mark.skip(reason="Requires real discord.py for embed verification")
    def test_build_mute_embed_basic(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, monkeypatch):
        """Test building a basic mute embed."""
        pass

    @pytest.mark.skip(reason="Requires real discord.py for embed verification")
    def test_build_mute_embed_extension(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, monkeypatch):
        """Test building a mute extension embed."""
        pass

    @pytest.mark.skip(reason="Requires real discord.py for embed verification")
    def test_build_mute_embed_repeat_offender(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, monkeypatch):
        """Test mute embed shows repeat offender count."""
        pass

    @pytest.mark.skip(reason="Requires real discord.py for embed verification")
    def test_build_mute_embed_with_evidence(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, monkeypatch):
        """Test mute embed includes evidence."""
        pass

    def test_build_mute_embed_callable(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, monkeypatch):
        """Test that _build_mute_embed is callable without errors."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        service = CaseLogService(mock_bot)

        # Just verify it doesn't raise an exception
        embed = service._build_mute_embed(
            user=mock_discord_member,
            moderator=mock_discord_moderator,
            duration="1 hour",
            reason="Test reason",
            mute_count=1,
        )
        assert embed is not None


class TestDurationFormatting:
    """Tests for duration formatting."""

    def test_format_duration_seconds(self, test_db, mock_bot, monkeypatch):
        """Test formatting seconds."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        service = CaseLogService(mock_bot)

        assert service._format_duration_precise(30) == "30 seconds"
        assert service._format_duration_precise(1) == "1 second"

    def test_format_duration_minutes(self, test_db, mock_bot, monkeypatch):
        """Test formatting minutes."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        service = CaseLogService(mock_bot)

        assert service._format_duration_precise(60) == "1 minute"
        assert service._format_duration_precise(120) == "2 minutes"
        assert service._format_duration_precise(3599) == "59 minutes"

    def test_format_duration_hours(self, test_db, mock_bot, monkeypatch):
        """Test formatting hours."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        service = CaseLogService(mock_bot)

        assert service._format_duration_precise(3600) == "1 hour"
        assert service._format_duration_precise(7200) == "2 hours"
        assert service._format_duration_precise(5400) == "1h 30m"

    def test_format_duration_days(self, test_db, mock_bot, monkeypatch):
        """Test formatting days."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        service = CaseLogService(mock_bot)

        assert service._format_duration_precise(86400) == "1 day"
        assert service._format_duration_precise(172800) == "2 days"
        assert service._format_duration_precise(90000) == "1d 1h"


class TestAgeFormatting:
    """Tests for age formatting."""

    def test_format_age_days(self, test_db, mock_bot, monkeypatch):
        """Test formatting age in days."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        from src.core.config import NY_TZ
        service = CaseLogService(mock_bot)

        now = datetime.now(NY_TZ)
        start = now - timedelta(days=15)

        result = service._format_age(start, now)
        assert "15d" in result

    def test_format_age_months(self, test_db, mock_bot, monkeypatch):
        """Test formatting age in months."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        from src.core.config import NY_TZ
        service = CaseLogService(mock_bot)

        now = datetime.now(NY_TZ)
        start = now - timedelta(days=75)  # ~2.5 months

        result = service._format_age(start, now)
        assert "2m" in result

    def test_format_age_years(self, test_db, mock_bot, monkeypatch):
        """Test formatting age in years."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        from src.core.config import NY_TZ
        service = CaseLogService(mock_bot)

        now = datetime.now(NY_TZ)
        start = now - timedelta(days=500)  # ~1.4 years

        result = service._format_age(start, now)
        assert "1y" in result


class TestThreadCaching:
    """Tests for thread caching behavior."""

    @pytest.mark.asyncio
    async def test_thread_cache_hit(self, test_db, mock_bot, mock_discord_thread, monkeypatch):
        """Test thread cache returns cached thread."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        from src.core.config import NY_TZ
        service = CaseLogService(mock_bot)

        # Pre-populate cache
        thread_id = 555666777
        service._thread_cache[thread_id] = (mock_discord_thread, datetime.now(NY_TZ))

        # Get thread - should use cache
        result = await service._get_case_thread(thread_id)

        assert result == mock_discord_thread
        # bot.fetch_channel should NOT have been called
        mock_bot.fetch_channel.assert_not_called()

    @pytest.mark.asyncio
    async def test_thread_cache_miss_fetches(self, test_db, mock_bot, mock_discord_thread, monkeypatch):
        """Test thread cache miss fetches from Discord."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        service = CaseLogService(mock_bot)

        thread_id = 555666777
        mock_bot.get_channel.return_value = None
        mock_bot.fetch_channel = AsyncMock(return_value=mock_discord_thread)

        result = await service._get_case_thread(thread_id)

        assert result == mock_discord_thread
        mock_bot.fetch_channel.assert_called_once_with(thread_id)


class TestPendingReasonHandling:
    """Tests for pending reason reply handling."""

    def test_pending_reason_stored_on_mute_without_reason(self, test_db):
        """Test pending reason is created when mute has no reason."""
        # Create pending reason
        test_db.create_pending_reason(
            thread_id=555666777,
            warning_message_id=111222333,
            embed_message_id=444555666,
            moderator_id=123456789,
            target_user_id=987654321,
            action_type="mute",
        )

        pending = test_db.get_pending_reason_by_thread(555666777, 123456789)
        assert pending is not None
        assert pending["action_type"] == "mute"

    def test_pending_reason_not_returned_for_wrong_mod(self, test_db):
        """Test pending reason only returns for correct moderator."""
        test_db.create_pending_reason(
            thread_id=555666777,
            warning_message_id=111222333,
            embed_message_id=444555666,
            moderator_id=123456789,
            target_user_id=987654321,
            action_type="mute",
        )

        # Different moderator
        pending = test_db.get_pending_reason_by_thread(555666777, 999999999)
        assert pending is None

    def test_pending_reason_deleted_after_resolution(self, test_db):
        """Test pending reason is deleted when resolved."""
        test_db.create_pending_reason(
            thread_id=555666777,
            warning_message_id=111222333,
            embed_message_id=444555666,
            moderator_id=123456789,
            target_user_id=987654321,
            action_type="mute",
        )

        pending = test_db.get_pending_reason_by_thread(555666777, 123456789)
        test_db.delete_pending_reason(pending["id"])

        pending_after = test_db.get_pending_reason_by_thread(555666777, 123456789)
        assert pending_after is None


class TestCaseLogView:
    """Tests for CaseLogView button generation.

    NOTE: These tests require real discord.py to verify view children.
    They are skipped in the mock environment.
    """

    @pytest.mark.skip(reason="Requires real discord.py for view verification")
    def test_case_log_view_with_all_buttons(self, test_db, mock_bot, monkeypatch):
        """Test view includes all buttons when all data provided."""
        pass

    @pytest.mark.skip(reason="Requires real discord.py for view verification")
    def test_case_log_view_without_optional_buttons(self, test_db, mock_bot, monkeypatch):
        """Test view works without optional data."""
        pass

    def test_case_log_view_instantiates(self, test_db, mock_bot, monkeypatch):
        """Test that CaseLogView can be instantiated without errors."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogView

        # Just verify it doesn't raise an exception
        view = CaseLogView(
            user_id=123456789,
            guild_id=987654321,
            message_url="https://discord.com/channels/1/2/3",
            case_thread_id=555666777,
        )
        assert view is not None
