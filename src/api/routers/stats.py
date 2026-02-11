"""
AzabBot - Stats Router
======================

Dashboard statistics and analytics endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from datetime import datetime, timedelta
from typing import Any, List

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from src.core.logger import logger
from src.core.config import NY_TZ
from src.api.dependencies import get_bot, require_auth, get_pagination, PaginationParams
from src.api.models.base import APIResponse, PaginatedResponse
from src.api.models.stats import (
    DashboardStats,
    ModeratorStats,
    LeaderboardEntry,
    ActivityChartData,
    ServerInfo,
)
from src.api.models.base import ModeratorBrief
from src.api.models.auth import TokenPayload
from src.api.utils.pagination import create_paginated_response
from src.api.utils.discord import (
    batch_fetch_users,
    format_relative_time,
)
from src.core.database import get_db


router = APIRouter(prefix="/stats", tags=["Statistics"])


# =============================================================================
# Root Stats (Public comprehensive stats for dashboard/leaderboard)
# =============================================================================

@router.get("")
async def get_public_stats(
    bot: Any = Depends(get_bot),
) -> JSONResponse:
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

    # Build response
    response = {
        "bot": {
            "online": bot_online,
            "latency_ms": bot_latency,
            "guilds": bot_guilds,
            "uptime": uptime_str,
        },
        "moderation": {
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
        "appeals": {
            "pending": pending_appeals,
            "approved": approved_appeals,
            "denied": denied_appeals,
            "total": total_appeals,
        },
        "tickets": {
            "open": open_tickets,
            "claimed": claimed_tickets,
            "closed": closed_tickets,
            "total": total_tickets,
        },
        "top_offenders": top_offenders,
        "moderator_leaderboard": moderator_leaderboard,
        "recent_actions": recent_actions,
        "repeat_offenders": repeat_offenders,
        "recent_releases": [],
        "moderator_spotlight": None,
        "system": {
            "bot_mem_mb": 0,
            "cpu_percent": 0,
            "mem_percent": 0,
            "mem_used_gb": 0,
            "mem_total_gb": 0,
            "disk_percent": 0,
            "disk_used_gb": 0,
            "disk_total_gb": 0,
        },
        "changelog": [],
        "generated_at": datetime.now(NY_TZ).isoformat(),
    }

    logger.tree("Public Stats Fetched", [
        ("Total Cases", str(total_cases)),
        ("Active Prisoners", str(active_prisoners)),
        ("Moderators", str(len(moderator_leaderboard))),
        ("Offenders", str(len(top_offenders))),
        ("Users Fetched", str(len(user_info))),
    ], emoji="📊")

    return JSONResponse(content=response)


# =============================================================================
# Dashboard Overview
# =============================================================================

@router.get("/dashboard", response_model=APIResponse[DashboardStats])
async def get_dashboard_stats(
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[DashboardStats]:
    """
    Get main dashboard statistics.

    Includes member counts, case totals, ticket status, and trends.
    """
    db = get_db()
    now = time.time()
    today_start = datetime.now(NY_TZ).replace(hour=0, minute=0, second=0).timestamp()
    yesterday_start = today_start - 86400

    # Get guild info
    guild = None
    if bot and hasattr(bot, 'config') and bot.config.ops_guild_id:
        guild = bot.get_guild(bot.config.ops_guild_id)

    total_members = guild.member_count if guild else 0
    online_members = sum(1 for m in guild.members if m.status.value != "offline") if guild else 0

    # Optimized: Single query for case stats
    case_stats = db.fetchone(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN action_type = 'mute' AND status = 'active'
                AND (duration_seconds IS NULL OR created_at + duration_seconds > ?)
                THEN 1 ELSE 0 END) as active_mutes,
            SUM(CASE WHEN action_type = 'ban' AND status = 'active'
                THEN 1 ELSE 0 END) as active_bans,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as cases_today,
            SUM(CASE WHEN created_at >= ? AND created_at < ?
                THEN 1 ELSE 0 END) as cases_yesterday
        FROM cases
        """,
        (now, today_start, yesterday_start, today_start)
    )
    total_cases = case_stats[0] or 0
    active_mutes = case_stats[1] or 0
    active_bans = case_stats[2] or 0
    cases_today = case_stats[3] or 0
    cases_yesterday = case_stats[4] or 0

    # Optimized: Single query for ticket stats
    ticket_stats = db.fetchone(
        """
        SELECT
            SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open,
            SUM(CASE WHEN status = 'claimed' THEN 1 ELSE 0 END) as claimed,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as today,
            SUM(CASE WHEN created_at >= ? AND created_at < ? THEN 1 ELSE 0 END) as yesterday,
            AVG(CASE WHEN claimed_at IS NOT NULL THEN (claimed_at - created_at) / 60.0 END) as avg_response
        FROM tickets
        """,
        (today_start, yesterday_start, today_start)
    )
    open_tickets = ticket_stats[0] or 0
    claimed_tickets = ticket_stats[1] or 0
    tickets_today = ticket_stats[2] or 0
    tickets_yesterday = ticket_stats[3] or 0
    avg_response = ticket_stats[4]

    # Pending appeals and today's appeals
    appeal_stats = db.fetchone(
        """
        SELECT
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as today
        FROM appeals
        """,
        (today_start,)
    )
    pending_appeals = appeal_stats[0] or 0
    appeals_today = appeal_stats[1] or 0

    # Calculate trends
    cases_trend = None
    if cases_yesterday > 0:
        cases_trend = ((cases_today - cases_yesterday) / cases_yesterday) * 100

    tickets_trend = None
    if tickets_yesterday > 0:
        tickets_trend = ((tickets_today - tickets_yesterday) / tickets_yesterday) * 100

    stats = DashboardStats(
        total_members=total_members,
        online_members=online_members,
        total_cases=total_cases,
        active_mutes=active_mutes,
        active_bans=active_bans,
        open_tickets=open_tickets,
        claimed_tickets=claimed_tickets,
        avg_response_time_minutes=round(avg_response, 1) if avg_response else None,
        pending_appeals=pending_appeals,
        cases_today=cases_today,
        tickets_today=tickets_today,
        appeals_today=appeals_today,
        cases_trend=round(cases_trend, 1) if cases_trend is not None else None,
        tickets_trend=round(tickets_trend, 1) if tickets_trend is not None else None,
    )

    logger.debug("Dashboard Stats Fetched", [
        ("User", str(payload.sub)),
        ("Members", str(total_members)),
        ("Cases", str(total_cases)),
        ("Open Tickets", str(open_tickets)),
        ("Pending Appeals", str(pending_appeals)),
    ])

    return APIResponse(success=True, data=stats)


# =============================================================================
# Moderator Stats
# =============================================================================

@router.get("/moderators/{moderator_id}", response_model=APIResponse[ModeratorStats])
async def get_moderator_stats(
    moderator_id: int,
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[ModeratorStats]:
    """
    Get statistics for a specific moderator.
    """
    db = get_db()
    now = time.time()
    today_start = datetime.now(NY_TZ).replace(hour=0, minute=0, second=0).timestamp()
    week_start = today_start - (7 * 86400)
    month_start = today_start - (30 * 86400)

    # Get moderator info
    user_info = await batch_fetch_users(bot, [moderator_id])
    mod_name, mod_avatar = user_info.get(moderator_id, (None, None))

    moderator = ModeratorBrief(
        discord_id=moderator_id,
        username=mod_name,
        avatar_url=mod_avatar,
    )

    # Optimized: Single query for action counts and time periods
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
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as month,
            MAX(created_at) as last_action
        FROM cases
        WHERE moderator_id = ?
        """,
        (today_start, week_start, month_start, moderator_id)
    )

    # Optimized: Single query for ticket stats
    ticket_stats = db.fetchone(
        """
        SELECT
            COUNT(*) as claimed,
            SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as closed,
            AVG(CASE WHEN closed_at IS NOT NULL THEN (closed_at - claimed_at) / 60.0 END) as avg_resolution
        FROM tickets
        WHERE claimed_by = ?
        """,
        (moderator_id,)
    )

    # Optimized: Single query for appeal stats
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

    last_action_at = datetime.fromtimestamp(action_stats[8]) if action_stats[8] else None

    stats = ModeratorStats(
        moderator=moderator,
        total_actions=action_stats[0] or 0,
        total_mutes=action_stats[1] or 0,
        total_bans=action_stats[2] or 0,
        total_warns=action_stats[3] or 0,
        total_kicks=action_stats[4] or 0,
        tickets_claimed=ticket_stats[0] or 0,
        tickets_closed=ticket_stats[1] or 0,
        avg_ticket_resolution_minutes=round(ticket_stats[2], 1) if ticket_stats[2] else None,
        appeals_approved=appeal_stats[0] or 0,
        appeals_denied=appeal_stats[1] or 0,
        actions_today=action_stats[5] or 0,
        actions_this_week=action_stats[6] or 0,
        actions_this_month=action_stats[7] or 0,
        last_action_at=last_action_at,
    )

    logger.debug("Moderator Stats Fetched", [
        ("Moderator ID", str(moderator_id)),
        ("Requested By", str(payload.sub)),
        ("Total Actions", str(stats.total_actions)),
        ("Tickets Closed", str(stats.tickets_closed)),
    ])

    return APIResponse(success=True, data=stats)


# =============================================================================
# Leaderboard
# =============================================================================

@router.get("/leaderboard", response_model=PaginatedResponse[LeaderboardEntry])
async def get_leaderboard(
    period: str = Query("month", description="Time period: week, month, year, all"),
    pagination: PaginationParams = Depends(get_pagination),
    bot: Any = Depends(get_bot),
) -> PaginatedResponse[LeaderboardEntry]:
    """
    Get moderator leaderboard rankings (public endpoint).

    Ranked by weighted score of moderation actions.
    """
    db = get_db()
    now = time.time()

    # Calculate time range
    period_offsets = {"week": 7 * 86400, "month": 30 * 86400, "year": 365 * 86400}
    start_time = now - period_offsets.get(period, 0) if period in period_offsets else 0

    # Get moderator stats with scoring
    # Weights: ban=5, kick=3, mute=2, warn=1
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

    total = len(all_rows)

    # Paginate
    start_idx = pagination.offset
    end_idx = start_idx + pagination.per_page
    page_rows = all_rows[start_idx:end_idx]

    # Batch fetch moderator info
    mod_ids = [row["moderator_id"] for row in page_rows]
    user_info = await batch_fetch_users(bot, mod_ids)

    # Get tickets closed for all mods on this page in a single query
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
    else:
        tickets_map = {}

    # Build entries
    entries = []
    for idx, row in enumerate(page_rows, start=start_idx + 1):
        mod_id = row["moderator_id"]
        mod_name, mod_avatar = user_info.get(mod_id, (None, None))
        tickets_closed = tickets_map.get(mod_id, 0)

        # Add ticket score (2 points per ticket)
        final_score = row["score"] + (tickets_closed * 2)

        entries.append(LeaderboardEntry(
            rank=idx,
            moderator=ModeratorBrief(
                discord_id=mod_id,
                username=mod_name,
                avatar_url=mod_avatar,
            ),
            total_actions=row["total_actions"],
            mutes=row["mutes"],
            bans=row["bans"],
            tickets_closed=tickets_closed,
            score=final_score,
        ))

    logger.debug("Leaderboard Fetched", [
        ("Period", period),
        ("Page", str(pagination.page)),
        ("Results", str(len(entries))),
        ("Total", str(total)),
    ])

    return create_paginated_response(entries, total, pagination)


# =============================================================================
# Public User Summary (for leaderboard user cards)
# =============================================================================

@router.get("/user/{user_id}")
async def get_public_user_summary(
    user_id: int,
    bot: Any = Depends(get_bot),
) -> JSONResponse:
    """
    Get public user summary for leaderboard user cards.

    Returns basic info, case stats, and moderation status.
    No authentication required.
    """
    db = get_db()
    config = None
    try:
        from src.core.config import get_config
        config = get_config()
    except Exception:
        pass

    now = time.time()
    user = None
    member = None

    # Try to fetch user from Discord
    try:
        user = await bot.fetch_user(user_id)
    except Exception:
        pass

    # Try to get member from guild
    guild_id = config.ops_guild_id if config else None
    if user and guild_id:
        guild = bot.get_guild(guild_id)
        if guild:
            member = guild.get_member(user_id)

    # Get case stats
    stats = db.fetchone(
        """
        SELECT
            COUNT(*) as total_cases,
            SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as total_warns,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as total_mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as total_bans,
            MIN(created_at) as first_case,
            MAX(created_at) as last_case
        FROM cases
        WHERE user_id = ?
        """,
        (user_id,)
    )

    total_cases = stats[0] or 0
    total_warns = stats[1] or 0
    total_mutes = stats[2] or 0
    total_bans = stats[3] or 0
    first_case_at = stats[4]
    last_case_at = stats[5]

    # Check for active mute
    active_mute = db.fetchone(
        """
        SELECT expires_at FROM active_mutes
        WHERE user_id = ? AND unmuted = 0
        AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY muted_at DESC LIMIT 1
        """,
        (user_id, now)
    )
    is_muted = active_mute is not None
    mute_expires_at = None
    if active_mute and active_mute[0]:
        mute_expires_at = datetime.utcfromtimestamp(active_mute[0]).isoformat() + "Z"

    # Check for active ban
    is_banned = False
    if guild_id:
        guild = bot.get_guild(guild_id)
        if guild:
            try:
                import discord
                ban_entry = await guild.fetch_ban(discord.Object(id=user_id))
                is_banned = ban_entry is not None
            except Exception:
                pass

    # Get recent cases (last 5)
    recent_rows = db.fetchall(
        """
        SELECT case_id, action_type, reason, moderator_id, created_at
        FROM cases
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 5
        """,
        (user_id,)
    )

    # Batch fetch moderator names
    mod_ids = [row["moderator_id"] for row in recent_rows if row["moderator_id"]]
    mod_info = await batch_fetch_users(bot, mod_ids)

    recent_cases = []
    for row in recent_rows:
        mod_name, _ = mod_info.get(row["moderator_id"], (None, None))
        recent_cases.append({
            "case_id": row["case_id"],
            "type": row["action_type"],
            "reason": (row["reason"][:80] + "...") if row["reason"] and len(row["reason"]) > 80 else row["reason"],
            "moderator": mod_name or f"Mod {row['moderator_id']}",
            "time": format_relative_time(row["created_at"], now),
        })

    # Build response
    response = {
        "user_id": str(user_id),
        "username": user.name if user else f"User {user_id}",
        "display_name": user.display_name if user else None,
        "avatar_url": str(user.display_avatar.url) if user and user.display_avatar else None,
        "in_server": member is not None,

        # Account info
        "account_created_at": user.created_at.isoformat() + "Z" if user and user.created_at else None,
        "joined_server_at": member.joined_at.isoformat() + "Z" if member and member.joined_at else None,
        "account_age_days": (datetime.now(NY_TZ) - user.created_at.replace(tzinfo=None)).days if user and user.created_at else 0,
        "server_tenure_days": (datetime.now(NY_TZ) - member.joined_at.replace(tzinfo=None)).days if member and member.joined_at else 0,

        # Moderation status
        "is_muted": is_muted,
        "is_banned": is_banned,
        "mute_expires_at": mute_expires_at,

        # Case stats
        "total_cases": total_cases,
        "total_warns": total_warns,
        "total_mutes": total_mutes,
        "total_bans": total_bans,
        "first_case_at": datetime.utcfromtimestamp(first_case_at).isoformat() + "Z" if first_case_at else None,
        "last_case_at": datetime.utcfromtimestamp(last_case_at).isoformat() + "Z" if last_case_at else None,

        # Recent history
        "recent_cases": recent_cases,
    }

    logger.debug("Public User Summary Fetched", [
        ("User ID", str(user_id)),
        ("Username", response["username"]),
        ("Cases", str(total_cases)),
        ("In Server", str(member is not None)),
    ])

    return JSONResponse(content=response)


# =============================================================================
# Activity Charts
# =============================================================================

@router.get("/activity", response_model=APIResponse[List[ActivityChartData]])
async def get_activity_chart(
    days: int = Query(7, ge=1, le=90, description="Number of days to include"),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[List[ActivityChartData]]:
    """
    Get daily activity data for charts.

    Returns data points for each day in the specified range.
    Uses optimized queries to avoid N+1 problem.
    """
    db = get_db()
    now = datetime.now(NY_TZ)
    start_date = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_ts = start_date.timestamp()

    # Optimized: Get all case counts in single query
    case_rows = db.fetchall(
        """
        SELECT
            CAST((created_at - ?) / 86400 AS INTEGER) as day_index,
            COUNT(*) as total,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans
        FROM cases
        WHERE created_at >= ?
        GROUP BY day_index
        """,
        (start_ts, start_ts)
    )
    case_data = {int(row[0]): {"total": row[1], "mutes": row[2], "bans": row[3]} for row in case_rows}

    # Optimized: Get all ticket counts in single query
    ticket_rows = db.fetchall(
        """
        SELECT
            CAST((created_at - ?) / 86400 AS INTEGER) as day_index,
            COUNT(*) as total
        FROM tickets
        WHERE created_at >= ?
        GROUP BY day_index
        """,
        (start_ts, start_ts)
    )
    ticket_data = {int(row[0]): row[1] for row in ticket_rows}

    # Optimized: Get all appeal counts in single query
    appeal_rows = db.fetchall(
        """
        SELECT
            CAST((created_at - ?) / 86400 AS INTEGER) as day_index,
            COUNT(*) as total
        FROM appeals
        WHERE created_at >= ?
        GROUP BY day_index
        """,
        (start_ts, start_ts)
    )
    appeal_data = {int(row[0]): row[1] for row in appeal_rows}

    # Build activity data
    data = []
    for i in range(days):
        day = now - timedelta(days=days - 1 - i)
        case_info = case_data.get(i, {"total": 0, "mutes": 0, "bans": 0})

        # Format label based on range
        if days <= 7:
            label = day.strftime("%a")  # Mon, Tue, etc.
        else:
            label = day.strftime("%b %d")  # Jan 1, Jan 2, etc.

        data.append(ActivityChartData(
            timestamp=day,
            label=label,
            cases=case_info["total"],
            tickets=ticket_data.get(i, 0),
            appeals=appeal_data.get(i, 0),
            mutes=case_info["mutes"],
            bans=case_info["bans"],
        ))

    logger.debug("Activity Chart Fetched", [
        ("User", str(payload.sub)),
        ("Days", str(days)),
        ("Data Points", str(len(data))),
    ])

    return APIResponse(success=True, data=data)


# =============================================================================
# Server Info
# =============================================================================

@router.get("/server", response_model=APIResponse[ServerInfo])
async def get_server_info(
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[ServerInfo]:
    """
    Get Discord server information.
    """
    guild = None
    if bot and hasattr(bot, 'config') and bot.config.ops_guild_id:
        guild = bot.get_guild(bot.config.ops_guild_id)

    if not guild:
        logger.warning("Server Info Failed", [
            ("User", str(payload.sub)),
            ("Reason", "Guild not found"),
        ])
        return APIResponse(
            success=False,
            message="Guild not found",
            data=ServerInfo(guild_id=0, name="Unknown"),
        )

    # Count channel types
    text_channels = sum(1 for c in guild.channels if hasattr(c, 'send'))
    voice_channels = sum(1 for c in guild.channels if hasattr(c, 'connect'))

    info = ServerInfo(
        guild_id=guild.id,
        name=guild.name,
        icon_url=str(guild.icon.url) if guild.icon else None,
        member_count=guild.member_count,
        online_count=sum(1 for m in guild.members if m.status.value != "offline"),
        bot_latency_ms=int(bot.latency * 1000),
        created_at=guild.created_at,
        total_channels=len(guild.channels),
        text_channels=text_channels,
        voice_channels=voice_channels,
        total_roles=len(guild.roles),
        mod_role_id=bot.config.moderation_role_id if hasattr(bot, 'config') else None,
        muted_role_id=bot.config.muted_role_id if hasattr(bot, 'config') else None,
    )

    logger.debug("Server Info Fetched", [
        ("User", str(payload.sub)),
        ("Guild", guild.name),
        ("Members", str(guild.member_count)),
        ("Latency", f"{int(bot.latency * 1000)}ms"),
    ])

    return APIResponse(success=True, data=info)


__all__ = ["router"]
