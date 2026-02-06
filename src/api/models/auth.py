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

class CheckModeratorResponse(BaseModel):
    """Response for moderator check."""

    is_moderator: bool = Field(description="Whether the user has mod role")
    is_registered: bool = Field(description="Whether the user has registered")


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
    "AuthTokenResponse",
    "AuthenticatedUser",
    "TokenPayload",
]
