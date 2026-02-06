"""
AzabBot - User API Models
=========================

User-related request/response models.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from .base import UserBrief
from .cases import CaseBrief


# =============================================================================
# Request Models
# =============================================================================

class UserSearchParams(BaseModel):
    """Query parameters for user search."""

    query: str = Field(min_length=2, description="Search query (ID or username)")
    limit: int = Field(10, ge=1, le=50)


class UserHistoryParams(BaseModel):
    """Query parameters for user moderation history."""

    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)
    include_resolved: bool = Field(True, description="Include resolved cases")


# =============================================================================
# Response Models
# =============================================================================

class UserProfile(BaseModel):
    """Full user profile with moderation history summary."""

    user: UserBrief

    # Discord info
    created_at: Optional[datetime] = Field(None, description="Account creation date")
    joined_at: Optional[datetime] = Field(None, description="Server join date")

    # Current status
    is_muted: bool = False
    is_banned: bool = False
    is_in_server: bool = True
    current_mute_expires: Optional[datetime] = None

    # Moderation summary
    total_cases: int = 0
    total_mutes: int = 0
    total_bans: int = 0
    total_warns: int = 0
    active_cases: int = 0

    # Recent activity
    recent_cases: list[CaseBrief] = Field(default_factory=list)
    last_case_at: Optional[datetime] = None

    # Tickets
    total_tickets: int = 0
    open_tickets: int = 0

    # Appeals
    total_appeals: int = 0
    pending_appeals: int = 0


class UserSearchResult(BaseModel):
    """User search result."""

    user: UserBrief
    is_in_server: bool = True
    is_muted: bool = False
    is_banned: bool = False
    case_count: int = 0


class ModerationNote(BaseModel):
    """A moderator note on a user."""

    note_id: str
    user_id: int
    content: str
    author: UserBrief
    created_at: datetime
    updated_at: Optional[datetime] = None


class UserActivity(BaseModel):
    """User activity entry for timeline."""

    timestamp: datetime
    event_type: str
    description: str
    case_id: Optional[str] = None
    moderator: Optional[UserBrief] = None


__all__ = [
    "UserSearchParams",
    "UserHistoryParams",
    "UserProfile",
    "UserSearchResult",
    "ModerationNote",
    "UserActivity",
]
