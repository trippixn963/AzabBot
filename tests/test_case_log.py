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
    """Tests for mute embed building."""

    def test_build_mute_embed_basic(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, monkeypatch):
        """Test building a basic mute embed."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        service = CaseLogService(mock_bot)

        embed = service._build_mute_embed(
            user=mock_discord_member,
            moderator=mock_discord_moderator,
            duration="1 hour",
            reason="Test reason",
            mute_count=1,
        )

        # Verify embed content
        assert embed is not None
        assert "Muted" in embed.title
        assert "#1" not in embed.title  # First mute doesn't show count
        # Check fields (use .name attribute for MockEmbedField)
        field_names = [f.name for f in embed.fields]
        assert "Muted By" in field_names
        assert "Duration" in field_names
        assert "Reason" in field_names

    def test_build_mute_embed_extension(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, monkeypatch):
        """Test building a mute extension embed."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        service = CaseLogService(mock_bot)

        embed = service._build_mute_embed(
            user=mock_discord_member,
            moderator=mock_discord_moderator,
            duration="2 hours",
            reason="Extended mute",
            mute_count=2,
            is_extension=True,
        )

        # Verify extension title
        assert "Extended" in embed.title

    def test_build_mute_embed_repeat_offender(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, monkeypatch):
        """Test mute embed shows repeat offender count."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        service = CaseLogService(mock_bot)

        embed = service._build_mute_embed(
            user=mock_discord_member,
            moderator=mock_discord_moderator,
            duration="1 hour",
            reason="Repeat offense",
            mute_count=5,
        )

        # Verify mute count in title
        assert "#5" in embed.title

    def test_build_mute_embed_with_evidence(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, monkeypatch):
        """Test mute embed includes evidence."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        service = CaseLogService(mock_bot)

        embed = service._build_mute_embed(
            user=mock_discord_member,
            moderator=mock_discord_moderator,
            duration="1 hour",
            reason="Test reason",
            mute_count=1,
            evidence="https://example.com/screenshot.png",
        )

        # Verify evidence field exists (use .name attribute for MockEmbedField)
        field_names = [f.name for f in embed.fields]
        assert "Evidence" in field_names
        evidence_field = next(f for f in embed.fields if f.name == "Evidence")
        assert "https://example.com/screenshot.png" in evidence_field.value

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
    """Tests for CaseLogView button generation."""

    def test_case_log_view_with_all_buttons(self, test_db, mock_bot, monkeypatch):
        """Test view includes all buttons when all data provided."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogView

        view = CaseLogView(
            user_id=123456789,
            guild_id=987654321,
            message_url="https://discord.com/channels/1/2/3",
            case_thread_id=555666777,
        )

        # Should have 6 children: Case, Message (row 0), Info, Avatar, History, Notes (row 1)
        assert len(view.children) == 6

        # Check button labels
        labels = [getattr(c, 'label', '') for c in view.children]
        assert "Case" in labels
        assert "Message" in labels

    def test_case_log_view_without_optional_buttons(self, test_db, mock_bot, monkeypatch):
        """Test view works without optional message URL and case thread."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogView

        # No message_url, no case_thread_id
        view = CaseLogView(
            user_id=123456789,
            guild_id=987654321,
            message_url=None,
            case_thread_id=None,
        )

        # Should have 4 children: Info, Avatar, History, Notes (row 1 only)
        assert len(view.children) == 4

    def test_case_log_view_case_button_url(self, test_db, mock_bot, monkeypatch):
        """Test case button has correct URL."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 123456789
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogView

        view = CaseLogView(
            user_id=123456789,
            guild_id=987654321,
            message_url=None,
            case_thread_id=555666777,
        )

        # Find case button
        case_button = next((c for c in view.children if getattr(c, 'label', '') == "Case"), None)
        assert case_button is not None
        assert "987654321" in case_button.url  # Guild ID
        assert "555666777" in case_button.url  # Thread ID

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


# =============================================================================
# Integration Tests: Per-Action Case System
# =============================================================================

class TestMuteCaseLogIntegration:
    """Integration tests for the per-action case system."""

    @pytest.mark.asyncio
    async def test_log_mute_creates_per_action_case(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, mock_discord_forum, mock_discord_thread, monkeypatch):
        """Test that log_mute creates a per-action case with its own thread."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 444555666
        mock_config.developer_id = 111222333
        mock_config.logging_guild_id = 987654321
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService

        # Setup mock thread creation
        thread_result = MagicMock()
        thread_result.thread = mock_discord_thread
        thread_result.message = MagicMock(id=999888777)
        mock_discord_forum.create_thread = AsyncMock(return_value=thread_result)
        mock_bot.get_channel.return_value = mock_discord_forum
        mock_bot.fetch_channel = AsyncMock(return_value=mock_discord_thread)
        mock_discord_thread.send = AsyncMock(return_value=MagicMock(id=888999000))

        service = CaseLogService(mock_bot)

        # Log mute for a new user
        result = await service.log_mute(
            user=mock_discord_member,
            moderator=mock_discord_moderator,
            duration="1 hour",
            reason="Test reason",
        )

        # Verify per-action case was created
        assert result is not None
        assert "case_id" in result
        assert "thread_id" in result
        assert len(result["case_id"]) == 4

        # Verify per-action case in database
        case = test_db.get_case(result["case_id"])
        assert case is not None
        assert case["action_type"] == "mute"
        assert case["status"] == "open"

    @pytest.mark.asyncio
    async def test_second_mute_creates_new_case(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, mock_discord_forum, mock_discord_thread, monkeypatch):
        """Test that second mute creates a NEW per-action case (not reusing old one)."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 444555666
        mock_config.developer_id = 111222333
        mock_config.logging_guild_id = 987654321
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService

        # Setup mocks
        thread_result = MagicMock()
        thread_result.thread = mock_discord_thread
        thread_result.message = MagicMock(id=999888777)
        mock_discord_forum.create_thread = AsyncMock(return_value=thread_result)
        mock_bot.get_channel.return_value = mock_discord_forum
        mock_bot.fetch_channel = AsyncMock(return_value=mock_discord_thread)
        mock_discord_thread.send = AsyncMock(return_value=MagicMock(id=888999000))

        service = CaseLogService(mock_bot)

        # First mute
        result1 = await service.log_mute(
            user=mock_discord_member,
            moderator=mock_discord_moderator,
            duration="1 hour",
            reason="First offense",
        )

        # Resolve the first case
        test_db.resolve_case(result1["case_id"], mock_discord_moderator.id, "Unmuted")

        # Second mute
        result2 = await service.log_mute(
            user=mock_discord_member,
            moderator=mock_discord_moderator,
            duration="2 hours",
            reason="Second offense",
        )

        # Verify different case IDs
        assert result1["case_id"] != result2["case_id"]

        # Verify both cases exist
        case1 = test_db.get_case(result1["case_id"])
        case2 = test_db.get_case(result2["case_id"])
        assert case1 is not None
        assert case2 is not None
        assert case1["status"] == "resolved"
        assert case2["status"] == "open"

    @pytest.mark.asyncio
    async def test_unmute_resolves_active_mute_case(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, mock_discord_forum, mock_discord_thread, monkeypatch):
        """Test that unmute finds and resolves the active mute case."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 444555666
        mock_config.developer_id = 111222333
        mock_config.logging_guild_id = 987654321
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService

        # Setup mocks
        thread_result = MagicMock()
        thread_result.thread = mock_discord_thread
        thread_result.message = MagicMock(id=999888777)
        mock_discord_forum.create_thread = AsyncMock(return_value=thread_result)
        mock_bot.get_channel.return_value = mock_discord_forum
        mock_bot.fetch_channel = AsyncMock(return_value=mock_discord_thread)
        mock_discord_thread.send = AsyncMock(return_value=MagicMock(id=888999000))

        service = CaseLogService(mock_bot)

        # Step 1: Log mute (creates per-action case)
        mute_result = await service.log_mute(
            user=mock_discord_member,
            moderator=mock_discord_moderator,
            duration="1 hour",
            reason="Testing",
        )
        assert mute_result is not None

        # Verify case is open
        case_before = test_db.get_case(mute_result["case_id"])
        assert case_before["status"] == "open"

        # Step 2: Log unmute (should find and resolve the case)
        mock_bot.get_channel.return_value = mock_discord_thread
        unmute_result = await service.log_unmute(
            user_id=mock_discord_member.id,
            moderator=mock_discord_moderator,
            display_name=mock_discord_member.display_name,
            reason="Test complete",
        )

        assert unmute_result is not None
        assert unmute_result["case_id"] == mute_result["case_id"]

        # Verify case is now resolved
        case_after = test_db.get_case(mute_result["case_id"])
        assert case_after["status"] == "resolved"
        assert case_after["resolved_by"] == mock_discord_moderator.id

    @pytest.mark.asyncio
    async def test_get_user_cases_returns_all_cases(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, monkeypatch):
        """Test that get_user_cases returns all cases for a user."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 444555666
        monkeypatch.setattr(config_module, "_config", mock_config)

        guild_id = mock_discord_member.guild.id

        # Create some cases directly in the database
        test_db.create_case("ABC1", mock_discord_member.id, guild_id, 111, "mute", mock_discord_moderator.id, "Reason 1", 3600, None)
        test_db.create_case("ABC2", mock_discord_member.id, guild_id, 222, "warn", mock_discord_moderator.id, "Reason 2", None, None)
        test_db.create_case("ABC3", mock_discord_member.id, guild_id, 333, "ban", mock_discord_moderator.id, "Reason 3", None, None)

        # Resolve one case
        test_db.resolve_case("ABC1", mock_discord_moderator.id, "Unmuted")

        # Get all cases
        cases = test_db.get_user_cases(mock_discord_member.id, guild_id, limit=10, include_resolved=True)
        assert len(cases) == 3

        # Get only open cases
        open_cases = test_db.get_user_cases(mock_discord_member.id, guild_id, limit=10, include_resolved=False)
        assert len(open_cases) == 2

    @pytest.mark.asyncio
    async def test_get_user_case_counts(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, monkeypatch):
        """Test that get_user_case_counts returns correct counts by action type."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 444555666
        monkeypatch.setattr(config_module, "_config", mock_config)

        guild_id = mock_discord_member.guild.id

        # Create cases of different types
        test_db.create_case("MUT1", mock_discord_member.id, guild_id, 111, "mute", mock_discord_moderator.id, "Mute 1", 3600, None)
        test_db.create_case("MUT2", mock_discord_member.id, guild_id, 222, "mute", mock_discord_moderator.id, "Mute 2", 3600, None)
        test_db.create_case("WRN1", mock_discord_member.id, guild_id, 333, "warn", mock_discord_moderator.id, "Warn 1", None, None)
        test_db.create_case("BAN1", mock_discord_member.id, guild_id, 444, "ban", mock_discord_moderator.id, "Ban 1", None, None)

        # Get counts
        counts = test_db.get_user_case_counts(mock_discord_member.id, guild_id)
        assert counts["mute_count"] == 2
        assert counts["warn_count"] == 1
        assert counts["ban_count"] == 1


class TestDebounceProfileUpdates:
    """Tests for debounced profile stats updates."""

    @pytest.mark.asyncio
    async def test_schedule_profile_update_queues_update(self, test_db, mock_bot, mock_discord_thread, monkeypatch):
        """Test that scheduling profile update adds to pending queue."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 444555666
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService

        service = CaseLogService(mock_bot)

        # Create a case
        test_db.create_case_log(123456789, "ABCD", mock_discord_thread.id)
        case = test_db.get_case_log(123456789)

        # Schedule update
        service._schedule_profile_update(123456789, case)

        # Verify it was queued
        assert 123456789 in service._pending_profile_updates

    @pytest.mark.asyncio
    async def test_multiple_updates_coalesce(self, test_db, mock_bot, mock_discord_thread, monkeypatch):
        """Test that multiple rapid updates for same user are coalesced."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 444555666
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService

        service = CaseLogService(mock_bot)

        # Create a case
        test_db.create_case_log(123456789, "ABCD", mock_discord_thread.id)
        case1 = test_db.get_case_log(123456789)

        # Schedule multiple updates
        service._schedule_profile_update(123456789, case1)

        # Increment mute count
        test_db.increment_mute_count(123456789)
        case2 = test_db.get_case_log(123456789)
        service._schedule_profile_update(123456789, case2)

        # Verify only one entry (latest)
        assert len(service._pending_profile_updates) == 1
        assert service._pending_profile_updates[123456789]["mute_count"] == 2
