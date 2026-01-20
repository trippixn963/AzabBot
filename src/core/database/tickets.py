"""
Database Ticket Operations Module
=================================

Ticket system database operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from src.core.logger import logger
from src.core.database.models import TicketRecord

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


class TicketsMixin:
    """Mixin for ticket database operations."""

    def generate_ticket_id(self: "DatabaseManager") -> str:
        """
        Generate next sequential ticket ID (T001, T002, etc.).

        Returns:
            Next available ticket ID.
        """
        row = self.fetchone(
            "SELECT ticket_id FROM tickets ORDER BY id DESC LIMIT 1"
        )
        if row and row["ticket_id"]:
            try:
                num = int(row["ticket_id"][1:])
                return f"T{num + 1:03d}"
            except (ValueError, IndexError):
                pass
        return "T001"

    def create_ticket(
        self: "DatabaseManager",
        ticket_id: str,
        user_id: int,
        guild_id: int,
        thread_id: int,
        category: str,
        subject: str,
    ) -> None:
        """Create a new support ticket."""
        now = time.time()
        self.execute(
            """INSERT INTO tickets (
                ticket_id, user_id, guild_id, thread_id,
                category, subject, status, priority, created_at, last_activity_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'open', 'normal', ?, ?)""",
            (ticket_id, user_id, guild_id, thread_id, category, subject, now, now)
        )
        logger.tree("Ticket Created", [
            ("Ticket ID", ticket_id),
            ("Category", category),
            ("User ID", str(user_id)),
        ], emoji="🎫")

    def get_ticket(self: "DatabaseManager", ticket_id: str) -> Optional[TicketRecord]:
        """Get a ticket by its ID."""
        row = self.fetchone("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
        return dict(row) if row else None

    def get_ticket_by_thread(self: "DatabaseManager", thread_id: int) -> Optional[TicketRecord]:
        """Get ticket by its forum thread ID."""
        row = self.fetchone("SELECT * FROM tickets WHERE thread_id = ?", (thread_id,))
        return dict(row) if row else None

    def get_user_tickets(self: "DatabaseManager", user_id: int, guild_id: int) -> List[TicketRecord]:
        """Get all tickets for a user."""
        rows = self.fetchall(
            """SELECT * FROM tickets WHERE user_id = ? AND guild_id = ?
               ORDER BY created_at DESC""",
            (user_id, guild_id)
        )
        return [dict(row) for row in rows]

    def get_open_tickets(self: "DatabaseManager", guild_id: int) -> List[TicketRecord]:
        """Get all open tickets for a guild."""
        rows = self.fetchall(
            """SELECT * FROM tickets WHERE guild_id = ? AND status IN ('open', 'claimed')
               ORDER BY
                   CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2
                   WHEN 'normal' THEN 3 WHEN 'low' THEN 4 END,
                   created_at ASC""",
            (guild_id,)
        )
        return [dict(row) for row in rows]

    def claim_ticket(self: "DatabaseManager", ticket_id: str, staff_id: int) -> bool:
        """Claim a ticket for handling."""
        cursor = self.execute(
            """UPDATE tickets SET status = 'claimed', claimed_by = ?, claimed_at = ?
               WHERE ticket_id = ? AND status = 'open'""",
            (staff_id, time.time(), ticket_id)
        )
        if cursor.rowcount > 0:
            logger.tree("Ticket Claimed", [
                ("Ticket ID", ticket_id),
                ("Staff ID", str(staff_id)),
            ], emoji="✋")
            return True
        return False

    def unclaim_ticket(self: "DatabaseManager", ticket_id: str) -> bool:
        """Unclaim a ticket."""
        cursor = self.execute(
            """UPDATE tickets SET status = 'open', claimed_by = NULL
               WHERE ticket_id = ? AND status = 'claimed'""",
            (ticket_id,)
        )
        if cursor.rowcount > 0:
            logger.debug("Ticket Unclaimed", [("Ticket ID", ticket_id)])
        return cursor.rowcount > 0

    def transfer_ticket(self: "DatabaseManager", ticket_id: str, new_staff_id: int) -> bool:
        """Transfer a ticket to a different staff member."""
        cursor = self.execute(
            """UPDATE tickets SET claimed_by = ?, claimed_at = ?
               WHERE ticket_id = ? AND status IN ('open', 'claimed')""",
            (new_staff_id, time.time(), ticket_id)
        )
        if cursor.rowcount > 0:
            logger.tree("Ticket Transferred (DB)", [
                ("Ticket ID", ticket_id),
                ("New Staff ID", str(new_staff_id)),
            ], emoji="🔄")
            return True
        return False

    def assign_ticket(self: "DatabaseManager", ticket_id: str, staff_id: int) -> bool:
        """Assign a ticket to a staff member."""
        cursor = self.execute(
            "UPDATE tickets SET assigned_to = ? WHERE ticket_id = ?",
            (staff_id, ticket_id)
        )
        if cursor.rowcount > 0:
            logger.tree("Ticket Assigned", [
                ("Ticket ID", ticket_id),
                ("Assigned To", str(staff_id)),
            ], emoji="👤")
            return True
        return False

    def set_ticket_priority(self: "DatabaseManager", ticket_id: str, priority: str) -> bool:
        """Set ticket priority."""
        if priority not in ("low", "normal", "high", "urgent"):
            return False
        cursor = self.execute(
            "UPDATE tickets SET priority = ? WHERE ticket_id = ?",
            (priority, ticket_id)
        )
        if cursor.rowcount > 0:
            logger.tree("Ticket Priority Set", [
                ("Ticket ID", ticket_id),
                ("Priority", priority),
            ], emoji="🔔")
            return True
        return False

    def close_ticket(
        self: "DatabaseManager",
        ticket_id: str,
        closed_by: int,
        close_reason: Optional[str] = None,
    ) -> bool:
        """Close a ticket."""
        cursor = self.execute(
            """UPDATE tickets SET status = 'closed', closed_at = ?, closed_by = ?, close_reason = ?
               WHERE ticket_id = ? AND status != 'closed'""",
            (time.time(), closed_by, close_reason, ticket_id)
        )
        if cursor.rowcount > 0:
            logger.tree("Ticket Closed", [
                ("Ticket ID", ticket_id),
                ("Closed By", str(closed_by)),
                ("Reason", close_reason or "No reason"),
            ], emoji="🔒")
            return True
        return False

    def reopen_ticket(self: "DatabaseManager", ticket_id: str) -> bool:
        """Reopen a closed ticket."""
        cursor = self.execute(
            """UPDATE tickets SET status = 'open', closed_at = NULL, closed_by = NULL, close_reason = NULL
               WHERE ticket_id = ? AND status = 'closed'""",
            (ticket_id,)
        )
        if cursor.rowcount > 0:
            logger.tree("Ticket Reopened", [("Ticket ID", ticket_id)], emoji="🔓")
            return True
        return False

    def get_ticket_stats(self: "DatabaseManager", guild_id: int) -> Dict[str, int]:
        """Get ticket statistics for a guild."""
        open_count = self.fetchone(
            "SELECT COUNT(*) as c FROM tickets WHERE guild_id = ? AND status = 'open'",
            (guild_id,)
        )
        claimed_count = self.fetchone(
            "SELECT COUNT(*) as c FROM tickets WHERE guild_id = ? AND status = 'claimed'",
            (guild_id,)
        )
        closed_count = self.fetchone(
            "SELECT COUNT(*) as c FROM tickets WHERE guild_id = ? AND status = 'closed'",
            (guild_id,)
        )
        return {
            "open": open_count["c"] if open_count else 0,
            "claimed": claimed_count["c"] if claimed_count else 0,
            "closed": closed_count["c"] if closed_count else 0,
        }

    def get_staff_ticket_stats(self: "DatabaseManager", staff_id: int, guild_id: int) -> Dict[str, int]:
        """Get ticket statistics for a specific staff member."""
        claimed_count = self.fetchone(
            "SELECT COUNT(*) as c FROM tickets WHERE guild_id = ? AND claimed_by = ?",
            (guild_id, staff_id)
        )
        closed_count = self.fetchone(
            "SELECT COUNT(*) as c FROM tickets WHERE guild_id = ? AND closed_by = ?",
            (guild_id, staff_id)
        )
        return {
            "claimed": claimed_count["c"] if claimed_count else 0,
            "closed": closed_count["c"] if closed_count else 0,
        }

    def get_average_response_time(self: "DatabaseManager", guild_id: int, days: int = 30) -> Optional[float]:
        """Get average ticket response time (time from creation to first claim)."""
        cutoff = time.time() - (days * 24 * 60 * 60)
        row = self.fetchone(
            """SELECT AVG(claimed_at - created_at) as avg_time FROM tickets
               WHERE guild_id = ? AND claimed_at IS NOT NULL AND created_at > ?
               AND (claimed_at - created_at) > 0 AND (claimed_at - created_at) < 604800""",
            (guild_id, cutoff)
        )
        return row["avg_time"] if row and row["avg_time"] is not None else None

    def get_open_ticket_position(self: "DatabaseManager", ticket_id: str, guild_id: int) -> int:
        """Get the position of a ticket in the queue."""
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            return 0
        row = self.fetchone(
            """SELECT COUNT(*) as c FROM tickets
               WHERE guild_id = ? AND status = 'open' AND created_at < ?""",
            (guild_id, ticket["created_at"])
        )
        return row["c"] if row else 0

    def get_user_open_ticket_count(self: "DatabaseManager", user_id: int, guild_id: int) -> int:
        """Count open tickets for a user."""
        row = self.fetchone(
            """SELECT COUNT(*) as c FROM tickets
               WHERE user_id = ? AND guild_id = ? AND status IN ('open', 'claimed')""",
            (user_id, guild_id)
        )
        return row["c"] if row else 0

    def update_ticket_activity(self: "DatabaseManager", ticket_id: str) -> bool:
        """Update last activity timestamp for a ticket."""
        cursor = self.execute(
            "UPDATE tickets SET last_activity_at = ? WHERE ticket_id = ?",
            (time.time(), ticket_id)
        )
        return cursor.rowcount > 0

    def get_inactive_tickets(
        self: "DatabaseManager", guild_id: int, inactive_since: float
    ) -> List[TicketRecord]:
        """Get tickets with no activity since a given timestamp."""
        rows = self.fetchall(
            """SELECT * FROM tickets WHERE guild_id = ? AND status IN ('open', 'claimed')
               AND (last_activity_at IS NULL OR last_activity_at < ?) AND (created_at < ?)
               ORDER BY last_activity_at ASC""",
            (guild_id, inactive_since, inactive_since)
        )
        return [TicketRecord(**dict(row)) for row in rows]

    def get_unwarned_inactive_tickets(
        self: "DatabaseManager", guild_id: int, inactive_since: float
    ) -> List[TicketRecord]:
        """Get inactive tickets that haven't been warned yet."""
        rows = self.fetchall(
            """SELECT * FROM tickets WHERE guild_id = ? AND status IN ('open', 'claimed')
               AND (last_activity_at IS NULL OR last_activity_at < ?) AND (created_at < ?)
               AND warned_at IS NULL ORDER BY last_activity_at ASC""",
            (guild_id, inactive_since, inactive_since)
        )
        return [TicketRecord(**dict(row)) for row in rows]

    def get_warned_tickets_ready_to_close(
        self: "DatabaseManager", guild_id: int, warned_before: float
    ) -> List[TicketRecord]:
        """Get tickets that were warned and are now ready to auto-close."""
        rows = self.fetchall(
            """SELECT * FROM tickets WHERE guild_id = ? AND status IN ('open', 'claimed')
               AND warned_at IS NOT NULL AND warned_at < ? ORDER BY warned_at ASC""",
            (guild_id, warned_before)
        )
        return [TicketRecord(**dict(row)) for row in rows]

    def get_closed_tickets_ready_to_delete(
        self: "DatabaseManager", guild_id: int, closed_before: float
    ) -> List[TicketRecord]:
        """Get closed tickets that are ready for deletion."""
        rows = self.fetchall(
            """SELECT * FROM tickets WHERE guild_id = ? AND status = 'closed'
               AND closed_at IS NOT NULL AND closed_at < ? ORDER BY closed_at ASC""",
            (guild_id, closed_before)
        )
        return [TicketRecord(**dict(row)) for row in rows]

    def delete_ticket(self: "DatabaseManager", ticket_id: str) -> bool:
        """Delete a ticket from the database."""
        cursor = self.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket_id,))
        if cursor.rowcount > 0:
            logger.debug("Ticket Deleted", [("Ticket ID", ticket_id)])
        return cursor.rowcount > 0

    def mark_ticket_warned(self: "DatabaseManager", ticket_id: str) -> bool:
        """Mark a ticket as warned about inactivity."""
        cursor = self.execute(
            "UPDATE tickets SET warned_at = ? WHERE ticket_id = ?",
            (time.time(), ticket_id)
        )
        if cursor.rowcount > 0:
            logger.debug("Ticket Warned", [("Ticket ID", ticket_id)])
        return cursor.rowcount > 0

    def clear_ticket_warning(self: "DatabaseManager", ticket_id: str) -> bool:
        """Clear inactivity warning (when user responds)."""
        cursor = self.execute(
            "UPDATE tickets SET warned_at = NULL WHERE ticket_id = ?",
            (ticket_id,)
        )
        if cursor.rowcount > 0:
            logger.debug("Ticket Warning Cleared", [("Ticket ID", ticket_id)])
        return cursor.rowcount > 0

    def save_ticket_transcript(self: "DatabaseManager", ticket_id: str, html_content: str) -> bool:
        """Save HTML transcript for a ticket."""
        cursor = self.execute(
            "UPDATE tickets SET transcript_html = ? WHERE ticket_id = ?",
            (html_content, ticket_id)
        )
        if cursor.rowcount > 0:
            logger.debug("Ticket Transcript Saved", [("Ticket ID", ticket_id)])
        return cursor.rowcount > 0

    def get_ticket_transcript(self: "DatabaseManager", ticket_id: str) -> Optional[str]:
        """Get HTML transcript for a ticket."""
        row = self.fetchone(
            "SELECT transcript_html FROM tickets WHERE ticket_id = ?",
            (ticket_id,)
        )
        return row["transcript_html"] if row and row["transcript_html"] else None

    def save_ticket_transcript_json(self: "DatabaseManager", ticket_id: str, transcript_json: str) -> bool:
        """Save JSON transcript for a ticket (for web viewer)."""
        cursor = self.execute(
            "UPDATE tickets SET transcript = ? WHERE ticket_id = ?",
            (transcript_json, ticket_id)
        )
        if cursor.rowcount > 0:
            logger.debug("Ticket JSON Transcript Saved", [("Ticket ID", ticket_id)])
        return cursor.rowcount > 0

    def get_ticket_transcript_json(self: "DatabaseManager", ticket_id: str) -> Optional[str]:
        """Get JSON transcript for a ticket."""
        row = self.fetchone("SELECT transcript FROM tickets WHERE ticket_id = ?", (ticket_id,))
        return row["transcript"] if row and row["transcript"] else None

    def set_control_panel_message(self: "DatabaseManager", ticket_id: str, message_id: int) -> bool:
        """Set the control panel message ID for a ticket."""
        cursor = self.execute(
            "UPDATE tickets SET control_panel_message_id = ? WHERE ticket_id = ?",
            (message_id, ticket_id)
        )
        if cursor.rowcount > 0:
            logger.debug("Ticket Control Panel Set", [
                ("Ticket ID", ticket_id),
                ("Message ID", str(message_id)),
            ])
        return cursor.rowcount > 0

    def clear_close_request(self: "DatabaseManager", ticket_id: str) -> bool:
        """Clear close request status for a ticket."""
        return True
