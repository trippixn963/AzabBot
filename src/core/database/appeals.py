"""
AzabBot - Appeals Mixin
=======================

Appeal operations for ban/mute appeals.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
import secrets
import string
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from src.core.logger import logger
from .models import AppealRecord

if TYPE_CHECKING:
    from .manager import DatabaseManager


class AppealsMixin:
    """Mixin for appeal operations."""

    def get_next_appeal_id(self: "DatabaseManager") -> str:
        """
        Generate next unique appeal ID (4 chars like AXXX).

        Returns:
            A unique 4-character appeal ID prefixed with 'A'.
        """
        # Prefix with 'A' for Appeal to distinguish from case IDs
        chars = string.ascii_uppercase + string.digits
        while True:
            appeal_id = 'A' + ''.join(secrets.choice(chars) for _ in range(3))
            existing = self.fetchone(
                "SELECT 1 FROM appeals WHERE appeal_id = ?",
                (appeal_id,)
            )
            if not existing:
                return appeal_id

    def create_appeal(
        self: "DatabaseManager",
        appeal_id: str,
        case_id: str,
        user_id: int,
        guild_id: int,
        thread_id: int,
        action_type: str,
        reason: Optional[str] = None,
        email: Optional[str] = None,
        attachments: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        """
        Create a new appeal.

        Args:
            appeal_id: Unique appeal ID.
            case_id: Original case ID being appealed.
            user_id: User submitting the appeal.
            guild_id: Guild ID.
            thread_id: Forum thread ID for this appeal.
            action_type: Type of action being appealed (ban/mute).
            reason: User's appeal reason.
            email: Optional email for notifications.
            attachments: Optional list of attachment metadata (name, type - no base64 data).
        """
        # Store only attachment metadata (name, type), not the actual data
        attachments_json = json.dumps(attachments) if attachments else None

        self.execute(
            """INSERT INTO appeals (
                appeal_id, case_id, user_id, guild_id, thread_id,
                action_type, reason, status, created_at, email, attachments
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (appeal_id, case_id, user_id, guild_id, thread_id, action_type, reason, time.time(), email, attachments_json)
        )

        logger.tree("Appeal Created", [
            ("Appeal ID", appeal_id),
            ("Case ID", case_id),
            ("User ID", str(user_id)),
            ("Type", action_type),
            ("Email", email[:20] + "..." if email and len(email) > 20 else (email or "None")),
            ("Attachments", str(len(attachments)) if attachments else "0"),
        ], emoji="📝")

    def get_appeal(self: "DatabaseManager", appeal_id: str) -> Optional[AppealRecord]:
        """
        Get an appeal by its ID.

        Args:
            appeal_id: Appeal ID.

        Returns:
            Appeal record or None.
        """
        row = self.fetchone(
            "SELECT * FROM appeals WHERE appeal_id = ?",
            (appeal_id,)
        )
        return dict(row) if row else None

    def get_appeal_by_case(self: "DatabaseManager", case_id: str) -> Optional[AppealRecord]:
        """
        Get appeal for a specific case.

        Args:
            case_id: Case ID.

        Returns:
            Appeal record or None.
        """
        row = self.fetchone(
            "SELECT * FROM appeals WHERE case_id = ?",
            (case_id,)
        )
        return dict(row) if row else None

    def get_pending_appeals(self: "DatabaseManager", guild_id: int) -> List[AppealRecord]:
        """
        Get all pending appeals for a guild.

        Args:
            guild_id: Guild ID.

        Returns:
            List of pending appeal records.
        """
        rows = self.fetchall(
            """SELECT * FROM appeals
               WHERE guild_id = ? AND status = 'pending'
               ORDER BY created_at ASC""",
            (guild_id,)
        )
        return [dict(row) for row in rows]

    def get_user_appeals(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int
    ) -> List[AppealRecord]:
        """
        Get all appeals for a user.

        Args:
            user_id: User ID.
            guild_id: Guild ID.

        Returns:
            List of appeal records.
        """
        rows = self.fetchall(
            """SELECT * FROM appeals
               WHERE user_id = ? AND guild_id = ?
               ORDER BY created_at DESC""",
            (user_id, guild_id)
        )
        return [dict(row) for row in rows]

    def resolve_appeal(
        self: "DatabaseManager",
        appeal_id: str,
        resolution: str,
        resolved_by: int,
        resolution_reason: Optional[str] = None,
    ) -> bool:
        """
        Resolve an appeal (approve/deny/close).

        Args:
            appeal_id: Appeal ID to resolve.
            resolution: Resolution type (approved/denied/closed).
            resolved_by: Moderator ID who resolved.
            resolution_reason: Optional reason for resolution.

        Returns:
            True if appeal was found and updated.
        """
        cursor = self.execute(
            """UPDATE appeals
               SET status = 'resolved',
                   resolved_at = ?,
                   resolved_by = ?,
                   resolution = ?,
                   resolution_reason = ?
               WHERE appeal_id = ? AND status = 'pending'""",
            (time.time(), resolved_by, resolution, resolution_reason, appeal_id)
        )

        if cursor.rowcount > 0:
            logger.tree("Appeal Resolved", [
                ("Appeal ID", appeal_id),
                ("Resolution", resolution),
                ("Resolved By", str(resolved_by)),
            ], emoji="✅" if resolution == "approved" else "❌")
            return True
        return False

    def can_appeal_case(
        self: "DatabaseManager",
        case_id: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a case can be appealed.

        Args:
            case_id: Case ID to check.

        Returns:
            Tuple of (can_appeal, reason_if_not).
        """
        # Check if already appealed
        existing = self.fetchone(
            "SELECT status, resolution FROM appeals WHERE case_id = ?",
            (case_id,)
        )

        if existing:
            if existing["status"] == "pending":
                return (False, "Case already has a pending appeal")
            elif existing["resolution"] == "denied":
                return (False, "Appeal was already denied")
            elif existing["resolution"] == "approved":
                return (False, "Appeal was already approved")

        return (True, None)

    def get_last_appeal_time(self: "DatabaseManager", case_id: str) -> Optional[float]:
        """
        Get the most recent appeal time for a case.

        Args:
            case_id: Case ID to check.

        Returns:
            Unix timestamp of last appeal or None.
        """
        row = self.fetchone(
            "SELECT created_at FROM appeals WHERE case_id = ? ORDER BY created_at DESC LIMIT 1",
            (case_id,)
        )
        return row["created_at"] if row else None

    def get_user_appeal_count_since(
        self: "DatabaseManager",
        user_id: int,
        since_timestamp: float
    ) -> int:
        """
        Count appeals from a user since a given time.

        Args:
            user_id: User ID to check.
            since_timestamp: Unix timestamp to count from.

        Returns:
            Number of appeals since the timestamp.
        """
        row = self.fetchone(
            "SELECT COUNT(*) as c FROM appeals WHERE user_id = ? AND created_at >= ?",
            (user_id, since_timestamp)
        )
        return row["c"] if row else 0

    def get_appealable_case(
        self: "DatabaseManager",
        case_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get case info for appeal eligibility check.

        Args:
            case_id: Case ID.

        Returns:
            Case record or None.
        """
        row = self.fetchone(
            """SELECT case_id, user_id, guild_id, action_type, moderator_id, reason,
                      duration_seconds, created_at, status, thread_id
               FROM cases
               WHERE case_id = ?""",
            (case_id,)
        )
        return dict(row) if row else None

    def get_appeal_stats(self: "DatabaseManager", guild_id: int) -> Dict[str, int]:
        """
        Get appeal statistics for a guild.

        Args:
            guild_id: Guild ID.

        Returns:
            Dict with pending, approved, denied counts.
        """
        # Single query with conditional aggregation (replaces 3 separate queries)
        row = self.fetchone(
            """
            SELECT
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN resolution = 'approved' THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN resolution = 'denied' THEN 1 ELSE 0 END) as denied
            FROM appeals
            WHERE guild_id = ?
            """,
            (guild_id,)
        )

        return {
            "pending": row["pending"] or 0 if row else 0,
            "approved": row["approved"] or 0 if row else 0,
            "denied": row["denied"] or 0 if row else 0,
        }


__all__ = ["AppealsMixin"]
