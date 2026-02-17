"""
AzabBot - Stats Service
=======================

Service for fetching stats data for both HTTP and WebSocket.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from src.core.logger import logger
from src.core.database import get_db

NY_TZ = ZoneInfo("America/New_York")


async def batch_fetch_users(bot: Any, user_ids: List[int]) -> Dict[int, tuple]:
    """Batch fetch user info from Discord."""
    from src.api.utils.discord import batch_fetch_users as _batch_fetch
    return await _batch_fetch(bot, user_ids)


def _get_previous_period_start(period: str, now: float) -> float:
    """Get the start time for the previous equivalent period."""
    period_offsets = {"day": 86400, "week": 7 * 86400, "month": 30 * 86400, "year": 365 * 86400}
    offset = period_offsets.get(period, 0)
    if offset == 0:
        return 0  # "all" has no previous period
    # Previous period starts at (now - 2*offset) and ends at (now - offset)
    return now - (2 * offset)


def _get_rankings_for_period(db: Any, start_time: float, guild_member_ids: set) -> Dict[int, int]:
    """Get mod rankings for a specific time period."""
    rows = db.fetchall(
        """
        SELECT
            moderator_id,
            (SUM(CASE WHEN action_type = 'ban' THEN 5 ELSE 0 END) +
             SUM(CASE WHEN action_type = 'kick' THEN 3 ELSE 0 END) +
             SUM(CASE WHEN action_type = 'mute' THEN 2 ELSE 0 END) +
             SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END)) as score
        FROM cases
        WHERE created_at >= ?
        GROUP BY moderator_id
        ORDER BY score DESC
        """,
        (start_time,)
    )
    # Filter by guild members and build ranking map
    filtered = [row for row in rows if row["moderator_id"] in guild_member_ids]
    return {row["moderator_id"]: idx + 1 for idx, row in enumerate(filtered)}


async def get_leaderboard_data(
    bot: Any,
    period: str = "month",
    per_page: int = 50,
) -> List[Dict[str, Any]]:
    """
    Fetch leaderboard data for WebSocket broadcast.

    Only includes moderators who are members of the ops server.
    Returns list of leaderboard entries as dicts with rank_change.
    """
    import discord

    db = get_db()
    now = time.time()

    # Get ops/staff guild - REQUIRED for member filtering and online status
    guild = None
    guild_member_ids = set()
    online_members = set()
    if bot and hasattr(bot, 'config') and bot.config.ops_guild_id:
        guild = bot.get_guild(bot.config.ops_guild_id)
        if guild:
            # Use cached members (fast) - cache is kept fresh by Discord gateway events
            for m in guild.members:
                guild_member_ids.add(m.id)
                # Check Discord presence (online, idle, dnd = online; offline = offline)
                if m.status != discord.Status.offline:
                    online_members.add(m.id)

    # If no guild, return empty (only track staff server members)
    if not guild:
        logger.warning("Leaderboard", [("Error", "Mods guild not found")])
        return []

    # Calculate time range
    period_offsets = {"day": 86400, "week": 7 * 86400, "month": 30 * 86400, "year": 365 * 86400}
    start_time = now - period_offsets.get(period, 0) if period in period_offsets else 0

    # Get previous period rankings for comparison
    prev_start = _get_previous_period_start(period, now)
    prev_rankings = {}
    if prev_start > 0:
        prev_rankings = _get_rankings_for_period(db, prev_start, guild_member_ids)

    # Get moderator stats with scoring (period-filtered)
    all_rows = db.fetchall(
        """
        SELECT
            moderator_id,
            COUNT(*) as total_actions,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
            SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns,
            SUM(CASE WHEN action_type = 'kick' THEN 1 ELSE 0 END) as kicks,
            (SUM(CASE WHEN action_type = 'ban' THEN 5 ELSE 0 END) +
             SUM(CASE WHEN action_type = 'kick' THEN 3 ELSE 0 END) +
             SUM(CASE WHEN action_type = 'mute' THEN 2 ELSE 0 END) +
             SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END)) as score
        FROM cases
        WHERE created_at >= ?
        GROUP BY moderator_id
        ORDER BY score DESC
        """,
        (start_time,)
    )

    # STRICT filter: only include mods who are currently in ops server
    # Double-check each mod with guild.get_member() for accuracy
    filtered_rows = []
    for row in all_rows:
        mod_id = row["moderator_id"]
        if mod_id in guild_member_ids and guild.get_member(mod_id) is not None:
            filtered_rows.append(row)
    all_rows = filtered_rows

    # Limit results
    page_rows = all_rows[:per_page]

    # Batch fetch moderator info
    mod_ids = [row["moderator_id"] for row in page_rows]
    user_info = await batch_fetch_users(bot, mod_ids)

    # Get tickets closed (period-filtered)
    tickets_map = {}
    if mod_ids:
        placeholders = ",".join("?" * len(mod_ids))
        ticket_rows = db.fetchall(
            f"""
            SELECT claimed_by, COUNT(*) as closed
            FROM tickets
            WHERE claimed_by IN ({placeholders})
              AND status = 'closed'
              AND closed_at >= ?
            GROUP BY claimed_by
            """,
            (*mod_ids, start_time)
        )
        tickets_map = {row["claimed_by"]: row["closed"] for row in ticket_rows}

    # Get last action time (all-time, for "last seen")
    last_action_map = {}
    if mod_ids:
        placeholders = ",".join("?" * len(mod_ids))
        last_action_rows = db.fetchall(
            f"""
            SELECT moderator_id, MAX(created_at) as last_action
            FROM cases
            WHERE moderator_id IN ({placeholders})
            GROUP BY moderator_id
            """,
            tuple(mod_ids)
        )
        last_action_map = {row["moderator_id"]: row["last_action"] for row in last_action_rows}

    # Get 7-day activity trend for sparkline (for each mod)
    activity_map = {}
    if mod_ids:
        week_ago = now - (7 * 86400)
        placeholders = ",".join("?" * len(mod_ids))
        trend_rows = db.fetchall(
            f"""
            SELECT
                moderator_id,
                strftime('%Y-%m-%d', datetime(created_at, 'unixepoch', 'localtime')) as day,
                COUNT(*) as count
            FROM cases
            WHERE moderator_id IN ({placeholders})
              AND created_at >= ?
            GROUP BY moderator_id, day
            ORDER BY day
            """,
            (*mod_ids, week_ago)
        )
        # Build activity map: mod_id -> list of daily counts
        for row in trend_rows:
            mid = row["moderator_id"]
            if mid not in activity_map:
                activity_map[mid] = []
            activity_map[mid].append({"day": row["day"], "count": row["count"]})

    # Build entries
    entries = []
    for idx, row in enumerate(page_rows, start=1):
        mod_id = row["moderator_id"]
        mod_name, mod_avatar = user_info.get(mod_id, (None, None))
        tickets_closed = tickets_map.get(mod_id, 0)
        final_score = row["score"] + (tickets_closed * 2)
        last_action_at = last_action_map.get(mod_id)

        # Use actual Discord online status
        is_online = mod_id in online_members

        # Calculate rank change (positive = moved up, negative = dropped)
        rank_change = None
        if prev_rankings:
            prev_rank = prev_rankings.get(mod_id)
            if prev_rank is None:
                rank_change = "new"  # New to leaderboard
            else:
                rank_change = prev_rank - idx  # e.g., was 5, now 3 = +2

        # Get 7-day trend data for sparkline
        trend = activity_map.get(mod_id, [])

        entries.append({
            "rank": idx,
            "rank_change": rank_change,
            "moderator": {
                "discord_id": str(mod_id),
                "username": mod_name,
                "avatar_url": mod_avatar,
                "is_online": is_online,
                "last_action_at": last_action_at,
            },
            "total_actions": row["total_actions"],
            "mutes": row["mutes"],
            "bans": row["bans"],
            "warns": row["warns"],
            "kicks": row["kicks"],
            "tickets_closed": tickets_closed,
            "score": final_score,
            "trend": trend,
        })

    return entries


async def get_moderator_stats_data(
    bot: Any,
    moderator_id: int,
) -> Dict[str, Any]:
    """
    Fetch personal stats for a moderator.

    Returns stats dict.
    """
    db = get_db()
    now = time.time()
    today_start = datetime.now(NY_TZ).replace(hour=0, minute=0, second=0).timestamp()
    week_start = today_start - (7 * 86400)
    month_start = today_start - (30 * 86400)

    # Get action stats
    action_stats = db.fetchone(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
            SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns,
            SUM(CASE WHEN action_type = 'kick' THEN 1 ELSE 0 END) as kicks,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as today,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as week,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as month
        FROM cases
        WHERE moderator_id = ?
        """,
        (today_start, week_start, month_start, moderator_id)
    )

    # Get ticket stats
    ticket_stats = db.fetchone(
        """
        SELECT
            COUNT(*) as claimed,
            SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as closed
        FROM tickets
        WHERE claimed_by = ?
        """,
        (moderator_id,)
    )

    # Get appeal stats
    appeal_stats = db.fetchone(
        """
        SELECT
            SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
            SUM(CASE WHEN status = 'denied' THEN 1 ELSE 0 END) as denied
        FROM appeals
        WHERE resolved_by = ?
        """,
        (moderator_id,)
    )

    return {
        "total_actions": action_stats[0] or 0,
        "total_mutes": action_stats[1] or 0,
        "total_bans": action_stats[2] or 0,
        "total_warns": action_stats[3] or 0,
        "total_kicks": action_stats[4] or 0,
        "tickets_claimed": ticket_stats[0] or 0,
        "tickets_closed": ticket_stats[1] or 0,
        "appeals_approved": appeal_stats[0] or 0,
        "appeals_denied": appeal_stats[1] or 0,
        "actions_today": action_stats[5] or 0,
        "actions_this_week": action_stats[6] or 0,
        "actions_this_month": action_stats[7] or 0,
    }


def get_peak_hours_data(moderator_id: Optional[int] = None, top_n: int = 24) -> List[Dict[str, int]]:
    """
    Fetch peak hours data.

    If moderator_id is None, returns server-wide peak hours.
    Returns list of {hour, count} dicts.
    """
    db = get_db()

    if moderator_id:
        # Try mod_hourly_activity first
        peak_hours = db.get_peak_hours(moderator_id, top_n)

        # Fall back to calculating from cases if no hourly data
        if not peak_hours:
            rows = db.fetchall(
                """
                SELECT
                    CAST(strftime('%H', datetime(created_at, 'unixepoch', 'localtime')) AS INTEGER) as hour,
                    COUNT(*) as cnt
                FROM cases
                WHERE moderator_id = ?
                GROUP BY hour
                ORDER BY cnt DESC
                LIMIT ?
                """,
                (moderator_id, top_n)
            )
            peak_hours = [(row["hour"], row["cnt"]) for row in rows]
    else:
        # Server-wide peak hours
        rows = db.fetchall(
            """
            SELECT hour, SUM(count) as total
            FROM mod_hourly_activity
            GROUP BY hour
            ORDER BY total DESC
            LIMIT ?
            """,
            (top_n,)
        )
        peak_hours = [(row["hour"], row["total"]) for row in rows]

    return [{"hour": hour, "count": count} for hour, count in peak_hours]


def get_activity_data(days: int = 30) -> List[Dict[str, Any]]:
    """
    Fetch activity chart data.

    Returns list of {date, cases} dicts.
    """
    db = get_db()
    now = time.time()
    start_time = now - (days * 86400)

    # Different grouping based on period
    if days <= 1:
        # Hourly for today
        rows = db.fetchall(
            """
            SELECT
                strftime('%H:00', datetime(created_at, 'unixepoch', 'localtime')) as label,
                COUNT(*) as cases
            FROM cases
            WHERE created_at >= ?
            GROUP BY label
            ORDER BY label
            """,
            (start_time,)
        )
    elif days <= 7:
        # Daily for week
        rows = db.fetchall(
            """
            SELECT
                strftime('%a', datetime(created_at, 'unixepoch', 'localtime')) as label,
                COUNT(*) as cases
            FROM cases
            WHERE created_at >= ?
            GROUP BY strftime('%Y-%m-%d', datetime(created_at, 'unixepoch', 'localtime'))
            ORDER BY created_at
            """,
            (start_time,)
        )
    else:
        # Daily for longer periods
        rows = db.fetchall(
            """
            SELECT
                strftime('%m/%d', datetime(created_at, 'unixepoch', 'localtime')) as label,
                COUNT(*) as cases
            FROM cases
            WHERE created_at >= ?
            GROUP BY strftime('%Y-%m-%d', datetime(created_at, 'unixepoch', 'localtime'))
            ORDER BY created_at
            """,
            (start_time,)
        )

    return [{"date": row["label"], "cases": row["cases"]} for row in rows]


def get_recent_actions_data(moderator_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch recent actions for a moderator.

    Returns list of action dicts with actual usernames from user_snapshots.
    """
    db = get_db()

    # Get cases with user info from snapshots
    rows = db.fetchall(
        """
        SELECT
            c.case_id,
            c.action_type,
            c.user_id,
            c.reason,
            c.created_at,
            COALESCE(s.display_name, s.username) as target_name
        FROM cases c
        LEFT JOIN user_snapshots s ON c.user_id = s.user_id
        WHERE c.moderator_id = ?
        ORDER BY c.created_at DESC
        LIMIT ?
        """,
        (moderator_id, limit)
    )

    return [{
        "case_id": row["case_id"],
        "action_type": row["action_type"],
        "target_id": str(row["user_id"]),
        "target_name": row["target_name"] or f"User {row['user_id']}",
        "reason": row["reason"] or "No reason provided",
        "created_at": datetime.fromtimestamp(row["created_at"]).isoformat(),
    } for row in rows]


__all__ = [
    "get_leaderboard_data",
    "get_moderator_stats_data",
    "get_peak_hours_data",
    "get_activity_data",
    "get_recent_actions_data",
]
