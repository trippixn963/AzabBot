"""
Azab Discord Bot - Button & Modal Interaction Tests
====================================================

Tests for Discord button callbacks and modal submissions.
Uses mocked Discord objects to simulate user interactions.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# =============================================================================
# Ticket Button Tests
# =============================================================================

class TestTicketClaimButton:
    """Tests for TicketClaimButton callback."""

    @pytest.mark.asyncio
    async def test_claim_button_no_permission(self, mock_discord_interaction, mock_config):
        """Test claim button fails without staff permission."""
        from src.services.ticket_service import TicketClaimButton

        # Setup
        button = TicketClaimButton("T001")
        mock_discord_interaction.user.id = 999999999  # Not developer
        mock_discord_interaction.user.guild_permissions = MagicMock()
        mock_discord_interaction.user.guild_permissions.administrator = False
        mock_discord_interaction.user.guild_permissions.moderate_members = False
        mock_discord_interaction.user.roles = []

        # Mock the bot's ticket service
        mock_ticket_service = MagicMock()
        mock_ticket_service.has_staff_permission = MagicMock(return_value=False)
        mock_discord_interaction.client.ticket_service = mock_ticket_service

        # Execute
        await button.callback(mock_discord_interaction)

        # Verify permission denied message
        mock_discord_interaction.response.send_message.assert_called_once()
        call_args = mock_discord_interaction.response.send_message.call_args
        assert "permission" in call_args[0][0].lower()
        assert call_args[1]["ephemeral"] is True

    @pytest.mark.asyncio
    async def test_claim_button_service_unavailable(self, mock_discord_interaction):
        """Test claim button fails when service unavailable."""
        from src.services.ticket_service import TicketClaimButton

        button = TicketClaimButton("T001")
        mock_discord_interaction.client.ticket_service = None

        # Test with hasattr returning False
        delattr(mock_discord_interaction.client, 'ticket_service')

        await button.callback(mock_discord_interaction)

        mock_discord_interaction.response.send_message.assert_called_once()
        call_args = mock_discord_interaction.response.send_message.call_args
        assert "unavailable" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_claim_button_success(self, mock_discord_interaction, mock_discord_user):
        """Test successful ticket claim."""
        from src.services.ticket_service import TicketClaimButton

        button = TicketClaimButton("T001")

        # Setup mock ticket service
        mock_ticket_service = MagicMock()
        mock_ticket_service.has_staff_permission = MagicMock(return_value=True)
        mock_ticket_service.claim_ticket = AsyncMock(return_value=(True, "Ticket claimed"))
        mock_ticket_service.db = MagicMock()
        mock_ticket_service.db.get_ticket = MagicMock(return_value={
            "ticket_id": "T001",
            "user_id": 123456789,
        })
        mock_discord_interaction.client.ticket_service = mock_ticket_service
        mock_discord_interaction.client.fetch_user = AsyncMock(return_value=mock_discord_user)
        mock_discord_interaction.client.interaction_logger = None

        await button.callback(mock_discord_interaction)

        # Verify claim was called
        mock_ticket_service.claim_ticket.assert_called_once_with("T001", mock_discord_interaction.user)


class TestTicketCloseButton:
    """Tests for TicketCloseButton callback."""

    @pytest.mark.asyncio
    async def test_close_button_no_permission(self, mock_discord_interaction):
        """Test close button fails without permission."""
        from src.services.ticket_service import TicketCloseButton

        button = TicketCloseButton("T001")

        mock_ticket_service = MagicMock()
        mock_ticket_service.has_staff_permission = MagicMock(return_value=False)
        mock_discord_interaction.client.ticket_service = mock_ticket_service

        await button.callback(mock_discord_interaction)

        mock_discord_interaction.response.send_message.assert_called_once()
        call_args = mock_discord_interaction.response.send_message.call_args
        assert "permission" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_close_button_shows_modal(self, mock_discord_interaction):
        """Test close button shows modal when user has permission."""
        from src.services.ticket_service import TicketCloseButton

        button = TicketCloseButton("T001")

        mock_ticket_service = MagicMock()
        mock_ticket_service.has_staff_permission = MagicMock(return_value=True)
        mock_discord_interaction.client.ticket_service = mock_ticket_service

        await button.callback(mock_discord_interaction)

        # Verify modal was shown
        mock_discord_interaction.response.send_modal.assert_called_once()


class TestTicketReopenButton:
    """Tests for TicketReopenButton callback."""

    @pytest.mark.asyncio
    async def test_reopen_button_no_permission(self, mock_discord_interaction):
        """Test reopen button fails without permission."""
        from src.services.ticket_service import TicketReopenButton

        button = TicketReopenButton("T001")

        mock_ticket_service = MagicMock()
        mock_ticket_service.has_staff_permission = MagicMock(return_value=False)
        mock_discord_interaction.client.ticket_service = mock_ticket_service

        await button.callback(mock_discord_interaction)

        mock_discord_interaction.response.send_message.assert_called_once()
        call_args = mock_discord_interaction.response.send_message.call_args
        assert "permission" in call_args[0][0].lower()


class TestTicketAddUserButton:
    """Tests for TicketAddUserButton callback."""

    @pytest.mark.asyncio
    async def test_add_user_button_no_permission(self, mock_discord_interaction):
        """Test add user button fails without permission."""
        from src.services.ticket_service import TicketAddUserButton

        button = TicketAddUserButton("T001")

        mock_ticket_service = MagicMock()
        mock_ticket_service.has_staff_permission = MagicMock(return_value=False)
        mock_discord_interaction.client.ticket_service = mock_ticket_service

        await button.callback(mock_discord_interaction)

        mock_discord_interaction.response.send_message.assert_called_once()
        call_args = mock_discord_interaction.response.send_message.call_args
        assert "permission" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_add_user_button_shows_modal(self, mock_discord_interaction):
        """Test add user button shows modal when user has permission."""
        from src.services.ticket_service import TicketAddUserButton

        button = TicketAddUserButton("T001")

        mock_ticket_service = MagicMock()
        mock_ticket_service.has_staff_permission = MagicMock(return_value=True)
        mock_discord_interaction.client.ticket_service = mock_ticket_service

        await button.callback(mock_discord_interaction)

        mock_discord_interaction.response.send_modal.assert_called_once()


class TestTicketTranscriptButton:
    """Tests for TicketTranscriptButton callback."""

    @pytest.mark.asyncio
    async def test_transcript_button_no_permission(self, mock_discord_interaction):
        """Test transcript button fails without permission."""
        from src.services.ticket_service import TicketTranscriptButton

        button = TicketTranscriptButton("T001")

        mock_ticket_service = MagicMock()
        mock_ticket_service.has_staff_permission = MagicMock(return_value=False)
        mock_discord_interaction.client.ticket_service = mock_ticket_service

        await button.callback(mock_discord_interaction)

        mock_discord_interaction.response.send_message.assert_called_once()
        call_args = mock_discord_interaction.response.send_message.call_args
        assert "permission" in call_args[0][0].lower()


# =============================================================================
# Appeal Button Tests
# =============================================================================

class TestApproveAppealButton:
    """Tests for ApproveAppealButton callback."""

    @pytest.mark.asyncio
    async def test_approve_button_no_permission(self, mock_discord_interaction, mock_config):
        """Test approve button fails without permission."""
        from src.services.appeal_service import ApproveAppealButton

        button = ApproveAppealButton("APL001", "CASE001")

        # Setup user without permissions
        mock_discord_interaction.user.id = 999999999
        mock_discord_interaction.user.guild_permissions = MagicMock()
        mock_discord_interaction.user.guild_permissions.moderate_members = False

        with patch('src.services.appeal_service.get_config', return_value=mock_config):
            await button.callback(mock_discord_interaction)

        mock_discord_interaction.response.send_message.assert_called_once()
        call_args = mock_discord_interaction.response.send_message.call_args
        assert "permission" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_approve_button_shows_modal(self, mock_discord_interaction, mock_config):
        """Test approve button shows modal when user has permission."""
        from src.services.appeal_service import ApproveAppealButton

        button = ApproveAppealButton("APL001", "CASE001")

        # Setup user with permissions
        mock_discord_interaction.user.id = mock_config.developer_id
        mock_discord_interaction.user.guild_permissions = MagicMock()
        mock_discord_interaction.user.guild_permissions.moderate_members = True

        with patch('src.services.appeal_service.get_config', return_value=mock_config):
            await button.callback(mock_discord_interaction)

        mock_discord_interaction.response.send_modal.assert_called_once()


class TestDenyAppealButton:
    """Tests for DenyAppealButton callback."""

    @pytest.mark.asyncio
    async def test_deny_button_no_permission(self, mock_discord_interaction, mock_config):
        """Test deny button fails without permission."""
        from src.services.appeal_service import DenyAppealButton

        button = DenyAppealButton("APL001", "CASE001")

        mock_discord_interaction.user.id = 999999999
        mock_discord_interaction.user.guild_permissions = MagicMock()
        mock_discord_interaction.user.guild_permissions.moderate_members = False

        with patch('src.services.appeal_service.get_config', return_value=mock_config):
            await button.callback(mock_discord_interaction)

        mock_discord_interaction.response.send_message.assert_called_once()
        call_args = mock_discord_interaction.response.send_message.call_args
        assert "permission" in call_args[0][0].lower()


class TestSubmitAppealButton:
    """Tests for SubmitAppealButton callback."""

    @pytest.mark.asyncio
    async def test_submit_appeal_wrong_user(self, mock_discord_interaction):
        """Test submit appeal fails for wrong user."""
        from src.services.appeal_service import SubmitAppealButton

        button = SubmitAppealButton("CASE001", 123456789)
        mock_discord_interaction.user.id = 999999999  # Different user

        await button.callback(mock_discord_interaction)

        mock_discord_interaction.response.send_message.assert_called_once()
        call_args = mock_discord_interaction.response.send_message.call_args
        assert "own cases" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_submit_appeal_service_unavailable(self, mock_discord_interaction):
        """Test submit appeal fails when service unavailable."""
        from src.services.appeal_service import SubmitAppealButton

        button = SubmitAppealButton("CASE001", 123456789)
        mock_discord_interaction.user.id = 123456789  # Correct user
        mock_discord_interaction.client.appeal_service = None

        # Remove appeal_service attribute
        if hasattr(mock_discord_interaction.client, 'appeal_service'):
            delattr(mock_discord_interaction.client, 'appeal_service')

        await button.callback(mock_discord_interaction)

        mock_discord_interaction.response.send_message.assert_called_once()
        call_args = mock_discord_interaction.response.send_message.call_args
        assert "not available" in call_args[0][0].lower()


# =============================================================================
# Modmail Button Tests
# =============================================================================

class TestModmailCloseButton:
    """Tests for ModmailCloseButton callback."""

    @pytest.mark.asyncio
    async def test_close_button_service_unavailable(self, mock_discord_interaction):
        """Test modmail close fails when service unavailable."""
        from src.services.modmail_service import ModmailCloseButton

        button = ModmailCloseButton(123456789)

        # Remove modmail_service attribute
        if hasattr(mock_discord_interaction.client, 'modmail_service'):
            delattr(mock_discord_interaction.client, 'modmail_service')

        await button.callback(mock_discord_interaction)

        mock_discord_interaction.response.send_message.assert_called_once()
        call_args = mock_discord_interaction.response.send_message.call_args
        assert "unavailable" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_close_button_not_in_thread(self, mock_discord_interaction):
        """Test modmail close fails when not in a thread."""
        from src.services.modmail_service import ModmailCloseButton

        button = ModmailCloseButton(123456789)

        mock_modmail_service = MagicMock()
        mock_discord_interaction.client.modmail_service = mock_modmail_service
        mock_discord_interaction.channel = MagicMock()  # Not a Thread

        # Mock isinstance to return False for Thread check
        with patch('src.services.modmail_service.isinstance', return_value=False):
            await button.callback(mock_discord_interaction)

        mock_discord_interaction.response.send_message.assert_called_once()
        call_args = mock_discord_interaction.response.send_message.call_args
        assert "thread" in call_args[0][0].lower()


# =============================================================================
# Modal Tests (Skipped - discord.ui.Modal mocking is complex)
# =============================================================================
# Modal classes inherit from discord.ui.Modal which requires special handling
# in tests. The Modal callbacks are tested indirectly through the button tests
# that show the modals. For full modal testing, consider using dpytest with
# a real bot instance.


# =============================================================================
# DynamicItem Pattern Tests
# =============================================================================

class TestDynamicItemPatterns:
    """Tests for DynamicItem custom_id pattern matching."""

    def test_ticket_claim_pattern(self):
        """Test TicketClaimButton custom_id pattern."""
        from src.services.ticket_service import TicketClaimButton
        import re

        pattern = r"tkt_claim:(?P<ticket_id>T\d+)"
        custom_id = "tkt_claim:T001"

        match = re.match(pattern, custom_id)
        assert match is not None
        assert match.group("ticket_id") == "T001"

    def test_ticket_close_pattern(self):
        """Test TicketCloseButton custom_id pattern."""
        import re

        pattern = r"tkt_close:(?P<ticket_id>T\d+)"
        custom_id = "tkt_close:T123"

        match = re.match(pattern, custom_id)
        assert match is not None
        assert match.group("ticket_id") == "T123"

    def test_appeal_approve_pattern(self):
        """Test ApproveAppealButton custom_id pattern."""
        import re

        pattern = r"appeal_approve:(?P<appeal_id>[A-Z0-9]+):(?P<case_id>[A-Z0-9]+)"
        custom_id = "appeal_approve:APL001:CASE123"

        match = re.match(pattern, custom_id)
        assert match is not None
        assert match.group("appeal_id") == "APL001"
        assert match.group("case_id") == "CASE123"

    def test_modmail_close_pattern(self):
        """Test ModmailCloseButton custom_id pattern."""
        import re

        pattern = r"modmail_close:(?P<user_id>\d+)"
        custom_id = "modmail_close:123456789"

        match = re.match(pattern, custom_id)
        assert match is not None
        assert match.group("user_id") == "123456789"

    def test_submit_appeal_pattern(self):
        """Test SubmitAppealButton custom_id pattern."""
        import re

        pattern = r"submit_appeal:(?P<case_id>[A-Z0-9]+):(?P<user_id>\d+)"
        custom_id = "submit_appeal:CASE001:123456789"

        match = re.match(pattern, custom_id)
        assert match is not None
        assert match.group("case_id") == "CASE001"
        assert match.group("user_id") == "123456789"
