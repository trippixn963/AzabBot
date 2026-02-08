"""
AzabBot - Database Detection Operations Module
==============================================

Alt detection, user join info, and ban evasion detection operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from src.core.logger import logger
from src.core.database.models import JoinInfoRecord

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


class DetectionMixin:
    """Mixin for ban evasion detection database operations."""

    # =========================================================================
    # User Join Info Operations
    # =========================================================================

    def save_user_join_info(
        self,
        user_id: int,
        guild_id: int,
        invite_code: Optional[str],
        inviter_id: Optional[int],
        joined_at: float,
        avatar_hash: Optional[str],
    ) -> None:
        """
        Save user join information for alt detection.

        Args:
            user_id: The user's ID.
            guild_id: The guild ID.
            invite_code: The invite code used (if known).
            inviter_id: The inviter's ID (if known).
            joined_at: Timestamp of when they joined.
            avatar_hash: Hash of their avatar (if any).
        """
        self.execute(
            """
            INSERT OR REPLACE INTO user_join_info
            (user_id, guild_id, invite_code, inviter_id, joined_at, avatar_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, guild_id, invite_code, inviter_id, joined_at, avatar_hash)
        )

        logger.debug("User Join Info Saved", [
            ("User ID", str(user_id)),
            ("Invite", invite_code or "Unknown"),
        ])

    def get_user_join_info(self: "DatabaseManager", user_id: int, guild_id: int) -> Optional[Dict]:
        """
        Get join information for a user.

        Args:
            user_id: The user's ID.
            guild_id: The guild ID.

        Returns:
            Join info dict or None.
        """
        row = self.fetchone(
            "SELECT * FROM user_join_info WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return dict(row) if row else None

    # =========================================================================
    # Mod Notes Operations
    # =========================================================================

    def save_mod_note(
        self,
        user_id: int,
        guild_id: int,
        moderator_id: int,
        note: str,
        case_id: Optional[str] = None,
    ) -> int:
        """
        Save a moderator note about a user.

        Args:
            user_id: Discord user ID the note is about.
            guild_id: Guild ID.
            moderator_id: Moderator who created the note.
            note: The note text.
            case_id: Optional case ID to link this note to.

        Returns:
            The row ID of the inserted note.
        """
        now = time.time()
        cursor = self.execute(
            """INSERT INTO mod_notes
               (user_id, guild_id, moderator_id, note, created_at, case_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, guild_id, moderator_id, note, now, case_id)
        )

        logger.tree("MOD NOTE SAVED", [
            ("User ID", str(user_id)),
            ("Moderator ID", str(moderator_id)),
            ("Case ID", case_id or "N/A"),
            ("Note", (note[:40] + "...") if len(note) > 40 else note),
        ], emoji="📝")

        return cursor.lastrowid

    def get_mod_notes(
        self,
        user_id: int,
        guild_id: int,
        limit: int = 20,
        case_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get moderator notes for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum records to return.
            case_id: Optional case ID to filter by.

        Returns:
            List of note records, newest first.
        """
        if case_id:
            rows = self.fetchall(
                """SELECT * FROM mod_notes
                   WHERE user_id = ? AND guild_id = ? AND case_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (user_id, guild_id, case_id, limit)
            )
        else:
            rows = self.fetchall(
                """SELECT * FROM mod_notes
                   WHERE user_id = ? AND guild_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (user_id, guild_id, limit)
            )
        return [dict(row) for row in rows]

    def get_note_count(self: "DatabaseManager", user_id: int, guild_id: int) -> int:
        """
        Get total note count for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Total note count.
        """
        row = self.fetchone(
            "SELECT COUNT(*) as count FROM mod_notes WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return row["count"] if row else 0

    # =========================================================================
    # Ban History Operations
    # =========================================================================

    def add_ban(
        self,
        user_id: int,
        guild_id: int,
        moderator_id: int,
        reason: Optional[str] = None,
    ) -> int:
        """
        Add a ban record to history.

        Args:
            user_id: Discord user ID being banned.
            guild_id: Guild ID.
            moderator_id: Moderator who issued the ban.
            reason: Optional reason for ban.

        Returns:
            Row ID of the ban record.
        """
        now = time.time()
        cursor = self.execute(
            """INSERT INTO ban_history
               (user_id, guild_id, moderator_id, action, reason, timestamp)
               VALUES (?, ?, ?, 'ban', ?, ?)""",
            (user_id, guild_id, moderator_id, reason, now)
        )

        logger.tree("Ban Recorded", [
            ("User ID", str(user_id)),
            ("Moderator", str(moderator_id)),
            ("Reason", (reason or "None")[:40]),
        ], emoji="🔨")

        return cursor.lastrowid

    def add_unban(
        self,
        user_id: int,
        guild_id: int,
        moderator_id: int,
        reason: Optional[str] = None,
    ) -> int:
        """
        Add an unban record to history.

        Args:
            user_id: Discord user ID being unbanned.
            guild_id: Guild ID.
            moderator_id: Moderator who issued the unban.
            reason: Optional reason for unban.

        Returns:
            Row ID of the unban record.
        """
        now = time.time()
        cursor = self.execute(
            """INSERT INTO ban_history
               (user_id, guild_id, moderator_id, action, reason, timestamp)
               VALUES (?, ?, ?, 'unban', ?, ?)""",
            (user_id, guild_id, moderator_id, reason, now)
        )

        logger.tree("Unban Recorded", [
            ("User ID", str(user_id)),
            ("Moderator", str(moderator_id)),
            ("Reason", (reason or "None")[:40]),
        ], emoji="🔓")

        return cursor.lastrowid

    def get_ban_history(
        self,
        user_id: int,
        guild_id: int,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get ban history for a user.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            limit: Maximum records to return.

        Returns:
            List of ban history records, newest first.
        """
        rows = self.fetchall(
            """SELECT * FROM ban_history
               WHERE user_id = ? AND guild_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (user_id, guild_id, limit)
        )
        return [dict(row) for row in rows]

    # =========================================================================
    # Voice Activity Pattern Detection
    # =========================================================================

    def detect_voice_channel_hopping(
        self,
        guild_id: int,
        window_minutes: int = 5,
        min_channels: int = 4,
    ) -> List[Dict[str, Any]]:
        """
        Detect users rapidly switching between voice channels.

        Args:
            guild_id: Guild ID.
            window_minutes: Time window in minutes.
            min_channels: Minimum unique channels to qualify as hopping.

        Returns:
            List of {user_id, channel_count, actions} for channel hoppers.
        """
        cutoff = time.time() - (window_minutes * 60)

        rows = self.fetchall(
            """SELECT user_id, COUNT(DISTINCT channel_id) as channel_count,
                      COUNT(*) as action_count
               FROM voice_activity
               WHERE guild_id = ? AND timestamp > ? AND action = 'join'
               GROUP BY user_id
               HAVING channel_count >= ?
               ORDER BY channel_count DESC""",
            (guild_id, cutoff, min_channels)
        )
        return [dict(row) for row in rows] if rows else []

    # =========================================================================
    # Username Cross-Reference for Ban Evasion
    # =========================================================================

    def find_banned_user_matches(
        self,
        guild_id: int,
        similarity_threshold: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """
        Find current members with usernames similar to banned users.

        Args:
            guild_id: Guild ID.
            similarity_threshold: Minimum similarity score (0-1).

        Returns:
            List of {current_user_id, current_name, banned_user_id, banned_name, similarity}.
        """
        # Get all unique banned user IDs
        banned_rows = self.fetchall(
            """SELECT DISTINCT user_id FROM ban_history
               WHERE guild_id = ? AND action = 'ban'""",
            (guild_id,)
        )
        banned_ids = {row["user_id"] for row in banned_rows}

        if not banned_ids:
            return []

        # Get username history for banned users
        banned_names = {}
        for uid in banned_ids:
            rows = self.fetchall(
                """SELECT username, display_name FROM username_history
                   WHERE user_id = ? ORDER BY changed_at DESC LIMIT 5""",
                (uid,)
            )
            for row in rows:
                if row["username"]:
                    banned_names[row["username"].lower()] = uid
                if row["display_name"]:
                    banned_names[row["display_name"].lower()] = uid

        # Get recent username changes (potential evaders)
        recent_names = self.fetchall(
            """SELECT user_id, username, display_name FROM username_history
               WHERE guild_id = ? AND user_id NOT IN ({})
               AND changed_at > ?
               ORDER BY changed_at DESC""".format(",".join("?" * len(banned_ids))),
            (guild_id, *banned_ids, time.time() - 86400 * 7)  # Last 7 days
        )

        matches = []
        for row in recent_names:
            current_id = row["user_id"]
            for name_field in ["username", "display_name"]:
                current_name = row[name_field]
                if not current_name:
                    continue
                current_lower = current_name.lower()

                for banned_name, banned_id in banned_names.items():
                    similarity = self._calculate_name_similarity(current_lower, banned_name)
                    if similarity >= similarity_threshold:
                        matches.append({
                            "current_user_id": current_id,
                            "current_name": current_name,
                            "banned_user_id": banned_id,
                            "banned_name": banned_name,
                            "similarity": similarity,
                        })

        return matches

    def _calculate_name_similarity(self: "DatabaseManager", name1: str, name2: str) -> float:
        """Calculate similarity between two names (0-1)."""
        if name1 == name2:
            return 1.0

        # Exact substring match
        if name1 in name2 or name2 in name1:
            return 0.9

        # Character-based similarity (Jaccard)
        set1 = set(name1.replace(" ", ""))
        set2 = set(name2.replace(" ", ""))
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["DetectionMixin"]
