"""
AzabBot - Moderator Stats Router
================================

Moderator statistics and peak hours endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from src.core.logger import logger
from src.core.config import NY_TZ
from src.api.dependencies import get_bot, require_auth
from src.api.models.base import APIResponse, ModeratorBrief
from src.api.models.stats import ModeratorStats, PeakHoursResponse, PeakHoursData, HourlyCount
from src.api.models.auth import TokenPayload
from src.api.utils.discord import batch_fetch_users
from src.core.database import get_db


router = APIRouter(tags=["Statistics"])


@router.get("/peak-hours", response_model=PeakHoursResponse)
async def get_server_peak_hours(
    payload: TokenPayload = Depends(require_auth),
) -> PeakHoursResponse:
    """
    Get server-wide peak activity hours (aggregate of all moderators).

    Returns activity count for each hour of the day (0-23).
    """
    db = get_db()

    # Get aggregated peak hours across all moderators
    rows = db.fetchall(
        """SELECT hour, SUM(count) as total
           FROM mod_hourly_activity
           GROUP BY hour
           ORDER BY hour"""
    )

    # Build full 24-hour data with zeros for missing hours
    hourly_data = {i: 0 for i in range(24)}
    for row in rows:
        hourly_data[row["hour"]] = row["total"]

    peak_hours = [HourlyCount(hour=hour, count=count) for hour, count in hourly_data.items()]

    logger.debug("Server Peak Hours Fetched", [
        ("Requested By", str(payload.sub)),
        ("Total Hours", str(len(peak_hours))),
    ])

    return PeakHoursResponse(data=PeakHoursData(peak_hours=peak_hours))


@router.get("/moderators/{moderator_id}/peak-hours", response_model=PeakHoursResponse)
async def get_moderator_peak_hours(
    moderator_id: int,
    top_n: int = Query(3, ge=1, le=24, description="Number of top hours to return"),
    payload: TokenPayload = Depends(require_auth),
) -> PeakHoursResponse:
    """
    Get peak activity hours for a specific moderator.

    Returns top N hours when the moderator is most active.
    """
    db = get_db()

    peak_hours_raw = db.get_peak_hours(moderator_id, top_n)

    # Format for frontend
    peak_hours = [HourlyCount(hour=hour, count=count) for hour, count in peak_hours_raw]

    logger.debug("Moderator Peak Hours Fetched", [
        ("Moderator ID", str(moderator_id)),
        ("Requested By", str(payload.sub)),
        ("Hours Returned", str(len(peak_hours))),
    ])

    return PeakHoursResponse(data=PeakHoursData(peak_hours=peak_hours))


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
        discord_id=str(moderator_id),
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


__all__ = ["router"]
