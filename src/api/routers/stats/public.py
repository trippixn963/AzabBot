"""
AzabBot - Public Stats Router
=============================

Public stats endpoints for leaderboard pages (no auth required).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from src.core.logger import logger
from src.core.config import NY_TZ
from src.api.dependencies import get_bot
from src.api.models.stats import PublicStatsResponse
from src.api.utils.discord import batch_fetch_users, format_relative_time
from src.core.database import get_db


router = APIRouter(tags=["Statistics"])


@router.get("/", response_model=PublicStatsResponse)
async def get_public_stats(
    bot: Any = Depends(get_bot),
) -> PublicStatsResponse:
    """
    Get comprehensive public stats for the leaderboard page.

    Returns bot status, moderation stats, leaderboards, and more.
    No authentication required.
    """
    db = get_db()
    now = time.time()
    today_start = datetime.now(NY_TZ).replace(hour=0, minute=0, second=0).timestamp()
    week_start = today_start - (7 * 86400)

    # Bot status
    bot_online = bot is not None and bot.is_ready() if bot else False
    bot_latency = int(bot.latency * 1000) if bot and bot_online else None
    bot_guilds = len(bot.guilds) if bot and bot_online else 0

    # Calculate uptime
    uptime_str = "0m"
    if bot and hasattr(bot, 'start_time') and bot.start_time:
        uptime_seconds = int(now - bot.start_time.timestamp())
        days, remainder = divmod(uptime_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes = remainder // 60
        if days > 0:
            uptime_str = f"{days}d {hours}h"
        elif hours > 0:
            uptime_str = f"{hours}h {minutes}m"
        else:
            uptime_str = f"{minutes}m"

    # Optimized: Single query for all case stats
    # Status values: 'active' (thread exists), 'resolved' (thread deleted/archived)
    case_stats = db.fetchone(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as total_mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as total_bans,
            SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as total_warns,
            SUM(CASE WHEN action_type = 'mute' AND created_at >= ? THEN 1 ELSE 0 END) as today_mutes,
            SUM(CASE WHEN action_type = 'ban' AND created_at >= ? THEN 1 ELSE 0 END) as today_bans,
            SUM(CASE WHEN action_type = 'warn' AND created_at >= ? THEN 1 ELSE 0 END) as today_warns,
            SUM(CASE WHEN action_type = 'mute' AND created_at >= ? THEN 1 ELSE 0 END) as weekly_mutes,
            SUM(CASE WHEN action_type = 'ban' AND created_at >= ? THEN 1 ELSE 0 END) as weekly_bans,
            SUM(CASE WHEN action_type = 'warn' AND created_at >= ? THEN 1 ELSE 0 END) as weekly_warns,
            SUM(CASE WHEN action_type = 'mute' AND status = 'active'
                AND (duration_seconds IS NULL OR created_at + duration_seconds > ?)
                THEN 1 ELSE 0 END) as active_prisoners,
            SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_cases,
            SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) as resolved_cases
        FROM cases
        """,
        (today_start, today_start, today_start, week_start, week_start, week_start, now)
    )

    total_cases = case_stats[0] or 0
    total_mutes = case_stats[1] or 0
    total_bans = case_stats[2] or 0
    total_warns = case_stats[3] or 0
    today_mutes = case_stats[4] or 0
    today_bans = case_stats[5] or 0
    today_warns = case_stats[6] or 0
    weekly_mutes = case_stats[7] or 0
    weekly_bans = case_stats[8] or 0
    weekly_warns = case_stats[9] or 0
    active_prisoners = case_stats[10] or 0
    active_cases = case_stats[11] or 0
    resolved_cases = case_stats[12] or 0

    # Optimized: Single query for appeals stats
    appeal_stats = db.fetchone(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
            SUM(CASE WHEN status = 'denied' THEN 1 ELSE 0 END) as denied
        FROM appeals
        """
    )
    total_appeals = appeal_stats[0] or 0
    pending_appeals = appeal_stats[1] or 0
    approved_appeals = appeal_stats[2] or 0
    denied_appeals = appeal_stats[3] or 0

    # Optimized: Single query for tickets stats
    ticket_stats = db.fetchone(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open,
            SUM(CASE WHEN status = 'claimed' THEN 1 ELSE 0 END) as claimed,
            SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as closed
        FROM tickets
        """
    )
    total_tickets = ticket_stats[0] or 0
    open_tickets = ticket_stats[1] or 0
    claimed_tickets = ticket_stats[2] or 0
    closed_tickets = ticket_stats[3] or 0

    # Top offenders (users with most punishments)
    offenders_rows = db.fetchall(
        """
        SELECT
            user_id,
            COUNT(*) as total,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
            SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns
        FROM cases
        GROUP BY user_id
        ORDER BY total DESC
        LIMIT 20
        """
    )

    # Moderator leaderboard
    mods_rows = db.fetchall(
        """
        SELECT
            moderator_id,
            COUNT(*) as actions,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
            SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns
        FROM cases
        GROUP BY moderator_id
        ORDER BY actions DESC
        LIMIT 20
        """
    )

    # Recent actions (last 10)
    recent_rows = db.fetchall(
        """
        SELECT case_id, action_type, user_id, moderator_id, reason, created_at
        FROM cases
        ORDER BY created_at DESC
        LIMIT 10
        """
    )

    # Repeat offenders (3+ offenses)
    repeat_rows = db.fetchall(
        """
        SELECT
            user_id,
            COUNT(*) as total,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans,
            SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns
        FROM cases
        GROUP BY user_id
        HAVING total >= 3
        ORDER BY total DESC
        LIMIT 10
        """
    )

    # Collect all user IDs we need to fetch
    all_user_ids = set()
    for row in offenders_rows:
        all_user_ids.add(row["user_id"])
    for row in mods_rows:
        all_user_ids.add(row["moderator_id"])
    for row in recent_rows:
        all_user_ids.add(row["user_id"])
        all_user_ids.add(row["moderator_id"])
    for row in repeat_rows:
        all_user_ids.add(row["user_id"])

    # Batch fetch all users
    user_info = await batch_fetch_users(bot, list(all_user_ids))

    # Build top offenders list
    top_offenders = []
    for row in offenders_rows:
        uid = row["user_id"]
        name, avatar = user_info.get(uid, (None, None))
        top_offenders.append({
            "user_id": str(uid),
            "name": name or f"User {uid}",
            "avatar": avatar,
            "total": row["total"],
            "mutes": row["mutes"],
            "bans": row["bans"],
            "warns": row["warns"],
        })

    # Build moderator leaderboard
    moderator_leaderboard = []
    for row in mods_rows:
        mod_id = row["moderator_id"]
        name, avatar = user_info.get(mod_id, (None, None))
        moderator_leaderboard.append({
            "user_id": str(mod_id),
            "name": name or f"Mod {mod_id}",
            "avatar": avatar,
            "actions": row["actions"],
            "mutes": row["mutes"],
            "bans": row["bans"],
            "warns": row["warns"],
        })

    # Build recent actions
    recent_actions = []
    for row in recent_rows:
        target_name, _ = user_info.get(row["user_id"], (None, None))
        mod_name, _ = user_info.get(row["moderator_id"], (None, None))

        recent_actions.append({
            "type": row["action_type"],
            "user": target_name or f"User {row['user_id']}",
            "user_id": str(row["user_id"]),
            "moderator": mod_name or f"Mod {row['moderator_id']}",
            "moderator_id": str(row["moderator_id"]),
            "reason": row["reason"] or "No reason provided",
            "time": format_relative_time(row["created_at"], now),
            "timestamp": row["created_at"],
        })

    # Build repeat offenders
    repeat_offenders = []
    for row in repeat_rows:
        uid = row["user_id"]
        name, avatar = user_info.get(uid, (None, None))
        repeat_offenders.append({
            "user_id": str(uid),
            "name": name or f"User {uid}",
            "avatar": avatar,
            "total": row["total"],
            "mutes": row["mutes"],
            "bans": row["bans"],
            "warns": row["warns"],
        })

    logger.tree("Public Stats Fetched", [
        ("Total Cases", str(total_cases)),
        ("Active Prisoners", str(active_prisoners)),
        ("Moderators", str(len(moderator_leaderboard))),
        ("Offenders", str(len(top_offenders))),
        ("Users Fetched", str(len(user_info))),
    ], emoji="📊")

    return PublicStatsResponse(
        bot={
            "online": bot_online,
            "latency_ms": bot_latency,
            "guilds": bot_guilds,
            "uptime": uptime_str,
        },
        moderation={
            "today": {
                "mutes": today_mutes,
                "bans": today_bans,
                "warns": today_warns,
            },
            "weekly": {
                "mutes": weekly_mutes,
                "bans": weekly_bans,
                "warns": weekly_warns,
            },
            "all_time": {
                "total_mutes": total_mutes,
                "total_bans": total_bans,
                "total_warns": total_warns,
                "total_cases": total_cases,
                "total_prisoners": active_prisoners,
            },
            "active": {
                "prisoners": active_prisoners,
                "active_cases": active_cases,
                "resolved_cases": resolved_cases,
            },
        },
        appeals={
            "pending": pending_appeals,
            "approved": approved_appeals,
            "denied": denied_appeals,
            "total": total_appeals,
        },
        tickets={
            "open": open_tickets,
            "claimed": claimed_tickets,
            "closed": closed_tickets,
            "total": total_tickets,
        },
        top_offenders=top_offenders,
        moderator_leaderboard=moderator_leaderboard,
        recent_actions=recent_actions,
        repeat_offenders=repeat_offenders,
        recent_releases=[],
        moderator_spotlight=None,
        system={
            "bot_mem_mb": 0,
            "cpu_percent": 0,
            "mem_percent": 0,
            "mem_used_gb": 0,
            "mem_total_gb": 0,
            "disk_percent": 0,
            "disk_used_gb": 0,
            "disk_total_gb": 0,
        },
        changelog=[],
        generated_at=datetime.now(NY_TZ).isoformat(),
    )


__all__ = ["router"]
