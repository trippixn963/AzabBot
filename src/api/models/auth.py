"""
AzabBot - Auth API Models
=========================

Authentication request/response models.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# =============================================================================
# Request Models
# =============================================================================

class CheckModeratorRequest(BaseModel):
    """Request to check if a user is a moderator."""

    discord_id: int = Field(description="Discord user ID")


class RegisterRequest(BaseModel):
    """Request to register a moderator account."""

    discord_id: int = Field(description="Discord user ID")
    pin: str = Field(min_length=4, max_length=8, description="PIN code (4-8 digits)")


class LoginRequest(BaseModel):
    """Request to log in."""

    discord_id: int = Field(description="Discord user ID")
    pin: str = Field(description="PIN code")


# =============================================================================
# Response Models
# =============================================================================

class DiscordUserInfo(BaseModel):
    """Discord user information fetched from API."""

    discord_id: int = Field(description="Discord user ID")
    username: str = Field(description="Discord username")
    display_name: Optional[str] = Field(None, description="Display name (global name)")
    avatar: Optional[str] = Field(None, description="Avatar URL")


class CheckModeratorResponse(BaseModel):
    """Response for moderator check."""

    is_moderator: bool = Field(description="Whether the user has mod role")
    is_registered: bool = Field(description="Whether the user has registered")
    user: Optional[DiscordUserInfo] = Field(None, description="Discord user info")


class AuthTokenResponse(BaseModel):
    """Response containing auth tokens."""

    access_token: str = Field(description="JWT access token")
    token_type: str = "bearer"
    expires_at: Optional[datetime] = Field(None, description="Token expiration time")


class AuthenticatedUser(BaseModel):
    """Authenticated user info."""

    discord_id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_admin: bool = False
    permissions: list[str] = Field(default_factory=list)


class GuildInfo(BaseModel):
    """Discord guild information."""

    id: int = Field(description="Guild ID")
    name: str = Field(description="Guild name")
    icon: Optional[str] = Field(None, description="Guild icon URL")
    member_count: Optional[int] = Field(None, description="Member count")


# =============================================================================
# Token Models (Internal Use)
# =============================================================================

class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: int = Field(description="Subject (Discord user ID)")
    exp: datetime = Field(description="Expiration time")
    iat: datetime = Field(description="Issued at time")
    type: str = Field(default="access", description="Token type")
    permissions: list[str] = Field(default_factory=list)


__all__ = [
    "CheckModeratorRequest",
    "RegisterRequest",
    "LoginRequest",
    "CheckModeratorResponse",
    "DiscordUserInfo",
    "AuthTokenResponse",
    "AuthenticatedUser",
    "GuildInfo",
    "TokenPayload",
]
