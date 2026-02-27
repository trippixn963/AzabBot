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
from src.core.config import NY_TZ, get_config, has_mod_role
from src.api.dependencies import get_bot
from src.api.models.stats import PublicStatsResponse
from src.api.utils.discord import batch_fetch_users, format_relative_time
from src.core.database import get_db
from src.utils.moderation_stats import get_moderation_stats, get_total_tickets


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

    # Get moderation stats from shared module (single source of truth)
    mod_stats = get_moderation_stats(today_start=today_start, week_start=week_start)

    total_cases = mod_stats.total_cases
    total_mutes = mod_stats.total_mutes
    total_bans = mod_stats.total_bans
    total_warns = mod_stats.total_warns
    today_mutes = mod_stats.today_mutes
    today_bans = mod_stats.today_bans
    today_warns = mod_stats.today_warns
    weekly_mutes = mod_stats.weekly_mutes
    weekly_bans = mod_stats.weekly_bans
    weekly_warns = mod_stats.weekly_warns
    active_prisoners = mod_stats.active_prisoners

    # Active/resolved cases (still need separate query for these)
    case_status_row = db.fetchone(
        """
        SELECT
            SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_cases,
            SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) as resolved_cases
        FROM cases
        """
    )
    active_cases = case_status_row[0] or 0 if case_status_row else 0
    resolved_cases = case_status_row[1] or 0 if case_status_row else 0

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

    # Optimized: Single query for current tickets stats
    ticket_stats = db.fetchone(
        """
        SELECT
            SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open,
            SUM(CASE WHEN status = 'claimed' THEN 1 ELSE 0 END) as claimed,
            SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as closed
        FROM tickets
        """
    )
    open_tickets = ticket_stats[0] or 0
    claimed_tickets = ticket_stats[1] or 0
    closed_tickets = ticket_stats[2] or 0

    # Use shared function for total tickets
    config = get_config()
    total_tickets = get_total_tickets(config.main_guild_id) if config.main_guild_id else 0

    # Calculate total prison time (filter out bad data > 1 year)
    prison_time_stats = db.fetchone(
        """
        SELECT
            COUNT(*) as total_sentences,
            COALESCE(SUM(CASE WHEN duration_seconds < 31536000 THEN duration_seconds ELSE 0 END), 0) as total_seconds
        FROM mute_history
        WHERE duration_seconds IS NOT NULL
        """
    )
    total_sentences = prison_time_stats[0] or 0
    total_prison_seconds = int(prison_time_stats[1] or 0)
    total_prison_hours = total_prison_seconds // 3600

    # Calculate total XP drained (from actual recorded drains)
    xp_drain_result = db.fetchone(
        """SELECT COALESCE(SUM(xp_drained), 0) FROM mute_history WHERE xp_drained > 0"""
    )
    total_xp_drained = int(xp_drain_result[0] or 0)

    # Owner personal stats
    owner_id = 259725211664908288
    owner_ticket_stats = db.get_staff_ticket_stats(owner_id, config.main_guild_id) if config.main_guild_id else {}
    owner_tickets_claimed = owner_ticket_stats.get("claimed", 0)
    owner_tickets_closed = owner_ticket_stats.get("closed", 0)

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

    # Get current mod IDs from main guild
    current_mod_ids = set()
    main_guild = None
    if bot and hasattr(bot, 'config') and bot.config.main_guild_id:
        main_guild = bot.get_guild(bot.config.main_guild_id)
        if main_guild:
            for m in main_guild.members:
                if has_mod_role(m):
                    current_mod_ids.add(m.id)

    # Moderator leaderboard (all, then filter by current mods)
    all_mods_rows = db.fetchall(
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
        """
    )

    # Filter to only current mods
    mods_rows = [row for row in all_mods_rows if row["moderator_id"] in current_mod_ids][:20]

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
        prison_time={
            "total_sentences": total_sentences,
            "total_hours": total_prison_hours,
            "total_seconds": total_prison_seconds,
            "total_xp_drained": total_xp_drained,
        },
        owner={
            "tickets_claimed": owner_tickets_claimed,
            "tickets_closed": owner_tickets_closed,
        },
        generated_at=datetime.now(NY_TZ).isoformat(),
    )


__all__ = ["router"]
