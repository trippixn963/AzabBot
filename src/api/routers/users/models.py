"""
AzabBot - User Lookup Models
============================

Pydantic models for user lookup responses.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class UserPunishment(BaseModel):
    """A punishment/case in user's history."""

    case_id: str = Field(description="Case ID")
    action_type: str = Field(description="Type: warn, mute, ban, kick")
    reason: Optional[str] = Field(None, description="Reason for punishment")
    moderator_id: str = Field(description="Moderator Discord ID")
    moderator_name: Optional[str] = Field(None, description="Moderator username")
    created_at: str = Field(description="ISO timestamp")
    expires_at: Optional[str] = Field(None, description="ISO timestamp if temporary")
    is_active: bool = Field(False, description="Whether punishment is currently active")


class ChannelActivity(BaseModel):
    """User's activity in a channel."""

    channel_id: str = Field(description="Channel ID")
    channel_name: str = Field(description="Channel name")
    message_count: int = Field(0, description="Messages in this channel")


class UserRole(BaseModel):
    """User's role info."""

    id: str = Field(description="Role ID")
    name: str = Field(description="Role name")
    color: str = Field(description="Role color hex")
    position: int = Field(description="Role position")


class UserLookupResult(BaseModel):
    """Full user lookup result."""

    # Basic info
    discord_id: str = Field(description="Discord user ID as string")
    username: str = Field(description="Discord username")
    display_name: str = Field(description="Display name")
    nickname: Optional[str] = Field(None, description="Server-specific nickname")
    avatar_url: Optional[str] = Field(None, description="Avatar URL")

    # Data source indicator
    is_cached: bool = Field(False, description="True if data is from cache (user left/banned)")
    cached_at: Optional[str] = Field(None, description="When the cache was last updated")
    in_server: bool = Field(True, description="Whether user is currently in server")

    # Banner (Nitro feature)
    banner_url: Optional[str] = Field(None, description="Profile banner image URL (Nitro users)")
    banner_color: Optional[str] = Field(None, description="Accent color hex (fallback if no banner)")

    # Account info
    joined_server_at: Optional[str] = Field(None, description="ISO timestamp")
    account_created_at: Optional[str] = Field(None, description="ISO timestamp")
    account_age_days: int = Field(0, description="Account age in days")
    server_tenure_days: int = Field(0, description="Days in server")
    last_seen_at: Optional[str] = Field(None, description="Last activity timestamp")

    # Moderation status
    is_muted: bool = Field(False, description="Currently muted")
    is_banned: bool = Field(False, description="Currently banned")
    mute_expires_at: Optional[str] = Field(None, description="ISO timestamp")

    # Case stats
    total_cases: int = Field(0, description="Total cases")
    total_warns: int = Field(0, description="Total warnings")
    total_mutes: int = Field(0, description="Total mutes")
    total_bans: int = Field(0, description="Total bans")

    # Activity stats (from SyriaBot)
    total_messages: int = Field(0, description="Total messages")
    messages_this_week: int = Field(0, description="Messages in last 7 days")
    messages_this_month: int = Field(0, description="Messages in last 30 days")
    voice_time_seconds: int = Field(0, description="Total voice time in seconds")
    voice_time_formatted: str = Field("0h 0m", description="Formatted voice time")

    # Risk assessment
    risk_score: int = Field(0, description="Risk score 0-100")
    risk_flags: List[str] = Field(default_factory=list, description="Risk indicators")

    # Invite info
    invite_code: Optional[str] = Field(None, description="Invite code used to join")
    invited_by: Optional[str] = Field(None, description="Who invited them (username)")
    invited_by_id: Optional[str] = Field(None, description="Inviter's Discord ID")

    # Roles
    roles: List[UserRole] = Field(default_factory=list, description="User's roles")

    # History
    previous_usernames: List[str] = Field(default_factory=list, description="Previous usernames")
    most_active_channels: List[ChannelActivity] = Field(default_factory=list, description="Top channels")

    # Punishment history
    punishments: List[UserPunishment] = Field(default_factory=list, description="Punishment history")


__all__ = [
    "UserPunishment",
    "ChannelActivity",
    "UserRole",
    "UserLookupResult",
]
