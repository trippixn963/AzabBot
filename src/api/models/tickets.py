"""
AzabBot - Ticket API Models
===========================

Support ticket request/response models.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class TicketStatus(str, Enum):
    """Ticket status."""

    OPEN = "open"
    CLAIMED = "claimed"
    CLOSED = "closed"


class TicketPriority(str, Enum):
    """Ticket priority level."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TicketCategory(str, Enum):
    """Ticket category."""

    SUPPORT = "support"
    PARTNERSHIP = "partnership"
    SUGGESTION = "suggestion"
    APPEAL = "appeal"
    VERIFICATION = "verification"
    OTHER = "other"


# =============================================================================
# Response Models
# =============================================================================

class TicketBrief(BaseModel):
    """Brief ticket information for lists."""

    ticket_id: str = Field(description="Unique ticket ID")
    channel_id: Optional[int] = None
    user_id: int
    claimed_by: Optional[int] = None
    status: TicketStatus = TicketStatus.OPEN
    priority: Optional[TicketPriority] = None
    subject: Optional[str] = None
    created_at: datetime
    claimed_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class TicketDetail(BaseModel):
    """Detailed ticket information."""

    ticket_id: str
    channel_id: Optional[int] = None
    user_id: int
    user_name: Optional[str] = None
    user_avatar: Optional[str] = None
    claimed_by: Optional[int] = None
    claimer_name: Optional[str] = None
    status: TicketStatus = TicketStatus.OPEN
    priority: Optional[TicketPriority] = None
    subject: Optional[str] = None
    created_at: datetime
    claimed_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    close_reason: Optional[str] = None
    message_count: int = 0


class TicketMessage(BaseModel):
    """A message in a ticket."""

    message_id: int
    author_id: int
    author_name: Optional[str] = None
    author_avatar: Optional[str] = None
    content: str
    created_at: datetime
    is_staff: bool = False


class TicketStats(BaseModel):
    """Ticket statistics."""

    total_tickets: int = 0
    open_tickets: int = 0
    claimed_tickets: int = 0
    closed_tickets: int = 0
    tickets_today: int = 0
    avg_response_time_minutes: Optional[float] = None
    avg_resolution_time_minutes: Optional[float] = None


# =============================================================================
# Full Response Models
# =============================================================================

class TicketListResponse(BaseModel):
    """Response for GET /tickets endpoint."""
    success: bool = True
    data: List[Dict[str, Any]] = Field(description="List of tickets")
    total: int = Field(description="Total ticket count")
    total_pages: int = Field(description="Total pages")
    page: int = Field(description="Current page")
    per_page: int = Field(description="Items per page")


class TicketStatsResponse(BaseModel):
    """Response for GET /tickets/stats endpoint."""
    success: bool = True
    data: Dict[str, Any] = Field(description="Ticket statistics")


class TicketDetailResponse(BaseModel):
    """Response for GET /tickets/{ticket_id} endpoint."""
    success: bool = True
    data: Dict[str, Any] = Field(description="Ticket details")


class TicketMessagesResponse(BaseModel):
    """Response for GET /tickets/{ticket_id}/messages endpoint."""
    success: bool = True
    data: List[Dict[str, Any]] = Field(description="List of messages")
    total: int = Field(description="Total message count")
    total_pages: int = Field(description="Total pages")
    page: int = Field(description="Current page")
    per_page: int = Field(description="Items per page")


__all__ = [
    "TicketStatus",
    "TicketPriority",
    "TicketCategory",
    "TicketBrief",
    "TicketDetail",
    "TicketMessage",
    "TicketStats",
    "TicketListResponse",
    "TicketStatsResponse",
    "TicketDetailResponse",
    "TicketMessagesResponse",
]
