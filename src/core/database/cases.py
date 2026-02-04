"""
AzabBot - Database Case Operations Module
=========================================

Per-action case database operations (new cases table).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
import time
import string
import secrets
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from src.core.logger import logger

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


class CasesMixin:
    """Mixin for per-action case database operations."""

    def get_next_case_id(self: "DatabaseManager") -> str:
        """
        Generate a unique 4-character alphanumeric case ID.

        DESIGN:
            Uses uppercase letters and digits for readability.
            Checks both legacy case_logs and new cases tables for uniqueness.
            With 36^4 = 1,679,616 possible combinations, collisions are rare.

        Returns:
            Unique 4-character case ID (e.g., "A7X2", "K3M9").
        """
        chars = string.ascii_uppercase + string.digits  # A-Z, 0-9

        while True:
            # Generate random 4-character code
            case_id = ''.join(secrets.choice(chars) for _ in range(4))

            # Check both tables in a single query for efficiency
            row = self.fetchone(
                """
                SELECT 1 FROM case_logs WHERE case_id = ?
                UNION ALL
                SELECT 1 FROM cases WHERE case_id = ?
                LIMIT 1
                """,
                (case_id, case_id)
            )

            if not row:
                return case_id

    def create_case(
        self,
        case_id: str,
        user_id: int,
        guild_id: int,
        thread_id: int,
        action_type: str,
        moderator_id: int,
        reason: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        evidence: Optional[str] = None,
    ) -> str:
        """
        Create a new per-action case.

        Args:
            case_id: Unique 4-char case ID.
            user_id: Target user ID.
            guild_id: Guild ID.
            thread_id: Forum thread ID for this case.
            action_type: 'mute', 'ban', or 'warn'.
            moderator_id: Moderator who created the case.
            reason: Optional reason for the action.
            duration_seconds: Optional duration (for mutes).
            evidence: Optional evidence URL/text.

        Returns:
            The case_id.
        """
        now = time.time()
        self.execute(
            """INSERT INTO cases
               (case_id, user_id, guild_id, thread_id, action_type, status,
                moderator_id, reason, duration_seconds, evidence, created_at)
               VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)""",
            (case_id, user_id, guild_id, thread_id, action_type,
             moderator_id, reason, duration_seconds, evidence, now)
        )

        logger.tree("Case Created", [
            ("Case ID", case_id),
            ("User ID", str(user_id)),
            ("Action", action_type),
            ("Moderator", str(moderator_id)),
        ], emoji="📋")

        return case_id

    def get_case(self: "DatabaseManager", case_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a case by its ID.

        Args:
            case_id: The 4-char case ID.

        Returns:
            Case dict or None if not found.
        """
        row = self.fetchone(
            "SELECT * FROM cases WHERE case_id = ?",
            (case_id,)
        )
        return dict(row) if row else None

    def update_case_reason(self: "DatabaseManager", case_id: str, new_reason: Optional[str], edited_by: int) -> bool:
        """
        Update the reason for a case.

        Args:
            case_id: The 4-char case ID.
            new_reason: The new reason text (or None to clear).
            edited_by: User ID of who edited the case.

        Returns:
            True if updated successfully, False if case doesn't exist or error occurred.
        """
        try:
            cursor = self.execute(
                """
                UPDATE cases
                SET reason = ?, updated_at = ?
                WHERE case_id = ?
                """,
                (new_reason, time.time(), case_id)
            )
            # Check if any row was actually updated
            if cursor.rowcount > 0:
                logger.debug("Case Reason Updated", [
                    ("Case ID", case_id),
                    ("Edited By", str(edited_by)),
                ])
                return True
            else:
                logger.debug("Case Not Found for Update", [
                    ("Case ID", case_id),
                ])
                return False
        except Exception as e:
            logger.error("Case Reason Update Failed", [
                ("Case ID", case_id),
                ("Error", str(e)[:100]),
                ("Type", type(e).__name__),
            ])
            return False

    def get_case_by_thread(self: "DatabaseManager", thread_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a case by its thread ID.

        Args:
            thread_id: The forum thread ID.

        Returns:
            Case dict or None if not found.
        """
        row = self.fetchone(
            "SELECT * FROM cases WHERE thread_id = ?",
            (thread_id,)
        )
        return dict(row) if row else None

    def get_active_mute_case(
        self,
        user_id: int,
        guild_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the most recent open mute case for a user.

        Used when unmuting to find the case thread to log to.

        Args:
            user_id: Target user ID.
            guild_id: Guild ID.

        Returns:
            Active mute case dict or None.
        """
        row = self.fetchone(
            """SELECT * FROM cases
               WHERE user_id = ? AND guild_id = ?
               AND action_type = 'mute' AND status = 'open'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, guild_id)
        )
        return dict(row) if row else None

    def get_active_ban_case(
        self,
        user_id: int,
        guild_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the most recent open ban case for a user.

        Used when unbanning to find the case thread to log to.

        Args:
            user_id: Target user ID.
            guild_id: Guild ID.

        Returns:
            Active ban case dict or None.
        """
        row = self.fetchone(
            """SELECT * FROM cases
               WHERE user_id = ? AND guild_id = ?
               AND action_type = 'ban' AND status = 'open'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, guild_id)
        )
        return dict(row) if row else None

    def get_active_forbid_case(
        self,
        user_id: int,
        guild_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the most recent open forbid case for a user.

        Used when unforbidding to find the case thread to log to.

        Args:
            user_id: Target user ID.
            guild_id: Guild ID.

        Returns:
            Active forbid case dict or None.
        """
        row = self.fetchone(
            """SELECT * FROM cases
               WHERE user_id = ? AND guild_id = ?
               AND action_type = 'forbid' AND status = 'open'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, guild_id)
        )
        return dict(row) if row else None

    def get_most_recent_forbid_case(
        self,
        user_id: int,
        guild_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the most recent forbid case (open or resolved) for a user.

        Used when unforbidding and no open case exists.
        Includes approved cases that might need to be unlocked.

        Args:
            user_id: Target user ID.
            guild_id: Guild ID.

        Returns:
            Most recent forbid case dict or None.
        """
        row = self.fetchone(
            """SELECT * FROM cases
               WHERE user_id = ? AND guild_id = ?
               AND action_type = 'forbid'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, guild_id)
        )
        return dict(row) if row else None

    def resolve_case(
        self,
        case_id: str,
        resolved_by: int,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Mark a case as resolved (for unmute/unban).

        Args:
            case_id: The case to resolve.
            resolved_by: User ID who resolved it.
            reason: Optional reason for resolution.

        Returns:
            True if case was resolved, False if not found or already resolved.
        """
        now = time.time()
        cursor = self.execute(
            """UPDATE cases
               SET status = 'resolved', resolved_at = ?, resolved_by = ?, resolved_reason = ?
               WHERE case_id = ? AND status = 'open'""",
            (now, resolved_by, reason, case_id)
        )

        if cursor.rowcount > 0:
            logger.tree("Case Resolved", [
                ("Case ID", case_id),
                ("Resolved By", str(resolved_by)),
            ], emoji="✅")

        return cursor.rowcount > 0

    def set_case_control_panel_message(self: "DatabaseManager", case_id: str, message_id: int) -> bool:
        """
        Set the control panel message ID for a case.

        Args:
            case_id: The case ID.
            message_id: The Discord message ID of the control panel.

        Returns:
            True if successful.
        """
        cursor = self.execute(
            "UPDATE cases SET control_panel_message_id = ? WHERE case_id = ?",
            (message_id, case_id)
        )

        if cursor.rowcount > 0:
            logger.debug("Control Panel Message Set", [
                ("Case ID", case_id),
                ("Message ID", str(message_id)),
            ])

        return cursor.rowcount > 0

    def set_case_evidence_request_message(self: "DatabaseManager", case_id: str, message_id: int) -> bool:
        """
        Set the evidence request message ID for a case.

        Args:
            case_id: The case ID.
            message_id: The Discord message ID of the evidence request.

        Returns:
            True if successful.
        """
        cursor = self.execute(
            "UPDATE cases SET evidence_request_message_id = ? WHERE case_id = ?",
            (message_id, case_id)
        )

        if cursor.rowcount > 0:
            logger.debug("Evidence Request Message Set", [
                ("Case ID", case_id),
                ("Message ID", str(message_id)),
            ])

        return cursor.rowcount > 0

    def get_case_by_evidence_request_message(self: "DatabaseManager", message_id: int) -> Optional[Dict[str, Any]]:
        """
        Get case by evidence request message ID.

        Args:
            message_id: The Discord message ID of the evidence request.

        Returns:
            Case dict or None.
        """
        row = self.fetchone(
            "SELECT * FROM cases WHERE evidence_request_message_id = ?",
            (message_id,)
        )
        return dict(row) if row else None

    def update_case_evidence(self: "DatabaseManager", case_id: str, evidence_urls: List[str]) -> bool:
        """
        Update evidence URLs for a case.

        Args:
            case_id: The case ID.
            evidence_urls: List of permanent evidence URLs.

        Returns:
            True if successful.
        """
        cursor = self.execute(
            "UPDATE cases SET evidence_urls = ?, evidence_request_message_id = NULL WHERE case_id = ?",
            (json.dumps(evidence_urls), case_id)
        )

        if cursor.rowcount > 0:
            logger.debug("Case Evidence Updated", [
                ("Case ID", case_id),
                ("URLs", str(len(evidence_urls))),
            ])

        return cursor.rowcount > 0

    def get_case_evidence(self: "DatabaseManager", case_id: str) -> List[str]:
        """
        Get evidence URLs for a case.

        Args:
            case_id: The case ID.

        Returns:
            List of evidence URLs.
        """
        row = self.fetchone(
            "SELECT evidence_urls FROM cases WHERE case_id = ?",
            (case_id,)
        )
        if row and row["evidence_urls"]:
            try:
                return json.loads(row["evidence_urls"])
            except json.JSONDecodeError:
                return []
        return []

    def get_user_cases(
        self,
        user_id: int,
        guild_id: int,
        limit: int = 25,
        include_resolved: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get all cases for a user, sorted by most recent.

        Args:
            user_id: Target user ID.
            guild_id: Guild ID.
            limit: Maximum number of cases to return.
            include_resolved: Whether to include resolved cases.

        Returns:
            List of case dicts.
        """
        if include_resolved:
            query = """SELECT * FROM cases
                       WHERE user_id = ? AND guild_id = ?
                       ORDER BY created_at DESC LIMIT ?"""
            rows = self.fetchall(query, (user_id, guild_id, limit))
        else:
            query = """SELECT * FROM cases
                       WHERE user_id = ? AND guild_id = ? AND status = 'open'
                       ORDER BY created_at DESC LIMIT ?"""
            rows = self.fetchall(query, (user_id, guild_id, limit))
        return [dict(row) for row in rows]

    def get_user_case_counts(self: "DatabaseManager", user_id: int, guild_id: int) -> Dict[str, int]:
        """
        Get case counts by action type for a user.

        Args:
            user_id: Target user ID.
            guild_id: Guild ID.

        Returns:
            Dict with mute_count, ban_count, warn_count.
        """
        row = self.fetchone(
            """SELECT
                SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mute_count,
                SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as ban_count,
                SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warn_count
               FROM cases WHERE user_id = ? AND guild_id = ?""",
            (user_id, guild_id)
        )
        return {
            "mute_count": row["mute_count"] or 0 if row else 0,
            "ban_count": row["ban_count"] or 0 if row else 0,
            "warn_count": row["warn_count"] or 0 if row else 0,
        }

    def get_old_cases_for_deletion(
        self: "DatabaseManager",
        ban_cutoff: float,
        default_cutoff: float,
    ) -> List[Dict[str, Any]]:
        """
        Get cases ready for auto-deletion based on creation time.

        Ban cases: 14 days after creation
        Other cases: 7 days after creation

        Args:
            ban_cutoff: Cutoff timestamp for ban cases.
            default_cutoff: Cutoff timestamp for other cases.

        Returns:
            List of case dicts eligible for archival.
        """
        rows = self.fetchall(
            """SELECT * FROM cases
               WHERE status != 'archived'
               AND (
                   (action_type = 'ban' AND created_at < ?)
                   OR (action_type != 'ban' AND created_at < ?)
               )
               ORDER BY created_at ASC""",
            (ban_cutoff, default_cutoff)
        )
        return [dict(row) for row in rows]

    def archive_case(self: "DatabaseManager", case_id: str) -> bool:
        """
        Mark a case as archived (thread was deleted).

        Args:
            case_id: The case ID to archive.

        Returns:
            True if case was archived, False if not found.
        """
        cursor = self.execute(
            "UPDATE cases SET status = 'archived' WHERE case_id = ?",
            (case_id,)
        )

        if cursor.rowcount > 0:
            logger.debug("Case Archived", [
                ("Case ID", case_id),
            ])

        return cursor.rowcount > 0

    def save_case_transcript(self: "DatabaseManager", case_id: str, transcript_json: str) -> bool:
        """
        Save a transcript JSON string for a case.

        Args:
            case_id: The case ID.
            transcript_json: JSON string of the transcript.

        Returns:
            True if saved successfully, False if case not found.
        """
        cursor = self.execute(
            "UPDATE cases SET transcript = ? WHERE case_id = ?",
            (transcript_json, case_id)
        )

        if cursor.rowcount > 0:
            logger.debug("Case Transcript Saved", [
                ("Case ID", case_id),
            ])

        return cursor.rowcount > 0

    def get_case_transcript(self: "DatabaseManager", case_id: str) -> Optional[str]:
        """
        Get the transcript JSON string for a case.

        Args:
            case_id: The case ID.

        Returns:
            Transcript JSON string or None if not found/no transcript.
        """
        row = self.fetchone(
            "SELECT transcript FROM cases WHERE case_id = ?",
            (case_id,)
        )
        if row and row["transcript"]:
            return row["transcript"]
        return None

    def get_most_recent_resolved_case(
        self,
        user_id: int,
        guild_id: int,
        action_type: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the most recently resolved case for a user.

        Args:
            user_id: Target user ID.
            guild_id: Guild ID.
            action_type: Type of action ('mute', 'ban', 'warn').

        Returns:
            Case dict with resolved_at, resolved_by, etc. or None.
        """
        row = self.fetchone(
            """SELECT * FROM cases
               WHERE user_id = ? AND guild_id = ? AND action_type = ?
               AND status = 'resolved'
               ORDER BY resolved_at DESC LIMIT 1""",
            (user_id, guild_id, action_type)
        )
        return dict(row) if row else None


__all__ = ["CasesMixin"]
