"""
AzabBot - Guild Snapshots Service
=================================

Background service that captures daily guild statistics (member count, online count)
for dashboard historical charts.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

import aiohttp

from src.core.logger import logger
from src.core.config import get_config
from src.core.database import get_db
from src.utils.async_utils import create_safe_task


# TrippixnBot API for accurate online count
TRIPPIXN_API_URL = "http://localhost:8085/api/stats"


class SnapshotService:
    """
    Background service for capturing daily guild snapshots.

    Runs a check every hour and captures a snapshot once per day (after midnight UTC).
    """

    def __init__(self, bot: Any):
        self._bot = bot
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the background snapshot loop."""
        if self._running:
            logger.warning("Snapshot Service Already Running", [])
            return

        self._running = True
        self._task = create_safe_task(self._snapshot_loop(), "Snapshot Loop")

        logger.tree("Snapshot Service Started", [
            ("Interval", "1 hour"),
            ("Captures", "Daily at midnight UTC"),
        ], emoji="📸")

    async def stop(self) -> None:
        """Stop the background snapshot loop."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.tree("Snapshot Service Stopped", [], emoji="🛑")

    async def _snapshot_loop(self) -> None:
        """Background loop that checks hourly if a new snapshot is needed."""
        # Initial delay to let bot fully connect
        await asyncio.sleep(30)

        logger.debug("Snapshot Loop Running", [
            ("Check Interval", "1 hour"),
        ])

        while self._running:
            try:
                await self._check_and_snapshot()
            except Exception as e:
                logger.error("Snapshot Loop Error", [
                    ("Error Type", type(e).__name__),
                    ("Error", str(e)[:100]),
                ])

            # Wait 1 hour before next check
            await asyncio.sleep(3600)

    async def _check_and_snapshot(self) -> None:
        """Check if we need a new snapshot for today."""
        config = get_config()
        db = get_db()

        guild_id = config.ops_guild_id
        if not guild_id:
            return

        # Get today's date (UTC)
        today = datetime.utcnow().strftime("%Y-%m-%d")

        # Check if we already have a snapshot for today
        existing = db.fetchone(
            "SELECT id FROM guild_daily_snapshots WHERE guild_id = ? AND date = ?",
            (guild_id, today)
        )

        if existing:
            # Already have today's snapshot
            return

        # Capture new snapshot
        await self.capture_snapshot(guild_id, today)

    async def capture_snapshot(self, guild_id: int, date: Optional[str] = None) -> bool:
        """
        Capture a snapshot for the given guild.

        Args:
            guild_id: The Discord guild ID
            date: Optional date string (YYYY-MM-DD), defaults to today

        Returns:
            True if snapshot was captured, False otherwise
        """
        db = get_db()

        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")

        # Get member count from bot
        guild = self._bot.get_guild(guild_id)
        member_count = guild.member_count if guild else 0

        # Get online count from TrippixnBot
        online_count = 0
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    TRIPPIXN_API_URL,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        guild_data = data.get("data", {}).get("guild", {})
                        online_count = guild_data.get("online_count", 0)
                        # Also update member count if TrippixnBot has it
                        if guild_data.get("member_count"):
                            member_count = guild_data.get("member_count")
                    else:
                        logger.warning("Snapshot TrippixnBot Bad Response", [
                            ("Status", str(resp.status)),
                        ])
        except asyncio.TimeoutError:
            logger.warning("Snapshot TrippixnBot Timeout", [
                ("Timeout", "5s"),
            ])
        except Exception as e:
            logger.warning("Snapshot TrippixnBot Fetch Failed", [
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:50]),
            ])

        # Insert snapshot
        try:
            db.execute(
                """
                INSERT INTO guild_daily_snapshots (guild_id, date, member_count, online_count, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, date, member_count, online_count, datetime.utcnow().timestamp())
            )
            # Note: execute() commits by default, no separate commit needed

            logger.tree("Daily Snapshot Captured", [
                ("Date", date),
                ("Guild", str(guild_id)),
                ("Members", str(member_count)),
                ("Online", str(online_count)),
            ], emoji="📊")

            return True
        except Exception as e:
            # Likely duplicate key if snapshot already exists
            logger.warning("Snapshot Insert Failed", [
                ("Date", date),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:50]),
            ])
            return False

    def get_daily_snapshots(self, guild_id: int, days: int = 7) -> list[dict]:
        """
        Get the last N days of snapshots for a guild.

        Args:
            guild_id: The Discord guild ID
            days: Number of days to fetch

        Returns:
            List of snapshot dicts with member_count and online_count
        """
        db = get_db()

        rows = db.fetchall(
            """
            SELECT date, member_count, online_count
            FROM guild_daily_snapshots
            WHERE guild_id = ?
            ORDER BY date DESC
            LIMIT ?
            """,
            (guild_id, days)
        )

        # Reverse to get chronological order (oldest first)
        snapshots = [
            {
                "date": row[0],
                "member_count": row[1],
                "online_count": row[2],
            }
            for row in reversed(rows)
        ]

        return snapshots

    def get_daily_member_counts(self, guild_id: int, days: int = 7) -> list[int]:
        """Get list of member counts for the last N days."""
        snapshots = self.get_daily_snapshots(guild_id, days)
        return [s["member_count"] for s in snapshots]

    def get_daily_online_counts(self, guild_id: int, days: int = 7) -> list[int]:
        """Get list of online counts for the last N days."""
        snapshots = self.get_daily_snapshots(guild_id, days)
        return [s["online_count"] for s in snapshots]


# Singleton instance
_snapshot_service: Optional[SnapshotService] = None


def get_snapshot_service() -> Optional[SnapshotService]:
    """Get the snapshot service instance."""
    return _snapshot_service


def init_snapshot_service(bot: Any) -> SnapshotService:
    """Initialize the snapshot service with the bot instance."""
    global _snapshot_service
    _snapshot_service = SnapshotService(bot)
    return _snapshot_service


__all__ = [
    "SnapshotService",
    "get_snapshot_service",
    "init_snapshot_service",
]
