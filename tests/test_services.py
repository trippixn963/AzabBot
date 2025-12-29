"""
Azab Discord Bot - Service Layer Tests
=======================================

Integration tests for services using mocked Discord objects.
Tests the full flow from service method call to database update.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# =============================================================================
# Ticket Service Tests
# =============================================================================

class TestTicketServiceEnabled:
    """Tests for TicketService enabled property."""

    def test_enabled_when_channel_configured(self, mock_ticket_service):
        """Test enabled returns True when ticket channel is configured."""
        assert mock_ticket_service.enabled is True

    def test_disabled_when_no_channel(self, mock_ticket_service):
        """Test enabled returns False when no channel configured."""
        mock_ticket_service.config.ticket_channel_id = None
        assert mock_ticket_service.enabled is False


class TestTicketServicePermissions:
    """Tests for staff permission checks."""

    def test_developer_has_permission(self, mock_ticket_service, mock_discord_member):
        """Test developer always has staff permission."""
        mock_discord_member.id = mock_ticket_service.config.developer_id
        assert mock_ticket_service.has_staff_permission(mock_discord_member) is True

    def test_admin_has_permission(self, mock_ticket_service, mock_discord_member):
        """Test administrator has staff permission."""
        mock_discord_member.guild_permissions.administrator = True
        mock_discord_member.guild_permissions.moderate_members = False
        assert mock_ticket_service.has_staff_permission(mock_discord_member) is True

    def test_moderator_has_permission(self, mock_ticket_service, mock_discord_member):
        """Test moderate_members permission grants access."""
        mock_discord_member.guild_permissions.administrator = False
        mock_discord_member.guild_permissions.moderate_members = True
        assert mock_ticket_service.has_staff_permission(mock_discord_member) is True

    def test_staff_role_has_permission(self, mock_ticket_service, mock_discord_member):
        """Test ticket staff role grants permission."""
        mock_discord_member.guild_permissions.administrator = False
        mock_discord_member.guild_permissions.moderate_members = False
        # Create a mock role with the staff role ID
        staff_role = MagicMock()
        staff_role.id = mock_ticket_service.config.ticket_staff_role_id
        mock_discord_member.roles = [staff_role]
        assert mock_ticket_service.has_staff_permission(mock_discord_member) is True

    def test_regular_user_no_permission(self, mock_ticket_service, mock_discord_member):
        """Test regular user does not have staff permission."""
        mock_discord_member.id = 999999999  # Not developer
        mock_discord_member.guild_permissions.administrator = False
        mock_discord_member.guild_permissions.moderate_members = False
        mock_discord_member.roles = []
        assert mock_ticket_service.has_staff_permission(mock_discord_member) is False


class TestTicketServiceCreateTicket:
    """Tests for ticket creation."""

    @pytest.mark.asyncio
    async def test_create_ticket_disabled(self, mock_ticket_service, mock_discord_member):
        """Test ticket creation fails when service is disabled."""
        mock_ticket_service.config.ticket_channel_id = None
        success, message, ticket_id = await mock_ticket_service.create_ticket(
            user=mock_discord_member,
            category="support",
            subject="Test Subject",
            description="Test Description",
        )
        assert success is False
        assert "not enabled" in message.lower()
        assert ticket_id is None

    @pytest.mark.asyncio
    async def test_create_ticket_max_limit(self, mock_ticket_service, mock_discord_member, test_db):
        """Test ticket creation fails when user has max open tickets."""
        # Create 3 open tickets for this user
        for i in range(3):
            ticket_id = test_db.generate_ticket_id()
            test_db.create_ticket(
                ticket_id=ticket_id,
                user_id=mock_discord_member.id,
                guild_id=mock_discord_member.guild.id,
                thread_id=100000 + i,
                category="support",
                subject=f"Test {i}",
            )

        success, message, ticket_id = await mock_ticket_service.create_ticket(
            user=mock_discord_member,
            category="support",
            subject="New Ticket",
            description="Description",
        )
        assert success is False
        assert "already have" in message.lower()


class TestTicketServiceClaimTicket:
    """Tests for ticket claiming."""

    @pytest.mark.asyncio
    async def test_claim_nonexistent_ticket(self, mock_ticket_service, mock_discord_moderator):
        """Test claiming a ticket that doesn't exist."""
        success, message = await mock_ticket_service.claim_ticket("T9999", mock_discord_moderator)
        assert success is False
        assert "not found" in message.lower()

    @pytest.mark.asyncio
    async def test_claim_ticket_database_update(self, mock_ticket_service, mock_discord_moderator, test_db):
        """Test that claiming updates the database correctly."""
        # Create a ticket
        ticket_id = test_db.generate_ticket_id()
        test_db.create_ticket(
            ticket_id=ticket_id,
            user_id=123456789,
            guild_id=987654321,
            thread_id=555666777,
            category="support",
            subject="Test Ticket",
        )

        # Mock the thread fetch
        mock_ticket_service._get_ticket_thread = AsyncMock(return_value=None)

        success, message = await mock_ticket_service.claim_ticket(ticket_id, mock_discord_moderator)
        assert success is True

        # Verify database was updated
        ticket = test_db.get_ticket(ticket_id)
        assert ticket["status"] == "claimed"
        assert ticket["claimed_by"] == mock_discord_moderator.id


class TestTicketServiceCloseTicket:
    """Tests for ticket closing."""

    @pytest.mark.asyncio
    async def test_close_nonexistent_ticket(self, mock_ticket_service, mock_discord_moderator):
        """Test closing a ticket that doesn't exist."""
        success, message = await mock_ticket_service.close_ticket("T9999", mock_discord_moderator, "Reason")
        assert success is False
        assert "not found" in message.lower()

    @pytest.mark.asyncio
    async def test_close_already_closed(self, mock_ticket_service, mock_discord_moderator, test_db):
        """Test closing an already closed ticket."""
        # Create and close a ticket
        ticket_id = test_db.generate_ticket_id()
        test_db.create_ticket(
            ticket_id=ticket_id,
            user_id=123456789,
            guild_id=987654321,
            thread_id=555666777,
            category="support",
            subject="Test Ticket",
        )
        test_db.close_ticket(ticket_id, mock_discord_moderator.id, "Initial close")

        success, message = await mock_ticket_service.close_ticket(ticket_id, mock_discord_moderator, "Second close")
        assert success is False
        assert "already closed" in message.lower()


class TestTicketServicePriority:
    """Tests for ticket priority."""

    @pytest.mark.asyncio
    async def test_set_priority_updates_database(self, mock_ticket_service, mock_discord_moderator, test_db):
        """Test that setting priority updates the database."""
        ticket_id = test_db.generate_ticket_id()
        test_db.create_ticket(
            ticket_id=ticket_id,
            user_id=123456789,
            guild_id=987654321,
            thread_id=555666777,
            category="support",
            subject="Test Ticket",
        )

        mock_ticket_service._get_ticket_thread = AsyncMock(return_value=None)

        success, message = await mock_ticket_service.set_priority(ticket_id, "high", mock_discord_moderator)
        assert success is True

        ticket = test_db.get_ticket(ticket_id)
        assert ticket["priority"] == "high"


# =============================================================================
# Appeal Service Tests
# =============================================================================

class TestAppealServiceEnabled:
    """Tests for AppealService enabled property."""

    def test_enabled_when_forum_configured(self, mock_appeal_service):
        """Test enabled returns True when appeal forum is configured."""
        assert mock_appeal_service.enabled is True

    def test_disabled_when_no_forum(self, mock_appeal_service):
        """Test enabled returns False when no forum configured."""
        mock_appeal_service.config.appeal_forum_id = None
        assert mock_appeal_service.enabled is False


class TestAppealServiceCanAppeal:
    """Tests for appeal eligibility checks."""

    def test_cannot_appeal_disabled_service(self, mock_appeal_service):
        """Test cannot appeal when service is disabled."""
        mock_appeal_service.config.appeal_forum_id = None
        can_appeal, reason, case = mock_appeal_service.can_appeal("CASE001")
        assert can_appeal is False
        assert "not enabled" in reason.lower()

    def test_cannot_appeal_nonexistent_case(self, mock_appeal_service):
        """Test cannot appeal a case that doesn't exist."""
        can_appeal, reason, case = mock_appeal_service.can_appeal("NONEXISTENT")
        assert can_appeal is False
        assert "not found" in reason.lower()


class TestAppealServiceResolve:
    """Tests for appeal resolution."""

    @pytest.mark.asyncio
    async def test_approve_nonexistent_appeal(self, mock_appeal_service, mock_discord_moderator):
        """Test approving an appeal that doesn't exist."""
        success, message = await mock_appeal_service.approve_appeal("APL999", mock_discord_moderator)
        assert success is False
        assert "not found" in message.lower()

    @pytest.mark.asyncio
    async def test_deny_nonexistent_appeal(self, mock_appeal_service, mock_discord_moderator):
        """Test denying an appeal that doesn't exist."""
        success, message = await mock_appeal_service.deny_appeal("APL999", mock_discord_moderator)
        assert success is False
        assert "not found" in message.lower()


# =============================================================================
# Modmail Service Tests
# =============================================================================

class TestModmailServiceEnabled:
    """Tests for ModmailService enabled property."""

    def test_enabled_when_configured(self, mock_modmail_service):
        """Test enabled returns True when modmail forum and guild are configured."""
        assert mock_modmail_service.enabled is True

    def test_disabled_when_no_forum(self, mock_modmail_service):
        """Test enabled returns False when no forum configured."""
        mock_modmail_service.config.modmail_forum_id = None
        assert mock_modmail_service.enabled is False

    def test_disabled_when_no_guild(self, mock_modmail_service):
        """Test enabled returns False when no logging guild configured."""
        mock_modmail_service.config.logging_guild_id = None
        assert mock_modmail_service.enabled is False


class TestModmailServiceBanCheck:
    """Tests for ban checking."""

    @pytest.mark.asyncio
    async def test_ban_check_not_banned(self, mock_modmail_service, mock_discord_guild):
        """Test ban check returns False when user is not banned."""
        mock_modmail_service.bot.get_guild = MagicMock(return_value=mock_discord_guild)
        # Simulate NotFound exception for non-banned user
        mock_discord_guild.fetch_ban = AsyncMock(side_effect=Exception("Not Found"))

        # The method should catch the exception and return False
        result = await mock_modmail_service.is_user_banned(123456789)
        assert result is False

    @pytest.mark.asyncio
    async def test_ban_check_no_guild(self, mock_modmail_service):
        """Test ban check returns False when guild not found."""
        mock_modmail_service.bot.get_guild = MagicMock(return_value=None)
        result = await mock_modmail_service.is_user_banned(123456789)
        assert result is False


class TestModmailServiceHandleDM:
    """Tests for DM handling."""

    @pytest.mark.asyncio
    async def test_handle_dm_disabled(self, mock_modmail_service, mock_discord_message):
        """Test handle_dm returns False when service is disabled."""
        mock_modmail_service.config.modmail_forum_id = None
        result = await mock_modmail_service.handle_dm(mock_discord_message)
        assert result is False


class TestModmailServiceCreateThread:
    """Tests for modmail thread creation."""

    @pytest.mark.asyncio
    async def test_create_thread_disabled(self, mock_modmail_service, mock_discord_user):
        """Test create_thread returns None when service is disabled."""
        mock_modmail_service.config.modmail_forum_id = None
        result = await mock_modmail_service.create_thread(mock_discord_user)
        assert result is None


# =============================================================================
# Integration Tests (Multi-Service)
# =============================================================================

class TestServiceIntegration:
    """Tests that verify services work together correctly."""

    def test_ticket_id_generation_sequential(self, test_db):
        """Test that ticket IDs are generated sequentially."""
        # First ID should be T001
        id1 = test_db.generate_ticket_id()
        assert id1 == "T001"

        # Create a ticket with this ID to advance the counter
        test_db.create_ticket(
            ticket_id=id1,
            user_id=123,
            guild_id=456,
            thread_id=789,
            category="support",
            subject="Test 1",
        )

        # Next ID should be T002
        id2 = test_db.generate_ticket_id()
        assert id2 == "T002"

    def test_appeal_id_generation(self, test_db):
        """Test that appeal IDs are generated as 4-character alphanumeric."""
        id1 = test_db.get_next_appeal_id()
        # Appeal IDs are 4-character alphanumeric (e.g., A22H)
        assert len(id1) == 4
        assert id1[0].isupper()  # Starts with uppercase letter

    def test_database_ticket_lifecycle(self, test_db):
        """Test full ticket lifecycle in database."""
        # Create
        ticket_id = test_db.generate_ticket_id()
        test_db.create_ticket(
            ticket_id=ticket_id,
            user_id=123,
            guild_id=456,
            thread_id=789,
            category="support",
            subject="Test",
        )

        # Verify created
        ticket = test_db.get_ticket(ticket_id)
        assert ticket is not None
        assert ticket["status"] == "open"

        # Claim
        test_db.claim_ticket(ticket_id, 999)
        ticket = test_db.get_ticket(ticket_id)
        assert ticket["status"] == "claimed"
        assert ticket["claimed_by"] == 999

        # Close
        test_db.close_ticket(ticket_id, 999, "Resolved")
        ticket = test_db.get_ticket(ticket_id)
        assert ticket["status"] == "closed"
        assert ticket["close_reason"] == "Resolved"

        # Reopen
        test_db.reopen_ticket(ticket_id)
        ticket = test_db.get_ticket(ticket_id)
        assert ticket["status"] == "open"
