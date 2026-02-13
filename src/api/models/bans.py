"""
AzabBot - Ban Response Models
=============================

Pydantic models for ban-related API endpoints.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# =============================================================================
# User Models
# =============================================================================

class BannedUserInfo(BaseModel):
    """Basic user info for banned user."""
    id: str = Field(description="Discord user ID")
    username: str = Field(description="Discord username")
    display_name: str = Field(description="Display name")
    avatar_url: Optional[str] = Field(None, description="Avatar URL")
    bot: bool = Field(False, description="Whether user is a bot")


class ModeratorInfo(BaseModel):
    """Moderator info for ban records."""
    id: str = Field(description="Discord user ID")
    username: str = Field(description="Discord username")
    display_name: str = Field(description="Display name")
    avatar_url: Optional[str] = Field(None, description="Avatar URL")


# =============================================================================
# Ban Entry Models
# =============================================================================

class BanEntry(BaseModel):
    """Single ban entry in list."""
    user: BannedUserInfo = Field(description="Banned user info")
    reason: str = Field(description="Ban reason")
    banned_at: float = Field(description="Unix timestamp when banned")
    moderator_id: Optional[str] = Field(None, description="Moderator who banned")
    moderator: Optional[ModeratorInfo] = Field(None, description="Moderator details")


class BanHistoryEntry(BaseModel):
    """Single entry in user's ban history."""
    action: str = Field(description="Action type: ban or unban")
    reason: str = Field(description="Reason for action")
    timestamp: float = Field(description="Unix timestamp")
    moderator_id: Optional[str] = Field(None, description="Moderator ID")
    moderator: Optional[ModeratorInfo] = Field(None, description="Moderator details")


# =============================================================================
# Pagination
# =============================================================================

class BanPagination(BaseModel):
    """Pagination info for ban list."""
    page: int = Field(description="Current page")
    per_page: int = Field(description="Items per page")
    total: int = Field(description="Total items")
    total_pages: int = Field(description="Total pages")
    has_next: bool = Field(description="Has next page")
    has_prev: bool = Field(description="Has previous page")


# =============================================================================
# Response Data Models
# =============================================================================

class BanListData(BaseModel):
    """Data for ban list response."""
    bans: List[BanEntry] = Field(description="List of bans")
    pagination: BanPagination = Field(description="Pagination info")


class BanSyncData(BaseModel):
    """Data for ban sync response."""
    synced: int = Field(description="Number of bans synced")
    errors: int = Field(description="Number of errors")


class BanDetailData(BaseModel):
    """Data for ban detail response."""
    user: BannedUserInfo = Field(description="User info")
    is_banned: bool = Field(description="Whether user is currently banned")
    history: List[BanHistoryEntry] = Field(description="Ban/unban history")


class UnbanData(BaseModel):
    """Data for unban response."""
    user_id: str = Field(description="Unbanned user ID")
    unbanned_by: str = Field(description="Moderator who unbanned")
    reason: str = Field(description="Unban reason")


# =============================================================================
# Full Response Models
# =============================================================================

class BanListResponse(BaseModel):
    """Response for GET /bans endpoint."""
    success: bool = True
    data: BanListData


class BanSyncResponse(BaseModel):
    """Response for GET /bans/sync endpoint."""
    success: bool = True
    data: BanSyncData


class BanDetailResponse(BaseModel):
    """Response for GET /bans/{user_id} endpoint."""
    success: bool = True
    data: BanDetailData


class UnbanResponse(BaseModel):
    """Response for POST /bans/{user_id}/unban endpoint."""
    success: bool = True
    message: str = Field(default="User has been unbanned")
    data: UnbanData


__all__ = [
    "BannedUserInfo",
    "ModeratorInfo",
    "BanEntry",
    "BanHistoryEntry",
    "BanPagination",
    "BanListData",
    "BanSyncData",
    "BanDetailData",
    "UnbanData",
    "BanListResponse",
    "BanSyncResponse",
    "BanDetailResponse",
    "UnbanResponse",
]
