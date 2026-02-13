"""
AzabBot - Dashboard Router
==========================

Dashboard statistics for the moderation panel.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from src.core.config import get_config, NY_TZ
from src.core.logger import logger
from src.core.database import get_db
from src.api.dependencies import get_bot, require_auth
from src.api.models.base import APIResponse
from src.api.models.auth import TokenPayload
from src.api.services.snapshots import get_snapshot_service
from src.utils.http import http_session, FAST_TIMEOUT


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

    def __init__(self) -> None:
        self._cache: Dict[str, Tuple[float, dict]] = {}  # cache_key -> (timestamp, data)

    def get(self, cache_key: str) -> Optional[dict]:
        """Get cached data if still valid."""
        if cache_key not in self._cache:
            return None

        cached_at, data = self._cache[cache_key]
        if time.time() - cached_at > CACHE_TTL_SECONDS:
            self._cache.pop(cache_key, None)
            return None

        return data

    def set(self, cache_key: str, data: dict) -> None:
        """Cache data for the given key."""
        self._cache[cache_key] = (time.time(), data)

    def invalidate(self, cache_key: str) -> None:
        """Remove cached data for the given key."""
        self._cache.pop(cache_key, None)

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


def _get_activity_chart(db, now: datetime, time_range: str = "week") -> list[DailyActivity]:
    """
    Get activity chart data based on the specified time range.

    Args:
        db: Database instance
        now: Current datetime
        time_range: One of "today", "week", "month", "all"

    Returns list of DailyActivity objects with appropriate date formatting.
    """
    if time_range == "today":
        return _get_hourly_activity(db, now)
    elif time_range == "week":
        return _get_daily_activity(db, now, days=7)
    elif time_range == "month":
        return _get_weekly_activity(db, now)
    else:  # "all"
        return _get_monthly_activity(db, now)


def _get_hourly_activity(db, now: datetime) -> list[DailyActivity]:
    """Get hourly activity for today (24 hours)."""
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    rows = db.fetchall(
        """
        SELECT
            CAST((created_at - ?) / 3600 AS INTEGER) as hour_index,
            COUNT(*) as total
        FROM cases
        WHERE created_at >= ?
        GROUP BY hour_index
        """,
        (today_start, today_start)
    )

    hour_counts = {int(row[0]): row[1] for row in rows}

    activity = []
    for hour in range(24):
        # Format: "12am", "1am", ... "12pm", "1pm", ... "11pm"
        if hour == 0:
            label = "12am"
        elif hour < 12:
            label = f"{hour}am"
        elif hour == 12:
            label = "12pm"
        else:
            label = f"{hour - 12}pm"

        activity.append(DailyActivity(
            date=label,
            cases=hour_counts.get(hour, 0),
        ))

    return activity


def _get_daily_activity(db, now: datetime, days: int = 7) -> list[DailyActivity]:
    """Get daily activity for the last N days."""
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    rows = db.fetchall(
        """
        SELECT
            CAST((created_at - ?) / 86400 AS INTEGER) as day_index,
            COUNT(*) as total
        FROM cases
        WHERE created_at >= ?
        GROUP BY day_index
        """,
        (start, start)
    )

    day_counts = {int(row[0]): row[1] for row in rows}

    activity = []
    for i in range(days):
        day = now - timedelta(days=days - 1 - i)
        # Format: "Mon", "Tue", etc.
        activity.append(DailyActivity(
            date=day.strftime("%a"),
            cases=day_counts.get(i, 0),
        ))

    return activity


def _get_weekly_activity(db, now: datetime) -> list[DailyActivity]:
    """Get weekly activity for the last ~5 weeks (grouped by week)."""
    # Start from 5 weeks ago, aligned to week start (Monday)
    weeks_back = 5
    week_start = now - timedelta(days=now.weekday())  # Start of current week (Monday)
    start_date = (week_start - timedelta(weeks=weeks_back - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_ts = start_date.timestamp()

    rows = db.fetchall(
        """
        SELECT
            CAST((created_at - ?) / 604800 AS INTEGER) as week_index,
            COUNT(*) as total
        FROM cases
        WHERE created_at >= ?
        GROUP BY week_index
        """,
        (start_ts, start_ts)
    )

    week_counts = {int(row[0]): row[1] for row in rows}

    activity = []
    for i in range(weeks_back):
        week_date = start_date + timedelta(weeks=i)
        # Format: "Jan 7", "Jan 14", etc. (day without leading zero)
        label = f"{week_date.strftime('%b')} {week_date.day}"
        activity.append(DailyActivity(
            date=label,
            cases=week_counts.get(i, 0),
        ))

    return activity


def _get_monthly_activity(db, now: datetime) -> list[DailyActivity]:
    """Get monthly activity for all time (last 6 months or since first case)."""
    # Get the timestamp of the earliest case
    first_case = db.fetchone("SELECT MIN(created_at) FROM cases")
    first_ts = first_case[0] if first_case and first_case[0] else now.timestamp()

    # Determine how many months to show (up to 12)
    first_date = datetime.utcfromtimestamp(first_ts)
    months_diff = (now.year - first_date.year) * 12 + (now.month - first_date.month) + 1
    months_to_show = min(max(months_diff, 1), 12)

    # Calculate start of first month
    start_month = now.month - months_to_show + 1
    start_year = now.year
    while start_month <= 0:
        start_month += 12
        start_year -= 1

    start_date = datetime(start_year, start_month, 1)
    start_ts = start_date.timestamp()

    # Query cases per month (using SQLite date functions)
    rows = db.fetchall(
        """
        SELECT
            strftime('%Y-%m', datetime(created_at, 'unixepoch')) as month,
            COUNT(*) as total
        FROM cases
        WHERE created_at >= ?
        GROUP BY month
        ORDER BY month
        """,
        (start_ts,)
    )

    month_counts = {row[0]: row[1] for row in rows}

    activity = []
    current = start_date
    while current <= now:
        month_key = current.strftime("%Y-%m")
        # Format: "Oct", "Nov", or "Oct '24" if spanning years
        if current.year != now.year:
            label = current.strftime("%b '%y")
        else:
            label = current.strftime("%b")

        activity.append(DailyActivity(
            date=label,
            cases=month_counts.get(month_key, 0),
        ))

        # Move to next month
        if current.month == 12:
            current = datetime(current.year + 1, 1, 1)
        else:
            current = datetime(current.year, current.month + 1, 1)

    return activity


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/stats", response_model=APIResponse[DashboardStatsResponse])
async def get_dashboard_stats(
    bot: Any = Depends(get_bot),
    payload: TokenPayload = Depends(require_auth),
    refresh: bool = Query(False, description="Force refresh, bypass cache"),
    time_range: str = Query("week", alias="range", description="Activity chart range: today, week, month, all"),
) -> APIResponse[DashboardStatsResponse]:
    """
    Get combined dashboard statistics.

    Returns both personal moderator stats and server-wide stats.
    Use ?refresh=true to bypass cache and get fresh data.
    Use ?range=today|week|month|all to change the activity chart time range.
    """
    # Validate range parameter
    valid_ranges = ("today", "week", "month", "all")
    if time_range not in valid_ranges:
        time_range = "week"

    config = get_config()
    moderator_id = payload.sub

    # Cache key includes range for different chart data
    cache_key = f"{moderator_id}:{time_range}"

    # Check cache first (unless refresh requested)
    if not refresh:
        cached_data = _dashboard_cache.get(cache_key)
        if cached_data:
            logger.debug("Dashboard Cache Hit", [
                ("Moderator", str(moderator_id)),
                ("Range", time_range),
            ])
            # Mark as cached when returning from cache
            cached_data["cached"] = True
            return APIResponse(success=True, data=DashboardStatsResponse(**cached_data))

    # Cache miss or refresh requested - fetch fresh data
    db = get_db()

    # Time calculations
    now = datetime.now(NY_TZ)
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
        async with http_session.session.get(TRIPPIXN_API_URL, timeout=FAST_TIMEOUT) as resp:
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
        if config.main_guild_id:
            guild = bot.get_guild(config.main_guild_id)
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
    if snapshot_service and config.main_guild_id:
        daily_members = snapshot_service.get_daily_member_counts(config.main_guild_id, 7)
        daily_online = snapshot_service.get_daily_online_counts(config.main_guild_id, 7)

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

    activity = _get_activity_chart(db, now, time_range=time_range)

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

    # Cache the response (key includes moderator_id and range)
    _dashboard_cache.set(cache_key, response_data.model_dump())

    logger.debug("Dashboard Stats Fetched", [
        ("Moderator", str(moderator_id)),
        ("Range", time_range),
        ("Mod Cases", str(mod_stats["total_cases"])),
        ("Server Cases", str(server_stats_data["total_cases"])),
        ("Activity Points", str(len(activity))),
        ("Refresh", str(refresh)),
    ])

    return APIResponse(success=True, data=response_data)


__all__ = ["router"]
