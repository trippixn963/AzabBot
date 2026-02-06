"""
AzabBot - Stats API Models
==========================

Statistics and dashboard data models.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from .base import ModeratorBrief


# =============================================================================
# Request Models
# =============================================================================

class StatsTimeRange(BaseModel):
    """Time range for statistics queries."""

    start: Optional[datetime] = Field(None, description="Start of range")
    end: Optional[datetime] = Field(None, description="End of range")
    preset: Optional[str] = Field(
        None,
        description="Preset: today, yesterday, this_week, this_month, last_30_days"
    )


# =============================================================================
# Response Models
# =============================================================================

class DashboardStats(BaseModel):
    """Main dashboard statistics."""

    # Overview
    total_members: int = 0
    online_members: int = 0
    total_cases: int = 0
    active_mutes: int = 0
    active_bans: int = 0

    # Tickets
    open_tickets: int = 0
    claimed_tickets: int = 0
    avg_response_time_minutes: Optional[float] = None

    # Appeals
    pending_appeals: int = 0

    # Activity (last 24h)
    cases_today: int = 0
    tickets_today: int = 0
    appeals_today: int = 0

    # Trends (compared to yesterday)
    cases_trend: Optional[float] = Field(None, description="Percentage change")
    tickets_trend: Optional[float] = None


class ModeratorStats(BaseModel):
    """Statistics for a specific moderator."""

    moderator: ModeratorBrief

    # Totals
    total_actions: int = 0
    total_mutes: int = 0
    total_bans: int = 0
    total_warns: int = 0
    total_kicks: int = 0

    # Tickets
    tickets_claimed: int = 0
    tickets_closed: int = 0
    avg_ticket_resolution_minutes: Optional[float] = None

    # Appeals resolved
    appeals_approved: int = 0
    appeals_denied: int = 0

    # Time period stats
    actions_today: int = 0
    actions_this_week: int = 0
    actions_this_month: int = 0

    # Last activity
    last_action_at: Optional[datetime] = None


class LeaderboardEntry(BaseModel):
    """Entry in the moderator leaderboard."""

    rank: int
    moderator: ModeratorBrief
    total_actions: int = 0
    mutes: int = 0
    bans: int = 0
    tickets_closed: int = 0
    score: int = Field(0, description="Weighted score for ranking")


class ActivityChartData(BaseModel):
    """Data point for activity charts."""

    timestamp: datetime
    label: str  # e.g., "Mon", "Jan 1"
    cases: int = 0
    tickets: int = 0
    appeals: int = 0
    mutes: int = 0
    bans: int = 0


class ServerInfo(BaseModel):
    """Discord server information."""

    guild_id: int
    name: str
    icon_url: Optional[str] = None
    member_count: int = 0
    online_count: int = 0
    bot_latency_ms: int = 0
    created_at: Optional[datetime] = None

    # Channels
    total_channels: int = 0
    text_channels: int = 0
    voice_channels: int = 0

    # Roles
    total_roles: int = 0
    mod_role_id: Optional[int] = None
    muted_role_id: Optional[int] = None


class SystemHealth(BaseModel):
    """System health metrics."""

    status: str = "healthy"
    uptime_seconds: int = 0
    memory_mb: float = 0
    cpu_percent: float = 0

    # Discord
    discord_connected: bool = True
    discord_latency_ms: int = 0
    guilds_connected: int = 0

    # Database
    db_connected: bool = True
    db_size_mb: Optional[float] = None

    # API
    api_requests_today: int = 0
    api_errors_today: int = 0

    # WebSocket
    ws_connections: int = 0


__all__ = [
    "StatsTimeRange",
    "DashboardStats",
    "ModeratorStats",
    "LeaderboardEntry",
    "ActivityChartData",
    "ServerInfo",
    "SystemHealth",
]
