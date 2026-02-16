"""
AzabBot - Moderation Stats
==========================

Shared moderation stats queries used by presence, API, and other services.
Single source of truth for all moderation stat calculations.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from dataclasses import dataclass
from typing import Optional

from src.core.database import get_db


@dataclass
class ModerationStats:
    """Moderation statistics from the cases table."""
    total_cases: int = 0
    total_mutes: int = 0
    total_bans: int = 0
    total_warns: int = 0
    active_prisoners: int = 0
    today_mutes: int = 0
    today_bans: int = 0
    today_warns: int = 0
    weekly_mutes: int = 0
    weekly_bans: int = 0
    weekly_warns: int = 0


def get_moderation_stats(
    today_start: Optional[float] = None,
    week_start: Optional[float] = None,
) -> ModerationStats:
    """
    Get moderation stats from the cases table.

    This is the single source of truth for all moderation statistics.
    Used by: presence handler, public API, dashboard API, etc.

    Args:
        today_start: Timestamp for today's start (for daily stats)
        week_start: Timestamp for week's start (for weekly stats)

    Returns:
        ModerationStats dataclass with all stats
    """
    db = get_db()
    now = time.time()

    row = db.fetchone(
        """
        SELECT
            COUNT(*) as total_cases,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as total_mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as total_bans,
            SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as total_warns,
            SUM(CASE WHEN action_type = 'mute' AND status = 'active'
                AND (duration_seconds IS NULL OR created_at + duration_seconds > ?)
                THEN 1 ELSE 0 END) as active_prisoners,
            SUM(CASE WHEN action_type = 'mute' AND created_at >= ? THEN 1 ELSE 0 END) as today_mutes,
            SUM(CASE WHEN action_type = 'ban' AND created_at >= ? THEN 1 ELSE 0 END) as today_bans,
            SUM(CASE WHEN action_type = 'warn' AND created_at >= ? THEN 1 ELSE 0 END) as today_warns,
            SUM(CASE WHEN action_type = 'mute' AND created_at >= ? THEN 1 ELSE 0 END) as weekly_mutes,
            SUM(CASE WHEN action_type = 'ban' AND created_at >= ? THEN 1 ELSE 0 END) as weekly_bans,
            SUM(CASE WHEN action_type = 'warn' AND created_at >= ? THEN 1 ELSE 0 END) as weekly_warns
        FROM cases
        """,
        (
            now,
            today_start or 0,
            today_start or 0,
            today_start or 0,
            week_start or 0,
            week_start or 0,
            week_start or 0,
        )
    )

    if not row:
        return ModerationStats()

    return ModerationStats(
        total_cases=row["total_cases"] or 0,
        total_mutes=row["total_mutes"] or 0,
        total_bans=row["total_bans"] or 0,
        total_warns=row["total_warns"] or 0,
        active_prisoners=row["active_prisoners"] or 0,
        today_mutes=row["today_mutes"] or 0 if today_start else 0,
        today_bans=row["today_bans"] or 0 if today_start else 0,
        today_warns=row["today_warns"] or 0 if today_start else 0,
        weekly_mutes=row["weekly_mutes"] or 0 if week_start else 0,
        weekly_bans=row["weekly_bans"] or 0 if week_start else 0,
        weekly_warns=row["weekly_warns"] or 0 if week_start else 0,
    )


def get_total_tickets(guild_id: int) -> int:
    """Get total tickets opened for a guild."""
    db = get_db()
    row = db.fetchone(
        "SELECT total_opened FROM ticket_stats WHERE guild_id = ?",
        (guild_id,)
    )
    return row["total_opened"] if row else 0


__all__ = ["ModerationStats", "get_moderation_stats", "get_total_tickets"]
