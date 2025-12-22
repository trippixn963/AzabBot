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

        # Should have 3 children: Case button, Message button, Download button
        assert len(view.children) == 3

        # Check button labels
        labels = [getattr(c, 'label', '') for c in view.children]
        assert "Case" in labels
        assert "Message" in labels

    def test_case_log_view_without_optional_buttons(self, test_db, mock_bot, monkeypatch):
        """Test view works without optional message URL."""
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

        # Should only have 1 child: Download button
        assert len(view.children) == 1

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
# Integration Tests: Mute → Case Log → Reply Flow
# =============================================================================

class TestMuteCaseLogIntegration:
    """Integration tests for the full mute → case log → reply flow."""

    @pytest.mark.asyncio
    async def test_log_mute_creates_case_and_thread(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, mock_discord_forum, mock_discord_thread, monkeypatch):
        """Test that log_mute creates a case and thread for new users."""
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

        service = CaseLogService(mock_bot)

        # Log mute for a new user
        result = await service.log_mute(
            user=mock_discord_member,
            moderator=mock_discord_moderator,
            duration="1 hour",
            reason="Test reason",
        )

        # Verify case was created
        assert result is not None
        assert "case_id" in result
        assert "thread_id" in result
        assert len(result["case_id"]) == 4

        # Verify database entry
        case = test_db.get_case_log(mock_discord_member.id)
        assert case is not None
        assert case["mute_count"] == 1

    @pytest.mark.asyncio
    async def test_log_mute_increments_count_for_existing_case(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, mock_discord_thread, monkeypatch):
        """Test that second mute increments count for existing case."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 444555666
        mock_config.developer_id = 111222333
        mock_config.logging_guild_id = 987654321
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService

        # Pre-create a case
        test_db.create_case_log(mock_discord_member.id, "ABCD", mock_discord_thread.id)

        # Setup mocks
        mock_bot.get_channel.return_value = mock_discord_thread
        mock_bot.fetch_channel = AsyncMock(return_value=mock_discord_thread)
        mock_discord_thread.send = AsyncMock(return_value=MagicMock(id=888999000))

        service = CaseLogService(mock_bot)

        # Log second mute
        result = await service.log_mute(
            user=mock_discord_member,
            moderator=mock_discord_moderator,
            duration="2 hours",
            reason="Second offense",
        )

        # Verify mute count incremented
        case = test_db.get_case_log(mock_discord_member.id)
        assert case["mute_count"] == 2

    @pytest.mark.asyncio
    async def test_log_mute_creates_pending_reason_without_reason(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, mock_discord_thread, monkeypatch):
        """Test that mute without reason creates pending reason entry."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 444555666
        mock_config.developer_id = 111222333
        mock_config.logging_guild_id = 987654321
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService

        # Pre-create a case
        test_db.create_case_log(mock_discord_member.id, "ABCD", mock_discord_thread.id)

        # Setup mocks
        mock_bot.get_channel.return_value = mock_discord_thread
        mock_bot.fetch_channel = AsyncMock(return_value=mock_discord_thread)

        embed_msg = MagicMock(id=111111)
        warning_msg = MagicMock(id=222222)
        mock_discord_thread.send = AsyncMock(side_effect=[embed_msg, warning_msg])

        service = CaseLogService(mock_bot)

        # Log mute without reason
        await service.log_mute(
            user=mock_discord_member,
            moderator=mock_discord_moderator,
            duration="1 hour",
            reason=None,  # No reason
        )

        # Verify pending reason was created
        pending = test_db.get_pending_reason_by_thread(mock_discord_thread.id, mock_discord_moderator.id)
        assert pending is not None
        assert pending["action_type"] == "mute"
        assert pending["embed_message_id"] == 111111
        assert pending["warning_message_id"] == 222222

    @pytest.mark.asyncio
    async def test_handle_reason_reply_updates_embed(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, mock_discord_thread, monkeypatch):
        """Test that replying with reason updates the embed."""
        from src.core import config as config_module
        mock_config = MagicMock()
        mock_config.case_log_forum_id = 444555666
        mock_config.developer_id = 111222333
        mock_config.logging_guild_id = 987654321
        monkeypatch.setattr(config_module, "_config", mock_config)

        from src.services.case_log import CaseLogService
        from tests.conftest import MockEmbed

        # Create pending reason
        test_db.create_pending_reason(
            thread_id=mock_discord_thread.id,
            warning_message_id=222222,
            embed_message_id=111111,
            moderator_id=mock_discord_moderator.id,
            target_user_id=mock_discord_member.id,
            action_type="mute",
        )

        # Create mock embed message with our MockEmbed
        mock_embed = MockEmbed(title="🔇 User Muted")
        mock_embed.add_field(name="Reason", value="```No reason provided```", inline=False)

        embed_msg = MagicMock()
        embed_msg.id = 111111
        embed_msg.embeds = [mock_embed]
        embed_msg.edit = AsyncMock()

        warning_msg = MagicMock()
        warning_msg.id = 222222
        warning_msg.delete = AsyncMock()

        # Setup thread to return messages
        mock_discord_thread.fetch_message = AsyncMock(side_effect=lambda id: embed_msg if id == 111111 else warning_msg)

        # Create mock reply message with attachment
        reply_message = MagicMock()
        reply_message.content = "Spamming in chat"
        reply_message.channel = mock_discord_thread
        reply_message.author = mock_discord_moderator
        reply_message.id = 333333
        reply_message.reference = MagicMock()
        reply_message.reference.message_id = 222222  # Reply to warning
        reply_message.attachments = [
            MagicMock(content_type="image/png", url="https://example.com/evidence.png")
        ]
        reply_message.delete = AsyncMock()

        mock_bot.get_channel.return_value = mock_discord_thread
        mock_bot.fetch_channel = AsyncMock(return_value=mock_discord_thread)

        service = CaseLogService(mock_bot)

        # Handle the reply
        result = await service.handle_reason_reply(reply_message)

        assert result is True

        # Verify pending reason was deleted
        pending_after = test_db.get_pending_reason_by_thread(mock_discord_thread.id, mock_discord_moderator.id)
        assert pending_after is None

    @pytest.mark.asyncio
    async def test_full_mute_unmute_flow(self, test_db, mock_bot, mock_discord_member, mock_discord_moderator, mock_discord_forum, mock_discord_thread, monkeypatch):
        """Test full flow: mute → case created → unmute logged."""
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

        # Step 1: Log mute
        mute_result = await service.log_mute(
            user=mock_discord_member,
            moderator=mock_discord_moderator,
            duration="1 hour",
            reason="Testing",
        )
        assert mute_result is not None

        # Step 2: Log unmute
        mock_bot.get_channel.return_value = mock_discord_thread
        unmute_result = await service.log_unmute(
            user_id=mock_discord_member.id,
            moderator=mock_discord_moderator,
            display_name=mock_discord_member.display_name,
            reason="Test complete",
        )

        assert unmute_result is not None
        assert unmute_result["case_id"] == mute_result["case_id"]

        # Verify database reflects unmute
        case = test_db.get_case_log(mock_discord_member.id)
        assert case["last_unmute_at"] is not None


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
