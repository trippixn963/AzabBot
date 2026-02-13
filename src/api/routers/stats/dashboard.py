"""
AzabBot - Dashboard Stats Router
================================

Dashboard overview statistics (authenticated).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from src.core.logger import logger
from src.core.config import NY_TZ
from src.api.dependencies import get_bot, require_auth
from src.api.models.base import APIResponse
from src.api.models.stats import DashboardStats
from src.api.models.auth import TokenPayload
from src.core.database import get_db


router = APIRouter(tags=["Statistics"])


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
    if bot and hasattr(bot, 'config') and bot.config.main_guild_id:
        guild = bot.get_guild(bot.config.main_guild_id)

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


__all__ = ["router"]
