"""
Database Detection Operations Module
=====================================

Alt detection, user join info, and ban evasion detection operations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Optional, List, Dict, Any, Set, TYPE_CHECKING

from src.core.logger import logger
from src.core.database.models import AltLinkRecord, JoinInfoRecord

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


class DetectionMixin:
    """Mixin for alt detection and ban evasion database operations."""

    # Alt Detection Operations
    # =========================================================================

    def save_alt_link(
        self,
        banned_user_id: int,
        potential_alt_id: int,
        guild_id: int,
        confidence: str,
        total_score: int,
        signals: dict,
    ) -> int:
        """
        Save a detected alt link to the database.

        Args:
            banned_user_id: The banned user's ID.
            potential_alt_id: The potential alt account's ID.
            guild_id: The guild ID.
            confidence: Confidence level (LOW, MEDIUM, HIGH).
            total_score: Total detection score.
            signals: Dictionary of matched signals.

        Returns:
            The row ID of the inserted record.
        """
        import json
        signals_json = json.dumps(signals)
        cursor = self.execute(
            """
            INSERT OR REPLACE INTO alt_links
            (banned_user_id, potential_alt_id, guild_id, confidence, total_score, signals, detected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (banned_user_id, potential_alt_id, guild_id, confidence, total_score, signals_json, time.time())
        )

        logger.tree("Alt Link Saved", [
            ("Banned User", str(banned_user_id)),
            ("Potential Alt", str(potential_alt_id)),
            ("Confidence", confidence),
            ("Score", str(total_score)),
        ], emoji="🔗")

        return cursor.lastrowid

    def get_alt_links_for_user(self: "DatabaseManager", user_id: int, guild_id: int) -> List[Dict]:
        """
        Get all potential alts linked to a user.

        Args:
            user_id: The banned user's ID.
            guild_id: The guild ID.

        Returns:
            List of alt link records.
        """
        rows = self.fetchall(
            "SELECT * FROM alt_links WHERE banned_user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        results = []
        for row in rows:
            record = dict(row)
            record['signals'] = _safe_json_loads(record['signals'], default=[])
            results.append(record)
        return results

    def get_users_linked_to_alt(self: "DatabaseManager", alt_id: int, guild_id: int) -> List[Dict]:
        """
        Get all users that have this account flagged as an alt.

        Args:
            alt_id: The potential alt's ID.
            guild_id: The guild ID.

        Returns:
            List of alt link records.
        """
        rows = self.fetchall(
            "SELECT * FROM alt_links WHERE potential_alt_id = ? AND guild_id = ?",
            (alt_id, guild_id)
        )
        results = []
        for row in rows:
            record = dict(row)
            record['signals'] = _safe_json_loads(record['signals'], default=[])
            results.append(record)
        return results

    def mark_alt_link_reviewed(
        self,
        link_id: int,
        reviewer_id: int,
        confirmed: bool
    ) -> None:
        """
        Mark an alt link as reviewed.

        Args:
            link_id: The alt link record ID.
            reviewer_id: The moderator who reviewed it.
            confirmed: True if confirmed alt, False if false positive.
        """
        status = 1 if confirmed else 2  # 1 = confirmed, 2 = false positive
        self.execute(
            "UPDATE alt_links SET reviewed = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
            (status, reviewer_id, time.time(), link_id)
        )

        logger.debug("Alt Link Reviewed", [
            ("Link ID", str(link_id)),
            ("Reviewer", str(reviewer_id)),
            ("Confirmed", str(confirmed)),
        ])

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

    def get_users_by_inviter(self: "DatabaseManager", inviter_id: int, guild_id: int) -> List[Dict]:
        """
        Get all users invited by a specific person.

        Args:
            inviter_id: The inviter's ID.
            guild_id: The guild ID.

        Returns:
            List of user join info records.
        """
        rows = self.fetchall(
            "SELECT * FROM user_join_info WHERE inviter_id = ? AND guild_id = ?",
            (inviter_id, guild_id)
        )
        return [dict(row) for row in rows]

    def get_users_by_avatar_hash(self: "DatabaseManager", avatar_hash: str, guild_id: int) -> List[Dict]:
        """
        Get all users with a specific avatar hash.

        Args:
            avatar_hash: The avatar hash to search for.
            guild_id: The guild ID.

        Returns:
            List of user join info records.
        """
        rows = self.fetchall(
            "SELECT * FROM user_join_info WHERE avatar_hash = ? AND guild_id = ?",
            (avatar_hash, guild_id)
        )
        return [dict(row) for row in rows]


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

    def get_repeat_ban_offenders(
        self,
        guild_id: int,
        min_bans: int = 2,
        days: int = 90,
    ) -> List[Dict[str, Any]]:
        """
        Get users with multiple bans in the specified time window.

        Args:
            guild_id: Guild ID.
            min_bans: Minimum number of bans to qualify.
            days: Look back this many days.

        Returns:
            List of {user_id, ban_count, last_ban} for repeat offenders.
        """
        cutoff = time.time() - (days * 86400)
        rows = self.fetchall(
            """SELECT user_id, COUNT(*) as ban_count, MAX(timestamp) as last_ban
               FROM ban_history
               WHERE guild_id = ? AND action = 'ban' AND timestamp > ?
               GROUP BY user_id
               HAVING ban_count >= ?
               ORDER BY ban_count DESC""",
            (guild_id, cutoff, min_bans)
        )
        return [dict(row) for row in rows] if rows else []

    def get_quick_unban_patterns(
        self,
        guild_id: int,
        max_hours: int = 24,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Find suspicious patterns where users were unbanned quickly after ban.

        Args:
            guild_id: Guild ID.
            max_hours: Unban within this many hours is suspicious.
            days: Look back this many days.

        Returns:
            List of {user_id, ban_time, unban_time, hours_between}.
        """
        cutoff = time.time() - (days * 86400)
        max_seconds = max_hours * 3600

        rows = self.fetchall(
            """SELECT
                b.user_id,
                b.timestamp as ban_time,
                u.timestamp as unban_time,
                (u.timestamp - b.timestamp) / 3600.0 as hours_between,
                b.moderator_id as ban_mod,
                u.moderator_id as unban_mod
               FROM ban_history b
               INNER JOIN ban_history u ON b.user_id = u.user_id
                   AND b.guild_id = u.guild_id
                   AND u.action = 'unban'
                   AND u.timestamp > b.timestamp
                   AND u.timestamp - b.timestamp < ?
               WHERE b.guild_id = ? AND b.action = 'ban' AND b.timestamp > ?
               ORDER BY hours_between ASC""",
            (max_seconds, guild_id, cutoff)
        )
        return [dict(row) for row in rows] if rows else []

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

    def detect_voice_following(
        self,
        target_user_id: int,
        guild_id: int,
        window_minutes: int = 30,
        min_follows: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Detect if someone is following a specific user between voice channels.

        Args:
            target_user_id: The user being potentially stalked.
            guild_id: Guild ID.
            window_minutes: Time window in minutes.
            min_follows: Minimum follows to qualify.

        Returns:
            List of {follower_id, follow_count, channels} for potential stalkers.
        """
        cutoff = time.time() - (window_minutes * 60)

        # Get target's channel history
        target_channels = self.fetchall(
            """SELECT channel_id, timestamp FROM voice_activity
               WHERE user_id = ? AND guild_id = ? AND action = 'join' AND timestamp > ?
               ORDER BY timestamp""",
            (target_user_id, guild_id, cutoff)
        )

        if not target_channels:
            return []

        # Check each other user's joins within 60s of target's joins
        followers = {}
        for tc in target_channels:
            channel_id = tc["channel_id"]
            target_time = tc["timestamp"]

            # Find users who joined same channel within 60 seconds after target
            rows = self.fetchall(
                """SELECT user_id FROM voice_activity
                   WHERE guild_id = ? AND channel_id = ? AND action = 'join'
                   AND user_id != ? AND timestamp > ? AND timestamp < ?""",
                (guild_id, channel_id, target_user_id, target_time, target_time + 60)
            )

            for row in rows:
                uid = row["user_id"]
                if uid not in followers:
                    followers[uid] = {"follower_id": uid, "follow_count": 0, "channels": []}
                followers[uid]["follow_count"] += 1
                followers[uid]["channels"].append(channel_id)

        # Filter by min_follows
        return [f for f in followers.values() if f["follow_count"] >= min_follows]

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

    # =========================================================================
    # Message Samples for Alt Detection
    # =========================================================================

    def save_message_sample(
        self,
        user_id: int,
        guild_id: int,
        content: str,
        word_count: int,
        avg_word_length: float,
        emoji_count: int = 0,
        caps_ratio: float = 0.0,
    ) -> None:
        """
        Save a message sample for writing style analysis.

        Args:
            user_id: The user's ID.
            guild_id: The guild ID.
            content: Message content (truncated).
            word_count: Number of words.
            avg_word_length: Average word length.
            emoji_count: Number of emojis.
            caps_ratio: Ratio of uppercase letters.
        """
        # Keep only last 10 samples per user
        self.execute(
            """DELETE FROM message_samples
               WHERE id IN (
                   SELECT id FROM message_samples
                   WHERE user_id = ? AND guild_id = ?
                   ORDER BY recorded_at DESC
                   LIMIT -1 OFFSET 9
               )""",
            (user_id, guild_id)
        )

        self.execute(
            """INSERT INTO message_samples
               (user_id, guild_id, content, word_count, avg_word_length, emoji_count, caps_ratio, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, guild_id, content[:200], word_count, avg_word_length, emoji_count, caps_ratio, time.time())
        )

    def get_message_samples(self: "DatabaseManager", user_id: int, guild_id: int) -> List[Dict]:
        """Get message samples for a user."""
        rows = self.fetchall(
            """SELECT * FROM message_samples
               WHERE user_id = ? AND guild_id = ?
               ORDER BY recorded_at DESC LIMIT 10""",
            (user_id, guild_id)
        )
        return [dict(row) for row in rows]

    # =========================================================================
    # Activity Hours for Alt Detection
    # =========================================================================

    def increment_activity_hour(
        self,
        user_id: int,
        guild_id: int,
        hour: int,
    ) -> None:
        """
        Increment activity count for a specific hour.

        Args:
            user_id: The user's ID.
            guild_id: The guild ID.
            hour: Hour of day (0-23).
        """
        self.execute(
            """INSERT INTO user_activity_hours (user_id, guild_id, hour, message_count, last_updated)
               VALUES (?, ?, ?, 1, ?)
               ON CONFLICT(user_id, guild_id, hour)
               DO UPDATE SET message_count = message_count + 1, last_updated = ?""",
            (user_id, guild_id, hour, time.time(), time.time())
        )

    def get_activity_hours(self: "DatabaseManager", user_id: int, guild_id: int) -> Dict[int, int]:
        """
        Get activity hour distribution for a user.

        Returns:
            Dict mapping hour (0-23) to message count.
        """
        rows = self.fetchall(
            "SELECT hour, message_count FROM user_activity_hours WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return {row["hour"]: row["message_count"] for row in rows}

    # =========================================================================
    # User Interactions for Alt Detection
    # =========================================================================

    def record_interaction(
        self,
        user_id: int,
        target_id: int,
        guild_id: int,
    ) -> None:
        """
        Record an interaction (reply/mention) between two users.

        Args:
            user_id: The user who initiated interaction.
            target_id: The user being interacted with.
            guild_id: The guild ID.
        """
        self.execute(
            """INSERT INTO user_interactions (user_id, target_id, guild_id, interaction_count, last_interaction)
               VALUES (?, ?, ?, 1, ?)
               ON CONFLICT(user_id, target_id, guild_id)
               DO UPDATE SET interaction_count = interaction_count + 1, last_interaction = ?""",
            (user_id, target_id, guild_id, time.time(), time.time())
        )

    def get_interaction_count(self: "DatabaseManager", user_id: int, target_id: int, guild_id: int) -> int:
        """Get total interactions between two users (both directions)."""
        row = self.fetchone(
            """SELECT COALESCE(SUM(interaction_count), 0) as total
               FROM user_interactions
               WHERE guild_id = ? AND (
                   (user_id = ? AND target_id = ?) OR
                   (user_id = ? AND target_id = ?)
               )""",
            (guild_id, user_id, target_id, target_id, user_id)
        )
        return row["total"] if row else 0

    def get_user_total_interactions(self: "DatabaseManager", user_id: int, guild_id: int) -> int:
        """Get total interactions a user has with anyone."""
        row = self.fetchone(
            """SELECT COALESCE(SUM(interaction_count), 0) as total
               FROM user_interactions
               WHERE guild_id = ? AND (user_id = ? OR target_id = ?)""",
            (guild_id, user_id, user_id)
        )
        return row["total"] if row else 0
