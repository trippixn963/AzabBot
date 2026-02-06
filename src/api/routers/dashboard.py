"""
AzabBot - Dashboard Router
==========================

Dashboard statistics for the moderation panel.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.core.config import get_config
from src.core.logger import logger
from src.core.database import get_db
from src.api.dependencies import get_bot, require_auth
from src.api.models.base import APIResponse
from src.api.models.auth import TokenPayload


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# =============================================================================
# Models
# =============================================================================

class ModeratorDashboardStats(BaseModel):
    """Personal stats for the current moderator."""

    total_cases: int = Field(0, description="Total cases handled by this mod")
    cases_this_week: int = Field(0, description="Cases in the last 7 days")
    cases_this_month: int = Field(0, description="Cases in the last 30 days")
    total_mutes: int = Field(0, description="Total mute actions")
    total_bans: int = Field(0, description="Total ban actions")
    total_warns: int = Field(0, description="Total warn actions")
    joined_at: Optional[datetime] = Field(None, description="When the mod joined the server")


class ServerDashboardStats(BaseModel):
    """Server-wide stats."""

    total_members: int = Field(0, description="Total server members")
    online_members: int = Field(0, description="Members currently online")
    total_cases: int = Field(0, description="Total cases server-wide")
    cases_today: int = Field(0, description="Cases created today")
    cases_this_week: int = Field(0, description="Cases in the last 7 days")
    active_tickets: int = Field(0, description="Currently open/claimed tickets")


class DashboardStatsResponse(BaseModel):
    """Combined dashboard stats response."""

    moderator: ModeratorDashboardStats
    server: ServerDashboardStats


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
    now_ts = now.timestamp()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    week_ago = (now - timedelta(days=7)).timestamp()
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
        cases_this_month=mod_cases_month,
        total_mutes=mod_mutes,
        total_bans=mod_bans,
        total_warns=mod_warns,
        joined_at=joined_at,
    )

    # =========================================================================
    # Server Stats
    # =========================================================================

    # Get guild for member counts
    guild = None
    total_members = 0
    online_members = 0

    if config.logging_guild_id:
        guild = bot.get_guild(config.logging_guild_id)
    elif config.mod_server_id:
        guild = bot.get_guild(config.mod_server_id)

    if guild:
        total_members = guild.member_count or 0
        # Count online members (requires members intent)
        try:
            online_members = sum(
                1 for m in guild.members
                if m.status.value in ("online", "idle", "dnd")
            )
        except Exception:
            online_members = 0

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

    # Active tickets (open or claimed)
    active_tickets = db.fetchone(
        "SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'claimed')"
    )[0]

    server_stats = ServerDashboardStats(
        total_members=total_members,
        online_members=online_members,
        total_cases=server_total_cases,
        cases_today=server_cases_today,
        cases_this_week=server_cases_week,
        active_tickets=active_tickets,
    )

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
        ),
    )


__all__ = ["router"]
