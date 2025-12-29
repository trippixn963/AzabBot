"""
Azab Discord Bot - Ticket System Tests
=======================================

Tests for the ticketing system database operations.
"""

import time
import pytest


class TestTicketOperations:
    """Tests for ticket database operations."""

    def test_generate_ticket_id_format(self, test_db):
        """Test ticket ID format is T followed by digits."""
        ticket_id = test_db.generate_ticket_id()
        assert ticket_id.startswith("T")
        assert ticket_id[1:].isdigit()

    def test_generate_ticket_id_sequential(self, test_db):
        """Test ticket IDs are sequential."""
        id1 = test_db.generate_ticket_id()
        # Create a ticket to use this ID
        test_db.create_ticket(
            ticket_id=id1,
            user_id=123456789,
            guild_id=987654321,
            thread_id=111222333,
            category="support",
            subject="Test ticket",
        )
        id2 = test_db.generate_ticket_id()

        # IDs should be sequential
        num1 = int(id1[1:])
        num2 = int(id2[1:])
        assert num2 == num1 + 1

    def test_create_ticket(self, test_db):
        """Test creating a ticket."""
        ticket_id = "T001"
        user_id = 123456789
        guild_id = 987654321
        thread_id = 111222333

        # create_ticket returns None (void function)
        test_db.create_ticket(
            ticket_id=ticket_id,
            user_id=user_id,
            guild_id=guild_id,
            thread_id=thread_id,
            category="support",
            subject="Test subject",
        )

        ticket = test_db.get_ticket(ticket_id)
        assert ticket is not None
        assert ticket["user_id"] == user_id
        assert ticket["category"] == "support"
        assert ticket["status"] == "open"

    def test_get_ticket(self, test_db):
        """Test getting a ticket by ID."""
        test_db.create_ticket(
            ticket_id="T001",
            user_id=123456789,
            guild_id=987654321,
            thread_id=111222333,
            category="partnership",
            subject="Partnership request",
        )

        ticket = test_db.get_ticket("T001")
        assert ticket is not None
        assert ticket["ticket_id"] == "T001"
        assert ticket["category"] == "partnership"

    def test_get_ticket_not_exists(self, test_db):
        """Test getting non-existent ticket returns None."""
        ticket = test_db.get_ticket("T999")
        assert ticket is None

    def test_get_ticket_by_thread(self, test_db):
        """Test getting ticket by thread ID."""
        thread_id = 555666777
        test_db.create_ticket(
            ticket_id="T001",
            user_id=123456789,
            guild_id=987654321,
            thread_id=thread_id,
            category="suggestion",
            subject="A suggestion",
        )

        ticket = test_db.get_ticket_by_thread(thread_id)
        assert ticket is not None
        assert ticket["thread_id"] == thread_id

    def test_get_user_tickets(self, test_db):
        """Test getting all tickets for a user."""
        user_id = 123456789
        guild_id = 987654321

        # Create multiple tickets
        test_db.create_ticket("T001", user_id, guild_id, 111, "support", "First")
        test_db.create_ticket("T002", user_id, guild_id, 222, "partnership", "Second")
        test_db.create_ticket("T003", user_id, guild_id, 333, "suggestion", "Third")

        tickets = test_db.get_user_tickets(user_id, guild_id)
        assert len(tickets) == 3

    def test_get_user_open_ticket_count(self, test_db):
        """Test counting open tickets for a user."""
        user_id = 123456789
        guild_id = 987654321

        # Create 3 tickets
        test_db.create_ticket("T001", user_id, guild_id, 111, "support", "First")
        test_db.create_ticket("T002", user_id, guild_id, 222, "support", "Second")
        test_db.create_ticket("T003", user_id, guild_id, 333, "support", "Third")

        count = test_db.get_user_open_ticket_count(user_id, guild_id)
        assert count == 3

        # Close one
        test_db.close_ticket("T001", user_id, "Done")
        count = test_db.get_user_open_ticket_count(user_id, guild_id)
        assert count == 2

    def test_claim_ticket(self, test_db):
        """Test claiming a ticket."""
        test_db.create_ticket("T001", 123456789, 987654321, 111, "support", "Test")

        result = test_db.claim_ticket("T001", 111222333)
        assert result is True

        ticket = test_db.get_ticket("T001")
        assert ticket["status"] == "claimed"
        assert ticket["claimed_by"] == 111222333

    def test_unclaim_ticket(self, test_db):
        """Test unclaiming a ticket."""
        test_db.create_ticket("T001", 123456789, 987654321, 111, "support", "Test")
        test_db.claim_ticket("T001", 111222333)

        result = test_db.unclaim_ticket("T001")
        assert result is True

        ticket = test_db.get_ticket("T001")
        assert ticket["status"] == "open"
        assert ticket["claimed_by"] is None

    def test_close_ticket(self, test_db):
        """Test closing a ticket."""
        test_db.create_ticket("T001", 123456789, 987654321, 111, "support", "Test")

        result = test_db.close_ticket("T001", 111222333, "Issue resolved")
        assert result is True

        ticket = test_db.get_ticket("T001")
        assert ticket["status"] == "closed"
        assert ticket["closed_by"] == 111222333
        assert ticket["close_reason"] == "Issue resolved"

    def test_reopen_ticket(self, test_db):
        """Test reopening a closed ticket."""
        test_db.create_ticket("T001", 123456789, 987654321, 111, "support", "Test")
        test_db.close_ticket("T001", 111222333, "Closed")

        result = test_db.reopen_ticket("T001")
        assert result is True

        ticket = test_db.get_ticket("T001")
        assert ticket["status"] == "open"
        assert ticket["closed_at"] is None

    def test_set_ticket_priority(self, test_db):
        """Test setting ticket priority."""
        test_db.create_ticket("T001", 123456789, 987654321, 111, "support", "Test")

        result = test_db.set_ticket_priority("T001", "high")
        assert result is True

        ticket = test_db.get_ticket("T001")
        assert ticket["priority"] == "high"

    def test_assign_ticket(self, test_db):
        """Test assigning a ticket."""
        test_db.create_ticket("T001", 123456789, 987654321, 111, "support", "Test")

        result = test_db.assign_ticket("T001", 444555666)
        assert result is True

        ticket = test_db.get_ticket("T001")
        assert ticket["assigned_to"] == 444555666

    def test_get_open_tickets(self, test_db):
        """Test getting all open tickets for a guild."""
        guild_id = 987654321

        # Create tickets with different statuses
        test_db.create_ticket("T001", 111, guild_id, 1001, "support", "Open 1")
        test_db.create_ticket("T002", 222, guild_id, 1002, "support", "Open 2")
        test_db.create_ticket("T003", 333, guild_id, 1003, "support", "Will close")
        test_db.close_ticket("T003", 444, "Closed")

        open_tickets = test_db.get_open_tickets(guild_id)
        assert len(open_tickets) == 2

    def test_get_ticket_stats(self, test_db):
        """Test getting ticket statistics."""
        guild_id = 987654321

        # Create various tickets
        test_db.create_ticket("T001", 111, guild_id, 1001, "support", "Open")
        test_db.create_ticket("T002", 222, guild_id, 1002, "support", "Claimed")
        test_db.claim_ticket("T002", 999)
        test_db.create_ticket("T003", 333, guild_id, 1003, "support", "Closed")
        test_db.close_ticket("T003", 999, "Done")

        stats = test_db.get_ticket_stats(guild_id)
        # Stats returns open, claimed, closed (no total key)
        assert stats["open"] == 1
        assert stats["claimed"] == 1
        assert stats["closed"] == 1


class TestTicketActivity:
    """Tests for ticket activity tracking."""

    def test_update_ticket_activity(self, test_db):
        """Test updating ticket last activity."""
        test_db.create_ticket("T001", 123456789, 987654321, 111, "support", "Test")

        before = test_db.get_ticket("T001")
        time.sleep(0.1)  # Small delay

        # update_ticket_activity returns cursor, not bool
        test_db.update_ticket_activity("T001")

        after = test_db.get_ticket("T001")
        assert after["last_activity_at"] > before["last_activity_at"]

    def test_mark_ticket_warned(self, test_db):
        """Test marking ticket as warned for inactivity."""
        test_db.create_ticket("T001", 123456789, 987654321, 111, "support", "Test")

        # mark_ticket_warned returns cursor, not bool
        test_db.mark_ticket_warned("T001")

        ticket = test_db.get_ticket("T001")
        assert ticket["warned_at"] is not None

    def test_clear_ticket_warning(self, test_db):
        """Test clearing ticket warning."""
        test_db.create_ticket("T001", 123456789, 987654321, 111, "support", "Test")
        test_db.mark_ticket_warned("T001")

        # clear_ticket_warning returns cursor, not bool
        test_db.clear_ticket_warning("T001")

        ticket = test_db.get_ticket("T001")
        assert ticket["warned_at"] is None

    def test_get_unwarned_inactive_tickets(self, test_db):
        """Test getting inactive tickets that haven't been warned."""
        guild_id = 987654321
        old_time = time.time() - 400000  # Very old

        # Create ticket and backdate BOTH last_activity_at AND created_at
        test_db.create_ticket("T001", 111, guild_id, 1001, "support", "Old ticket")
        test_db.execute(
            "UPDATE tickets SET last_activity_at = ?, created_at = ? WHERE ticket_id = ?",
            (old_time, old_time, "T001")
        )

        # Get inactive tickets
        threshold = time.time() - 300000
        inactive = test_db.get_unwarned_inactive_tickets(guild_id, threshold)
        assert len(inactive) >= 1
        assert any(t["ticket_id"] == "T001" for t in inactive)

    def test_get_warned_tickets_ready_to_close(self, test_db):
        """Test getting warned tickets ready for auto-close."""
        guild_id = 987654321
        old_time = time.time() - 400000

        # Create, warn, and backdate ticket
        test_db.create_ticket("T001", 111, guild_id, 1001, "support", "Warned ticket")
        test_db.mark_ticket_warned("T001")
        test_db.execute(
            "UPDATE tickets SET warned_at = ? WHERE ticket_id = ?",
            (old_time, "T001")
        )

        # Get warned tickets ready to close
        threshold = time.time() - 300000
        ready = test_db.get_warned_tickets_ready_to_close(guild_id, threshold)
        assert len(ready) >= 1
        assert any(t["ticket_id"] == "T001" for t in ready)


class TestTicketCategories:
    """Tests for ticket categories."""

    def test_support_category(self, test_db):
        """Test creating support ticket."""
        test_db.create_ticket("T001", 123, 456, 789, "support", "Support request")
        ticket = test_db.get_ticket("T001")
        assert ticket["category"] == "support"

    def test_partnership_category(self, test_db):
        """Test creating partnership ticket."""
        test_db.create_ticket("T001", 123, 456, 789, "partnership", "Partnership inquiry")
        ticket = test_db.get_ticket("T001")
        assert ticket["category"] == "partnership"

    def test_suggestion_category(self, test_db):
        """Test creating suggestion ticket."""
        test_db.create_ticket("T001", 123, 456, 789, "suggestion", "A great idea")
        ticket = test_db.get_ticket("T001")
        assert ticket["category"] == "suggestion"
