"""
AzabBot - Appeal API Models
===========================

Ban/mute appeal request/response models.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class AppealStatus(str, Enum):
    """Appeal status."""

    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    DENIED = "denied"


class AppealType(str, Enum):
    """Type of punishment being appealed."""

    MUTE = "mute"
    BAN = "ban"


# =============================================================================
# Response Models
# =============================================================================

class AppealBrief(BaseModel):
    """Brief appeal information for lists."""

    appeal_id: str = Field(description="Unique appeal ID")
    case_id: Optional[str] = None
    user_id: int
    user_name: Optional[str] = None
    user_avatar: Optional[str] = None
    appeal_type: AppealType = AppealType.BAN
    status: AppealStatus = AppealStatus.PENDING
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[int] = None
    resolver_name: Optional[str] = None
    resolver_avatar: Optional[str] = None


class AppealDetail(BaseModel):
    """Detailed appeal information."""

    appeal_id: str
    case_id: Optional[str] = None
    case_info: Optional[dict[str, Any]] = None
    user_id: int
    user_name: Optional[str] = None
    user_avatar: Optional[str] = None
    appeal_type: AppealType = AppealType.BAN
    status: AppealStatus = AppealStatus.PENDING
    reason: Optional[str] = None
    additional_info: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[int] = None
    resolver_name: Optional[str] = None
    resolver_avatar: Optional[str] = None
    resolution_reason: Optional[str] = None
    thread_id: Optional[int] = None
    email: Optional[str] = None
    attachments: Optional[list[dict[str, str]]] = None


class AppealFormData(BaseModel):
    """Data for appeal form (from token)."""

    valid: bool
    user_id: Optional[int] = None
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    case_id: Optional[str] = None
    appeal_type: Optional[AppealType] = None
    original_reason: Optional[str] = None
    punishment_date: Optional[datetime] = None
    can_appeal: bool = False
    cooldown_remaining: Optional[int] = Field(None, description="Seconds until can appeal again")
    error: Optional[str] = None


class AppealStats(BaseModel):
    """Appeal statistics."""

    total_appeals: int = 0
    pending_appeals: int = 0
    under_review_appeals: int = 0
    approved_appeals: int = 0
    denied_appeals: int = 0
    appeals_today: int = 0
    approval_rate_percent: Optional[float] = None
    avg_resolution_time_hours: Optional[float] = None


__all__ = [
    "AppealStatus",
    "AppealType",
    "AppealBrief",
    "AppealDetail",
    "AppealFormData",
    "AppealStats",
]
