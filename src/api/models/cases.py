"""
AzabBot - Case API Models
=========================

Moderation case request/response models.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

from .base import UserBrief, ModeratorBrief


# =============================================================================
# Enums
# =============================================================================

class CaseType(str, Enum):
    """Case/action type."""

    MUTE = "mute"
    UNMUTE = "unmute"
    BAN = "ban"
    UNBAN = "unban"
    KICK = "kick"
    WARN = "warn"
    TIMEOUT = "timeout"


class CaseStatus(str, Enum):
    """Case status."""

    ACTIVE = "active"
    RESOLVED = "resolved"
    APPEALED = "appealed"
    EXPIRED = "expired"


# =============================================================================
# Request Models
# =============================================================================

class CaseListParams(BaseModel):
    """Query parameters for case list."""

    page: int = Field(1, ge=1, description="Page number")
    limit: int = Field(50, ge=1, le=100, description="Items per page")
    status: Optional[CaseStatus] = Field(None, description="Filter by status")
    action_type: Optional[CaseType] = Field(None, description="Filter by action type")
    moderator_id: Optional[int] = Field(None, description="Filter by moderator")
    target_id: Optional[int] = Field(None, description="Filter by target user")
    search: Optional[str] = Field(None, description="Search in reason")
    sort_by: str = Field("created_at", description="Sort field")
    sort_order: str = Field("desc", description="Sort order (asc/desc)")


class CaseUpdateRequest(BaseModel):
    """Request to update a case."""

    reason: Optional[str] = Field(None, max_length=500, description="Update reason")
    notes: Optional[str] = Field(None, max_length=1000, description="Internal notes")


class CaseResolveRequest(BaseModel):
    """Request to resolve a case."""

    resolution_reason: Optional[str] = Field(None, max_length=500)


# =============================================================================
# Response Models
# =============================================================================

class CaseBrief(BaseModel):
    """Brief case information for lists."""

    case_id: str = Field(description="Unique case ID (e.g., 001A)")
    action_type: CaseType
    status: CaseStatus
    target: UserBrief
    moderator: ModeratorBrief
    reason: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    duration: Optional[int] = Field(None, description="Duration in seconds (for mutes)")
    has_appeal: bool = False


class CaseDetail(BaseModel):
    """Detailed case information."""

    case_id: str
    action_type: CaseType
    status: CaseStatus

    # Users involved
    target: UserBrief
    moderator: ModeratorBrief
    resolved_by: Optional[ModeratorBrief] = None

    # Details
    reason: Optional[str] = None
    resolution_reason: Optional[str] = None
    notes: Optional[str] = None
    evidence_urls: list[str] = Field(default_factory=list)

    # Timing
    created_at: datetime
    resolved_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    duration: Optional[int] = None

    # Related
    appeal_id: Optional[str] = None
    thread_id: Optional[int] = Field(None, description="Discord thread ID")
    message_id: Optional[int] = Field(None, description="Discord message ID")

    # Transcript
    has_transcript: bool = False
    transcript_url: Optional[str] = None


class CaseStats(BaseModel):
    """Case statistics."""

    total: int = 0
    active: int = 0
    resolved: int = 0
    appealed: int = 0

    by_type: dict[str, int] = Field(default_factory=dict)
    by_moderator: dict[str, int] = Field(default_factory=dict)

    today: int = 0
    this_week: int = 0
    this_month: int = 0


class CaseTimeline(BaseModel):
    """Timeline entry for a case."""

    timestamp: datetime
    event: str
    description: str
    actor: Optional[UserBrief] = None


__all__ = [
    "CaseType",
    "CaseStatus",
    "CaseListParams",
    "CaseUpdateRequest",
    "CaseResolveRequest",
    "CaseBrief",
    "CaseDetail",
    "CaseStats",
    "CaseTimeline",
]
