"""
AzabBot - Stats API Models
==========================

Statistics and dashboard data models.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from .base import ModeratorBrief


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


# =============================================================================
# Response Models
# =============================================================================

class HourlyCount(BaseModel):
    """Hour and count data."""
    hour: int = Field(description="Hour of day (0-23)")
    count: int = Field(description="Activity count")


class PeakHoursData(BaseModel):
    """Peak hours data."""
    peak_hours: List[HourlyCount] = Field(description="Peak hours data")


class PeakHoursResponse(BaseModel):
    """Response for peak hours endpoints."""
    success: bool = True
    data: PeakHoursData


class PublicStatsResponse(BaseModel):
    """Response for GET /stats endpoint (public)."""
    bot: Dict[str, Any] = Field(description="Bot status info")
    moderation: Dict[str, Any] = Field(description="Moderation stats")
    appeals: Dict[str, Any] = Field(description="Appeals stats")
    tickets: Dict[str, Any] = Field(description="Tickets stats")
    top_offenders: List[Dict[str, Any]] = Field(description="Top offenders list")
    moderator_leaderboard: List[Dict[str, Any]] = Field(description="Moderator leaderboard")
    recent_actions: List[Dict[str, Any]] = Field(description="Recent actions")
    repeat_offenders: List[Dict[str, Any]] = Field(description="Repeat offenders")
    recent_releases: List[Dict[str, Any]] = Field(description="Recent releases")
    moderator_spotlight: Optional[Dict[str, Any]] = Field(None, description="Spotlight moderator")
    system: Dict[str, Any] = Field(description="System info")
    changelog: List[Dict[str, Any]] = Field(description="Changelog entries")
    generated_at: str = Field(description="ISO timestamp")


class UserSummaryResponse(BaseModel):
    """Response for GET /stats/user/{user_id} endpoint."""
    user_id: str = Field(description="Discord user ID")
    username: str = Field(description="Discord username")
    display_name: Optional[str] = Field(None, description="Display name")
    avatar_url: Optional[str] = Field(None, description="Avatar URL")
    in_server: bool = Field(description="Whether user is in server")
    account_created_at: Optional[str] = Field(None, description="Account creation date")
    joined_server_at: Optional[str] = Field(None, description="Server join date")
    account_age_days: int = Field(0, description="Account age in days")
    server_tenure_days: int = Field(0, description="Server tenure in days")
    is_muted: bool = Field(False, description="Whether user is muted")
    is_banned: bool = Field(False, description="Whether user is banned")
    mute_expires_at: Optional[str] = Field(None, description="Mute expiration")
    total_cases: int = Field(0, description="Total cases")
    total_warns: int = Field(0, description="Total warnings")
    total_mutes: int = Field(0, description="Total mutes")
    total_bans: int = Field(0, description="Total bans")
    first_case_at: Optional[str] = Field(None, description="First case date")
    last_case_at: Optional[str] = Field(None, description="Last case date")
    recent_cases: List[Dict[str, Any]] = Field(description="Recent cases")


__all__ = [
    "DashboardStats",
    "ModeratorStats",
    "LeaderboardEntry",
    "ActivityChartData",
    "ServerInfo",
    "SystemHealth",
    "HourlyCount",
    "PeakHoursData",
    "PeakHoursResponse",
    "PublicStatsResponse",
    "UserSummaryResponse",
]
