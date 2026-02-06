"""
AzabBot - Dashboard Router
==========================

Dashboard statistics for the moderation panel.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import Any, Optional

import aiohttp
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.core.config import get_config
from src.core.logger import logger
from src.core.database import get_db
from src.api.dependencies import get_bot, require_auth
from src.api.models.base import APIResponse
from src.api.models.auth import TokenPayload


# TrippixnBot API for guild stats (has accurate online count)
TRIPPIXN_API_URL = "http://localhost:8085/api/stats"


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# =============================================================================
# Models
# =============================================================================

class ModeratorDashboardStats(BaseModel):
    """Personal stats for the current moderator."""

    total_cases: int = Field(0, description="Total cases handled by this mod")
    cases_this_week: int = Field(0, description="Cases in the last 7 days")
    cases_last_week: int = Field(0, description="Cases 7-14 days ago (for trend)")
    cases_this_month: int = Field(0, description="Cases in the last 30 days")
    total_mutes: int = Field(0, description="Total mute actions")
    total_bans: int = Field(0, description="Total ban actions")
    total_warns: int = Field(0, description="Total warn actions")
    joined_at: Optional[datetime] = Field(None, description="When the mod joined the server")
    daily_cases: list[int] = Field(default_factory=list, description="Last 7 days cases (sparkline)")
    daily_warns: list[int] = Field(default_factory=list, description="Last 7 days warns")
    daily_mutes: list[int] = Field(default_factory=list, description="Last 7 days mutes")
    daily_bans: list[int] = Field(default_factory=list, description="Last 7 days bans")


class ServerDashboardStats(BaseModel):
    """Server-wide stats."""

    total_members: int = Field(0, description="Total server members")
    online_members: int = Field(0, description="Members currently online")
    total_cases: int = Field(0, description="Total cases server-wide")
    cases_today: int = Field(0, description="Cases created today")
    cases_this_week: int = Field(0, description="Cases in the last 7 days")
    cases_last_week: int = Field(0, description="Cases 7-14 days ago (for trend)")
    active_tickets: int = Field(0, description="Currently open/claimed tickets")
    daily_members: list[int] = Field(default_factory=list, description="Last 7 days member count")
    daily_online: list[int] = Field(default_factory=list, description="Last 7 days online count")
    daily_cases: list[int] = Field(default_factory=list, description="Last 7 days cases")
    daily_tickets: list[int] = Field(default_factory=list, description="Last 7 days new tickets")


class DailyActivity(BaseModel):
    """Daily activity data point."""

    date: str = Field(description="Date label (e.g., 'Jan 24')")
    cases: int = Field(0, description="Number of cases on this day")


class DashboardStatsResponse(BaseModel):
    """Combined dashboard stats response."""

    moderator: ModeratorDashboardStats
    server: ServerDashboardStats
    activity: list[DailyActivity] = Field(default_factory=list, description="Last 14 days activity")


# =============================================================================
# Helper Functions
# =============================================================================

def _get_daily_counts(
    db,
    now: datetime,
    days: int,
    query: str,
    params: tuple = ()
) -> list[int]:
    """Get daily counts for the last N days."""
    counts = []
    for i in range(days - 1, -1, -1):  # Oldest to newest
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        day_end = day_start + 86400

        full_query = query.format(day_start=day_start, day_end=day_end)
        result = db.fetchone(full_query, params)
        counts.append(result[0] if result else 0)

    return counts


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/stats", response_model=APIResponse[DashboardStatsResponse])
async def get_dashboard_stats(
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
) -> APIResponse[DashboardStatsResponse]:
    """
    Get combined dashboard statistics.

    Returns both personal moderator stats and server-wide stats.
    """
    db = get_db()
    config = get_config()
    moderator_id = payload.sub

    # Time calculations
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    week_ago = (now - timedelta(days=7)).timestamp()
    two_weeks_ago = (now - timedelta(days=14)).timestamp()
    month_ago = (now - timedelta(days=30)).timestamp()

    # =========================================================================
    # Moderator Stats
    # =========================================================================

    # Total cases by this mod
    mod_total_cases = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE moderator_id = ?",
        (moderator_id,)
    )[0]

    # Cases this week
    mod_cases_week = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE moderator_id = ? AND created_at >= ?",
        (moderator_id, week_ago)
    )[0]

    # Cases last week (7-14 days ago)
    mod_cases_last_week = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE moderator_id = ? AND created_at >= ? AND created_at < ?",
        (moderator_id, two_weeks_ago, week_ago)
    )[0]

    # Cases this month
    mod_cases_month = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE moderator_id = ? AND created_at >= ?",
        (moderator_id, month_ago)
    )[0]

    # Mutes by this mod
    mod_mutes = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE moderator_id = ? AND action_type = 'mute'",
        (moderator_id,)
    )[0]

    # Bans by this mod
    mod_bans = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE moderator_id = ? AND action_type = 'ban'",
        (moderator_id,)
    )[0]

    # Warns by this mod
    mod_warns = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE moderator_id = ? AND action_type = 'warn'",
        (moderator_id,)
    )[0]

    # Daily sparklines for moderator (last 7 days)
    mod_daily_cases = []
    mod_daily_warns = []
    mod_daily_mutes = []
    mod_daily_bans = []

    for i in range(6, -1, -1):  # 6 days ago to today
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        day_end = day_start + 86400

        # All cases
        day_cases = db.fetchone(
            "SELECT COUNT(*) FROM cases WHERE moderator_id = ? AND created_at >= ? AND created_at < ?",
            (moderator_id, day_start, day_end)
        )[0]
        mod_daily_cases.append(day_cases)

        # Warns
        day_warns = db.fetchone(
            "SELECT COUNT(*) FROM cases WHERE moderator_id = ? AND action_type = 'warn' AND created_at >= ? AND created_at < ?",
            (moderator_id, day_start, day_end)
        )[0]
        mod_daily_warns.append(day_warns)

        # Mutes
        day_mutes = db.fetchone(
            "SELECT COUNT(*) FROM cases WHERE moderator_id = ? AND action_type = 'mute' AND created_at >= ? AND created_at < ?",
            (moderator_id, day_start, day_end)
        )[0]
        mod_daily_mutes.append(day_mutes)

        # Bans
        day_bans = db.fetchone(
            "SELECT COUNT(*) FROM cases WHERE moderator_id = ? AND action_type = 'ban' AND created_at >= ? AND created_at < ?",
            (moderator_id, day_start, day_end)
        )[0]
        mod_daily_bans.append(day_bans)

    # When did this mod join the server?
    joined_at = None
    if config.mod_server_id:
        guild = bot.get_guild(config.mod_server_id)
        if guild:
            member = guild.get_member(moderator_id)
            if member and member.joined_at:
                joined_at = member.joined_at

    moderator_stats = ModeratorDashboardStats(
        total_cases=mod_total_cases,
        cases_this_week=mod_cases_week,
        cases_last_week=mod_cases_last_week,
        cases_this_month=mod_cases_month,
        total_mutes=mod_mutes,
        total_bans=mod_bans,
        total_warns=mod_warns,
        joined_at=joined_at,
        daily_cases=mod_daily_cases,
        daily_warns=mod_daily_warns,
        daily_mutes=mod_daily_mutes,
        daily_bans=mod_daily_bans,
    )

    # =========================================================================
    # Server Stats
    # =========================================================================

    # Fetch guild stats from TrippixnBot (has accurate member/online counts)
    total_members = 0
    online_members = 0

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(TRIPPIXN_API_URL, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    guild_data = data.get("data", {}).get("guild", {})
                    total_members = guild_data.get("member_count", 0)
                    online_members = guild_data.get("online_count", 0)
    except Exception as e:
        logger.warning("Failed to Fetch TrippixnBot Stats", [
            ("Error", str(e)[:50]),
        ])
        # Fallback to local guild data
        guild = None
        if config.logging_guild_id:
            guild = bot.get_guild(config.logging_guild_id)
        if guild:
            total_members = guild.member_count or 0

    # Total cases server-wide
    server_total_cases = db.fetchone("SELECT COUNT(*) FROM cases")[0]

    # Cases today
    server_cases_today = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE created_at >= ?",
        (today_start,)
    )[0]

    # Cases this week
    server_cases_week = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE created_at >= ?",
        (week_ago,)
    )[0]

    # Cases last week (7-14 days ago)
    server_cases_last_week = db.fetchone(
        "SELECT COUNT(*) FROM cases WHERE created_at >= ? AND created_at < ?",
        (two_weeks_ago, week_ago)
    )[0]

    # Active tickets (open or claimed)
    active_tickets = db.fetchone(
        "SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'claimed')"
    )[0]

    # Daily server stats (last 7 days)
    server_daily_cases = []
    server_daily_tickets = []

    for i in range(6, -1, -1):  # 6 days ago to today
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        day_end = day_start + 86400

        # Cases
        day_cases = db.fetchone(
            "SELECT COUNT(*) FROM cases WHERE created_at >= ? AND created_at < ?",
            (day_start, day_end)
        )[0]
        server_daily_cases.append(day_cases)

        # New tickets created
        day_tickets = db.fetchone(
            "SELECT COUNT(*) FROM tickets WHERE created_at >= ? AND created_at < ?",
            (day_start, day_end)
        )[0]
        server_daily_tickets.append(day_tickets)

    # Note: daily_members and daily_online require historical snapshots
    # which we don't currently store. Leaving as empty arrays.
    # TODO: Add a daily snapshot system to track member/online counts

    server_stats = ServerDashboardStats(
        total_members=total_members,
        online_members=online_members,
        total_cases=server_total_cases,
        cases_today=server_cases_today,
        cases_this_week=server_cases_week,
        cases_last_week=server_cases_last_week,
        active_tickets=active_tickets,
        daily_members=[],  # Requires historical snapshots
        daily_online=[],   # Requires historical snapshots
        daily_cases=server_daily_cases,
        daily_tickets=server_daily_tickets,
    )

    # =========================================================================
    # Activity (Last 14 Days)
    # =========================================================================

    activity = []
    for i in range(13, -1, -1):  # 13 days ago to today
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        day_end = day_start + 86400  # 24 hours

        day_cases = db.fetchone(
            "SELECT COUNT(*) FROM cases WHERE created_at >= ? AND created_at < ?",
            (day_start, day_end)
        )[0]

        activity.append(DailyActivity(
            date=day.strftime("%b %d"),  # e.g., "Jan 24"
            cases=day_cases,
        ))

    # =========================================================================
    # Response
    # =========================================================================

    logger.debug("Dashboard Stats Fetched", [
        ("Moderator", str(moderator_id)),
        ("Mod Cases", str(mod_total_cases)),
        ("Server Cases", str(server_total_cases)),
        ("Active Tickets", str(active_tickets)),
    ])

    return APIResponse(
        success=True,
        data=DashboardStatsResponse(
            moderator=moderator_stats,
            server=server_stats,
            activity=activity,
        ),
    )


__all__ = ["router"]
