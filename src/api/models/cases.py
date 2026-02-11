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


__all__ = [
    "CaseType",
    "CaseStatus",
    "CaseBrief",
]
