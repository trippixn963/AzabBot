"""
AzabBot - Stats Router
======================

Dashboard statistics and analytics endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query

from src.core.logger import logger
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
from src.core.database import get_db


router = APIRouter(prefix="/stats", tags=["Statistics"])


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
    now = datetime.utcnow().timestamp()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0).timestamp()
    yesterday_start = today_start - 86400

    # Get guild info
    guild = None
    if bot and hasattr(bot, 'config') and bot.config.logging_guild_id:
        guild = bot.get_guild(bot.config.logging_guild_id)

    total_members = guild.member_count if guild else 0
    online_members = sum(1 for m in guild.members if m.status.value != "offline") if guild else 0

    # Case stats
    total_cases = db.fetchone("SELECT COUNT(*) FROM cases")[0]

    active_mutes = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE action_type = 'mute' AND (expires_at IS NULL OR expires_at > ?)",
        (now,)
    )[0]

    active_bans = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE action_type = 'ban' AND (expires_at IS NULL OR expires_at > ?)",
        (now,)
    )[0]

    # Ticket stats
    open_tickets = db.fetchone("SELECT COUNT(*) FROM tickets WHERE status = 'open'")[0]
    claimed_tickets = db.fetchone("SELECT COUNT(*) FROM tickets WHERE status = 'claimed'")[0]

    avg_response = db.fetchone(
        """SELECT AVG(claimed_at - created_at) / 60.0
           FROM tickets WHERE claimed_at IS NOT NULL"""
    )[0]

    # Appeal stats
    pending_appeals = db.fetchone("SELECT COUNT(*) FROM appeals WHERE status = 'pending'")[0]

    # Today's activity
    cases_today = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE created_at >= ?",
        (today_start,)
    )[0]

    tickets_today = db.fetchone(
        "SELECT COUNT(*) FROM tickets WHERE created_at >= ?",
        (today_start,)
    )[0]

    appeals_today = db.fetchone(
        "SELECT COUNT(*) FROM appeals WHERE created_at >= ?",
        (today_start,)
    )[0]

    # Trends (compare to yesterday)
    cases_yesterday = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE created_at >= ? AND created_at < ?",
        (yesterday_start, today_start)
    )[0]

    tickets_yesterday = db.fetchone(
        "SELECT COUNT(*) FROM tickets WHERE created_at >= ? AND created_at < ?",
        (yesterday_start, today_start)
    )[0]

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
    now = datetime.utcnow().timestamp()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0).timestamp()
    week_start = today_start - (7 * 86400)
    month_start = today_start - (30 * 86400)

    # Get moderator info
    mod_name = None
    mod_avatar = None
    try:
        user = await bot.fetch_user(moderator_id)
        mod_name = user.name
        mod_avatar = str(user.display_avatar.url) if user.display_avatar else None
    except Exception:
        pass

    moderator = ModeratorBrief(
        discord_id=moderator_id,
        username=mod_name,
        avatar_url=mod_avatar,
    )

    # Action counts
    action_counts = db.fetchall(
        "SELECT action_type, COUNT(*) as count FROM cases WHERE moderator_id = ? GROUP BY action_type",
        (moderator_id,)
    )
    count_map = {row["action_type"]: row["count"] for row in action_counts}

    # Ticket stats
    tickets_claimed = db.fetchone(
        "SELECT COUNT(*) FROM tickets WHERE claimed_by = ?",
        (moderator_id,)
    )[0]

    tickets_closed = db.fetchone(
        "SELECT COUNT(*) FROM tickets WHERE claimed_by = ? AND status = 'closed'",
        (moderator_id,)
    )[0]

    avg_ticket_resolution = db.fetchone(
        """SELECT AVG(closed_at - claimed_at) / 60.0
           FROM tickets WHERE claimed_by = ? AND closed_at IS NOT NULL""",
        (moderator_id,)
    )[0]

    # Appeal stats
    appeals_approved = db.fetchone(
        "SELECT COUNT(*) FROM appeals WHERE resolved_by = ? AND status = 'approved'",
        (moderator_id,)
    )[0]

    appeals_denied = db.fetchone(
        "SELECT COUNT(*) FROM appeals WHERE resolved_by = ? AND status = 'denied'",
        (moderator_id,)
    )[0]

    # Time period stats
    actions_today = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE moderator_id = ? AND created_at >= ?",
        (moderator_id, today_start)
    )[0]

    actions_this_week = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE moderator_id = ? AND created_at >= ?",
        (moderator_id, week_start)
    )[0]

    actions_this_month = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE moderator_id = ? AND created_at >= ?",
        (moderator_id, month_start)
    )[0]

    # Last action
    last_action = db.fetchone(
        "SELECT MAX(created_at) FROM cases WHERE moderator_id = ?",
        (moderator_id,)
    )
    last_action_at = datetime.fromtimestamp(last_action[0]) if last_action and last_action[0] else None

    stats = ModeratorStats(
        moderator=moderator,
        total_actions=sum(count_map.values()),
        total_mutes=count_map.get("mute", 0),
        total_bans=count_map.get("ban", 0),
        total_warns=count_map.get("warn", 0),
        total_kicks=count_map.get("kick", 0),
        tickets_claimed=tickets_claimed,
        tickets_closed=tickets_closed,
        avg_ticket_resolution_minutes=round(avg_ticket_resolution, 1) if avg_ticket_resolution else None,
        appeals_approved=appeals_approved,
        appeals_denied=appeals_denied,
        actions_today=actions_today,
        actions_this_week=actions_this_week,
        actions_this_month=actions_this_month,
        last_action_at=last_action_at,
    )

    logger.debug("Moderator Stats Fetched", [
        ("Moderator ID", str(moderator_id)),
        ("Requested By", str(payload.sub)),
        ("Total Actions", str(stats.total_actions)),
        ("Tickets Closed", str(tickets_closed)),
    ])

    return APIResponse(success=True, data=stats)


# =============================================================================
# Leaderboard
# =============================================================================

@router.get("/leaderboard", response_model=PaginatedResponse[List[LeaderboardEntry]])
async def get_leaderboard(
    period: str = Query("month", description="Time period: week, month, year, all"),
    pagination: PaginationParams = Depends(get_pagination),
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> PaginatedResponse[List[LeaderboardEntry]]:
    """
    Get moderator leaderboard rankings.

    Ranked by weighted score of moderation actions.
    """
    db = get_db()

    # Calculate time range
    now = datetime.utcnow().timestamp()
    if period == "week":
        start_time = now - (7 * 86400)
    elif period == "month":
        start_time = now - (30 * 86400)
    elif period == "year":
        start_time = now - (365 * 86400)
    else:
        start_time = 0

    # Get moderator stats with scoring
    # Weights: ban=5, kick=3, mute=2, warn=1
    query = """
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
    """

    all_rows = db.fetchall(query, (start_time,))
    total = len(all_rows)

    # Paginate
    start_idx = pagination.offset
    end_idx = start_idx + pagination.per_page
    page_rows = all_rows[start_idx:end_idx]

    # Add tickets closed to score
    entries = []
    for idx, row in enumerate(page_rows, start=start_idx + 1):
        mod_id = row["moderator_id"]

        # Get moderator info
        mod_name = None
        mod_avatar = None
        try:
            user = await bot.fetch_user(mod_id)
            mod_name = user.name
            mod_avatar = str(user.display_avatar.url) if user.display_avatar else None
        except Exception:
            pass

        # Get tickets closed
        tickets_closed = db.fetchone(
            """SELECT COUNT(*) FROM tickets
               WHERE claimed_by = ? AND status = 'closed' AND closed_at >= ?""",
            (mod_id, start_time)
        )[0]

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
        ("User", str(payload.sub)),
        ("Period", period),
        ("Page", str(pagination.page)),
        ("Results", str(len(entries))),
        ("Total", str(total)),
    ])

    return create_paginated_response(entries, total, pagination)


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
    """
    db = get_db()

    data = []
    now = datetime.utcnow()

    for i in range(days - 1, -1, -1):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        day_end = day_start + 86400

        # Get counts for this day
        cases = db.fetchone(
            "SELECT COUNT(*) FROM cases WHERE created_at >= ? AND created_at < ?",
            (day_start, day_end)
        )[0]

        tickets = db.fetchone(
            "SELECT COUNT(*) FROM tickets WHERE created_at >= ? AND created_at < ?",
            (day_start, day_end)
        )[0]

        appeals = db.fetchone(
            "SELECT COUNT(*) FROM appeals WHERE created_at >= ? AND created_at < ?",
            (day_start, day_end)
        )[0]

        mutes = db.fetchone(
            "SELECT COUNT(*) FROM cases WHERE action_type = 'mute' AND created_at >= ? AND created_at < ?",
            (day_start, day_end)
        )[0]

        bans = db.fetchone(
            "SELECT COUNT(*) FROM cases WHERE action_type = 'ban' AND created_at >= ? AND created_at < ?",
            (day_start, day_end)
        )[0]

        # Format label based on range
        if days <= 7:
            label = day.strftime("%a")  # Mon, Tue, etc.
        else:
            label = day.strftime("%b %d")  # Jan 1, Jan 2, etc.

        data.append(ActivityChartData(
            timestamp=day,
            label=label,
            cases=cases,
            tickets=tickets,
            appeals=appeals,
            mutes=mutes,
            bans=bans,
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
    if bot and hasattr(bot, 'config') and bot.config.logging_guild_id:
        guild = bot.get_guild(bot.config.logging_guild_id)

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
