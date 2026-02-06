"""
AzabBot - Dashboard Router
==========================

Dashboard statistics for the moderation panel.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from datetime import datetime, timedelta
from typing import Any, Optional

import aiohttp
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from src.core.config import get_config
from src.core.logger import logger
from src.core.database import get_db
from src.api.dependencies import get_bot, require_auth
from src.api.models.base import APIResponse
from src.api.models.auth import TokenPayload
from src.api.services.snapshots import get_snapshot_service


# TrippixnBot API for guild stats (has accurate online count)
TRIPPIXN_API_URL = "http://localhost:8085/api/stats"

# Cache settings
CACHE_TTL_SECONDS = 120  # 2 minutes


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# =============================================================================
# Cache
# =============================================================================

class DashboardCache:
    """Simple TTL cache for dashboard stats."""

    def __init__(self):
        self._cache: dict[int, tuple[float, dict]] = {}  # mod_id -> (timestamp, data)

    def get(self, moderator_id: int) -> Optional[dict]:
        """Get cached data if still valid."""
        if moderator_id not in self._cache:
            return None

        cached_at, data = self._cache[moderator_id]
        if time.time() - cached_at > CACHE_TTL_SECONDS:
            del self._cache[moderator_id]
            return None

        return data

    def set(self, moderator_id: int, data: dict) -> None:
        """Cache data for moderator."""
        self._cache[moderator_id] = (time.time(), data)

    def invalidate(self, moderator_id: int) -> None:
        """Remove cached data for moderator."""
        self._cache.pop(moderator_id, None)

    def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()


# Singleton cache instance
_dashboard_cache = DashboardCache()


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
    cached: bool = Field(False, description="Whether this response was served from cache")
    cached_at: Optional[float] = Field(None, description="Cache timestamp (unix)")


# =============================================================================
# Optimized Query Helpers
# =============================================================================

def _get_moderator_stats_optimized(db, moderator_id: int, week_ago: float, two_weeks_ago: float, month_ago: float) -> dict:
    """
    Get all moderator stats in a single optimized query.

    Returns dict with: total_cases, cases_this_week, cases_last_week, cases_this_month,
                       total_mutes, total_bans, total_warns
    """
    result = db.fetchone(
        """
        SELECT
            COUNT(*) as total_cases,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as cases_this_week,
            SUM(CASE WHEN created_at >= ? AND created_at < ? THEN 1 ELSE 0 END) as cases_last_week,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as cases_this_month,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as total_mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as total_bans,
            SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as total_warns
        FROM cases
        WHERE moderator_id = ?
        """,
        (week_ago, two_weeks_ago, week_ago, month_ago, moderator_id)
    )

    return {
        "total_cases": result[0] or 0,
        "cases_this_week": result[1] or 0,
        "cases_last_week": result[2] or 0,
        "cases_this_month": result[3] or 0,
        "total_mutes": result[4] or 0,
        "total_bans": result[5] or 0,
        "total_warns": result[6] or 0,
    }


def _get_moderator_daily_stats(db, moderator_id: int, now: datetime) -> dict:
    """
    Get moderator's daily breakdown for last 7 days in a single query.

    Returns dict with: daily_cases, daily_warns, daily_mutes, daily_bans (each a list of 7 ints)
    """
    # Calculate date boundaries
    seven_days_ago = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    rows = db.fetchall(
        """
        SELECT
            CAST((created_at - ?) / 86400 AS INTEGER) as day_index,
            COUNT(*) as total,
            SUM(CASE WHEN action_type = 'warn' THEN 1 ELSE 0 END) as warns,
            SUM(CASE WHEN action_type = 'mute' THEN 1 ELSE 0 END) as mutes,
            SUM(CASE WHEN action_type = 'ban' THEN 1 ELSE 0 END) as bans
        FROM cases
        WHERE moderator_id = ? AND created_at >= ?
        GROUP BY day_index
        """,
        (seven_days_ago, moderator_id, seven_days_ago)
    )

    # Initialize arrays with zeros
    daily_cases = [0] * 7
    daily_warns = [0] * 7
    daily_mutes = [0] * 7
    daily_bans = [0] * 7

    # Fill in actual values
    for row in rows:
        day_idx = int(row[0])
        if 0 <= day_idx < 7:
            daily_cases[day_idx] = row[1] or 0
            daily_warns[day_idx] = row[2] or 0
            daily_mutes[day_idx] = row[3] or 0
            daily_bans[day_idx] = row[4] or 0

    return {
        "daily_cases": daily_cases,
        "daily_warns": daily_warns,
        "daily_mutes": daily_mutes,
        "daily_bans": daily_bans,
    }


def _get_server_stats_optimized(db, today_start: float, week_ago: float, two_weeks_ago: float) -> dict:
    """
    Get all server stats in a single optimized query.

    Returns dict with: total_cases, cases_today, cases_this_week, cases_last_week
    """
    result = db.fetchone(
        """
        SELECT
            COUNT(*) as total_cases,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as cases_today,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as cases_this_week,
            SUM(CASE WHEN created_at >= ? AND created_at < ? THEN 1 ELSE 0 END) as cases_last_week
        FROM cases
        """,
        (today_start, week_ago, two_weeks_ago, week_ago)
    )

    return {
        "total_cases": result[0] or 0,
        "cases_today": result[1] or 0,
        "cases_this_week": result[2] or 0,
        "cases_last_week": result[3] or 0,
    }


def _get_server_daily_stats(db, now: datetime) -> dict:
    """
    Get server's daily cases and tickets for last 7 days in optimized queries.

    Returns dict with: daily_cases, daily_tickets (each a list of 7 ints)
    """
    seven_days_ago = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    # Daily cases
    case_rows = db.fetchall(
        """
        SELECT
            CAST((created_at - ?) / 86400 AS INTEGER) as day_index,
            COUNT(*) as total
        FROM cases
        WHERE created_at >= ?
        GROUP BY day_index
        """,
        (seven_days_ago, seven_days_ago)
    )

    # Daily tickets
    ticket_rows = db.fetchall(
        """
        SELECT
            CAST((created_at - ?) / 86400 AS INTEGER) as day_index,
            COUNT(*) as total
        FROM tickets
        WHERE created_at >= ?
        GROUP BY day_index
        """,
        (seven_days_ago, seven_days_ago)
    )

    # Initialize arrays
    daily_cases = [0] * 7
    daily_tickets = [0] * 7

    for row in case_rows:
        day_idx = int(row[0])
        if 0 <= day_idx < 7:
            daily_cases[day_idx] = row[1] or 0

    for row in ticket_rows:
        day_idx = int(row[0])
        if 0 <= day_idx < 7:
            daily_tickets[day_idx] = row[1] or 0

    return {
        "daily_cases": daily_cases,
        "daily_tickets": daily_tickets,
    }


def _get_activity_chart(db, now: datetime) -> list[DailyActivity]:
    """
    Get 14-day activity chart in a single query.

    Returns list of DailyActivity objects.
    """
    fourteen_days_ago = (now - timedelta(days=13)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    rows = db.fetchall(
        """
        SELECT
            CAST((created_at - ?) / 86400 AS INTEGER) as day_index,
            COUNT(*) as total
        FROM cases
        WHERE created_at >= ?
        GROUP BY day_index
        """,
        (fourteen_days_ago, fourteen_days_ago)
    )

    # Build day index -> count map
    day_counts = {int(row[0]): row[1] for row in rows}

    # Generate activity list
    activity = []
    for i in range(14):
        day = now - timedelta(days=13 - i)
        activity.append(DailyActivity(
            date=day.strftime("%b %d"),
            cases=day_counts.get(i, 0),
        ))

    return activity


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/stats", response_model=APIResponse[DashboardStatsResponse])
async def get_dashboard_stats(
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
    refresh: bool = Query(False, description="Force refresh, bypass cache"),
) -> APIResponse[DashboardStatsResponse]:
    """
    Get combined dashboard statistics.

    Returns both personal moderator stats and server-wide stats.
    Use ?refresh=true to bypass cache and get fresh data.
    """
    config = get_config()
    moderator_id = payload.sub

    # Check cache first (unless refresh requested)
    if not refresh:
        cached_data = _dashboard_cache.get(moderator_id)
        if cached_data:
            logger.debug("Dashboard Cache Hit", [
                ("Moderator", str(moderator_id)),
            ])
            # Mark as cached when returning from cache
            cached_data["cached"] = True
            return APIResponse(success=True, data=DashboardStatsResponse(**cached_data))

    # Cache miss or refresh requested - fetch fresh data
    db = get_db()

    # Time calculations
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    week_ago = (now - timedelta(days=7)).timestamp()
    two_weeks_ago = (now - timedelta(days=14)).timestamp()
    month_ago = (now - timedelta(days=30)).timestamp()

    # =========================================================================
    # Moderator Stats (2 optimized queries instead of 10+)
    # =========================================================================

    mod_stats = _get_moderator_stats_optimized(db, moderator_id, week_ago, two_weeks_ago, month_ago)
    mod_daily = _get_moderator_daily_stats(db, moderator_id, now)

    # When did this mod join the server?
    joined_at = None
    if config.mod_server_id:
        guild = bot.get_guild(config.mod_server_id)
        if guild:
            member = guild.get_member(moderator_id)
            if member and member.joined_at:
                joined_at = member.joined_at

    moderator_stats = ModeratorDashboardStats(
        total_cases=mod_stats["total_cases"],
        cases_this_week=mod_stats["cases_this_week"],
        cases_last_week=mod_stats["cases_last_week"],
        cases_this_month=mod_stats["cases_this_month"],
        total_mutes=mod_stats["total_mutes"],
        total_bans=mod_stats["total_bans"],
        total_warns=mod_stats["total_warns"],
        joined_at=joined_at,
        daily_cases=mod_daily["daily_cases"],
        daily_warns=mod_daily["daily_warns"],
        daily_mutes=mod_daily["daily_mutes"],
        daily_bans=mod_daily["daily_bans"],
    )

    # =========================================================================
    # Server Stats (3 optimized queries instead of 8+)
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
        logger.warning("Dashboard TrippixnBot Fetch Failed", [
            ("Error Type", type(e).__name__),
            ("Error", str(e)[:50]),
        ])
        # Fallback to local guild data
        if config.logging_guild_id:
            guild = bot.get_guild(config.logging_guild_id)
            if guild:
                total_members = guild.member_count or 0

    server_stats_data = _get_server_stats_optimized(db, today_start, week_ago, two_weeks_ago)
    server_daily = _get_server_daily_stats(db, now)

    # Active tickets (simple count)
    active_tickets = db.fetchone(
        "SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'claimed')"
    )[0]

    # Historical snapshots for member/online trends
    daily_members = []
    daily_online = []
    snapshot_service = get_snapshot_service()
    if snapshot_service and config.logging_guild_id:
        daily_members = snapshot_service.get_daily_member_counts(config.logging_guild_id, 7)
        daily_online = snapshot_service.get_daily_online_counts(config.logging_guild_id, 7)

    server_stats = ServerDashboardStats(
        total_members=total_members,
        online_members=online_members,
        total_cases=server_stats_data["total_cases"],
        cases_today=server_stats_data["cases_today"],
        cases_this_week=server_stats_data["cases_this_week"],
        cases_last_week=server_stats_data["cases_last_week"],
        active_tickets=active_tickets,
        daily_members=daily_members,
        daily_online=daily_online,
        daily_cases=server_daily["daily_cases"],
        daily_tickets=server_daily["daily_tickets"],
    )

    # =========================================================================
    # Activity Chart (1 optimized query instead of 14)
    # =========================================================================

    activity = _get_activity_chart(db, now)

    # =========================================================================
    # Build Response & Cache
    # =========================================================================

    cache_time = time.time()
    response_data = DashboardStatsResponse(
        moderator=moderator_stats,
        server=server_stats,
        activity=activity,
        cached=False,
        cached_at=cache_time,
    )

    # Cache the response
    _dashboard_cache.set(moderator_id, response_data.model_dump())

    logger.debug("Dashboard Stats Fetched", [
        ("Moderator", str(moderator_id)),
        ("Mod Cases", str(mod_stats["total_cases"])),
        ("Server Cases", str(server_stats_data["total_cases"])),
        ("Refresh", str(refresh)),
    ])

    return APIResponse(success=True, data=response_data)


__all__ = ["router"]
