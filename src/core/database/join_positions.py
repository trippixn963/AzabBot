"""
AzabBot - Join Positions Mixin
==============================

Permanent historical join position tracking.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import TYPE_CHECKING, Optional, List, Tuple

if TYPE_CHECKING:
    from .manager import DatabaseManager


class JoinPositionsMixin:
    """Mixin for permanent join position tracking."""

    # =========================================================================
    # Join Position Operations
    # =========================================================================

    def get_join_position(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int
    ) -> Optional[int]:
        """
        Get a user's permanent historical join position.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.

        Returns:
            Join position number or None if not recorded.
        """
        row = self.fetchone(
            "SELECT join_position FROM member_join_positions WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        return row["join_position"] if row else None

    def record_join_position(
        self: "DatabaseManager",
        user_id: int,
        guild_id: int,
        joined_at: float
    ) -> int:
        """
        Record a new member's join position.

        Only records if this user doesn't already have a position.
        Position is permanent and survives leave/rejoin.

        Args:
            user_id: Discord user ID.
            guild_id: Guild ID.
            joined_at: Timestamp when member joined.

        Returns:
            The user's join position (existing or newly assigned).
        """
        now = time.time()

        # Check if already recorded
        existing = self.get_join_position(user_id, guild_id)
        if existing:
            return existing

        # Get and increment counter atomically
        with self.transaction() as tx:
            # Get or create counter
            tx.execute(
                """INSERT INTO guild_join_counters (guild_id, next_position)
                   VALUES (?, 1)
                   ON CONFLICT(guild_id) DO UPDATE SET next_position = next_position
                   RETURNING next_position""",
                (guild_id,)
            )
            row = tx.fetchone()
            position = row[0] if row else 1

            # Record the position
            tx.execute(
                """INSERT INTO member_join_positions (user_id, guild_id, join_position, first_joined_at, recorded_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, guild_id, position, joined_at, now)
            )

            # Increment counter for next user
            tx.execute(
                "UPDATE guild_join_counters SET next_position = next_position + 1 WHERE guild_id = ?",
                (guild_id,)
            )

        return position

    def backfill_join_positions(
        self: "DatabaseManager",
        guild_id: int,
        members: List[Tuple[int, float]]
    ) -> int:
        """
        Backfill join positions for existing members.

        Members should be sorted by joined_at ascending (oldest first).
        Only adds entries for users without existing positions.

        Args:
            guild_id: Guild ID.
            members: List of (user_id, joined_at) tuples, sorted by join time.

        Returns:
            Number of positions backfilled.
        """
        now = time.time()
        backfilled = 0

        # Get existing positions to skip
        existing_rows = self.fetchall(
            "SELECT user_id FROM member_join_positions WHERE guild_id = ?",
            (guild_id,)
        )
        existing_ids = {row["user_id"] for row in existing_rows}

        # Get current counter
        counter_row = self.fetchone(
            "SELECT next_position FROM guild_join_counters WHERE guild_id = ?",
            (guild_id,)
        )
        next_position = counter_row["next_position"] if counter_row else 1

        # Filter out existing members and assign positions
        to_insert = []
        for user_id, joined_at in members:
            if user_id in existing_ids:
                continue
            to_insert.append((user_id, guild_id, next_position, joined_at, now))
            next_position += 1
            backfilled += 1

        if to_insert:
            # Bulk insert
            self.executemany(
                """INSERT OR IGNORE INTO member_join_positions
                   (user_id, guild_id, join_position, first_joined_at, recorded_at)
                   VALUES (?, ?, ?, ?, ?)""",
                to_insert
            )

            # Update counter
            self.execute(
                """INSERT INTO guild_join_counters (guild_id, next_position)
                   VALUES (?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET next_position = ?""",
                (guild_id, next_position, next_position)
            )

        return backfilled

    def get_total_join_positions(self: "DatabaseManager", guild_id: int) -> int:
        """
        Get total number of recorded join positions for a guild.

        Args:
            guild_id: Guild ID.

        Returns:
            Total count of recorded positions.
        """
        row = self.fetchone(
            "SELECT COUNT(*) as count FROM member_join_positions WHERE guild_id = ?",
            (guild_id,)
        )
        return row["count"] if row else 0

    def get_next_join_position(self: "DatabaseManager", guild_id: int) -> int:
        """
        Get the next join position that will be assigned.

        Args:
            guild_id: Guild ID.

        Returns:
            Next position number.
        """
        row = self.fetchone(
            "SELECT next_position FROM guild_join_counters WHERE guild_id = ?",
            (guild_id,)
        )
        return row["next_position"] if row else 1


__all__ = ["JoinPositionsMixin"]
