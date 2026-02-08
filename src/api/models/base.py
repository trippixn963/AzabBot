"""
AzabBot - Base API Models
=========================

Common response models and utilities.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field


# =============================================================================
# Generic Type Variables
# =============================================================================

T = TypeVar("T")


# =============================================================================
# Base Response Models
# =============================================================================

class APIResponse(BaseModel, Generic[T]):
    """Standard API response wrapper."""

    success: bool = True
    message: Optional[str] = None
    data: Optional[T] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ErrorResponse(BaseModel):
    """Error response model."""

    success: bool = False
    error: str
    error_code: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response."""

    success: bool = True
    data: list[T]
    pagination: "PaginationMeta"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PaginationMeta(BaseModel):
    """Pagination metadata."""

    page: int = Field(ge=1, description="Current page number")
    per_page: int = Field(ge=1, le=100, description="Items per page")
    total: int = Field(ge=0, description="Total number of items")
    total_pages: int = Field(ge=0, description="Total number of pages")
    has_next: bool = Field(description="Whether there is a next page")
    has_prev: bool = Field(description="Whether there is a previous page")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    bot: str = "Azab"
    run_id: Optional[str] = None
    connected: bool
    timestamp: datetime
    discord: Optional["DiscordStatus"] = None


class DiscordStatus(BaseModel):
    """Discord connection status."""

    connected: bool
    latency_ms: int
    guilds: int


# =============================================================================
# Common Models
# =============================================================================

class UserBrief(BaseModel):
    """Brief user information."""

    id: int = Field(description="Discord user ID")
    username: str = Field(description="Discord username")
    display_name: Optional[str] = Field(None, description="Display name")
    avatar_url: Optional[str] = Field(None, description="Avatar URL")


class ModeratorBrief(BaseModel):
    """Brief moderator information."""

    discord_id: int = Field(description="Discord user ID")
    username: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_online: bool = False


# =============================================================================
# WebSocket Models
# =============================================================================

class WSMessage(BaseModel):
    """WebSocket message format."""

    type: str = Field(description="Event type")
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class WSEventType:
    """WebSocket event type constants."""

    # Connection events
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    HEARTBEAT = "heartbeat"
    PONG = "pong"

    # Subscription events
    SUBSCRIBED = "subscribed"
    UNSUBSCRIBED = "unsubscribed"

    # Auth events
    AUTHENTICATED = "authenticated"
    ERROR = "error"

    # Case events
    CASE_CREATED = "case.created"
    CASE_UPDATED = "case.updated"
    CASE_RESOLVED = "case.resolved"

    # Ticket events
    TICKET_CREATED = "ticket.created"
    TICKET_CLAIMED = "ticket.claimed"
    TICKET_CLOSED = "ticket.closed"
    TICKET_MESSAGE = "ticket.message"

    # Appeal events
    APPEAL_SUBMITTED = "appeal.submitted"
    APPEAL_APPROVED = "appeal.approved"
    APPEAL_DENIED = "appeal.denied"

    # Moderation events
    MOD_ACTION = "mod.action"
    USER_MUTED = "user.muted"
    USER_UNMUTED = "user.unmuted"
    USER_BANNED = "user.banned"
    USER_UNBANNED = "user.unbanned"

    # Stats events
    STATS_UPDATED = "stats.updated"

    # Bot status events (for dashboard)
    BOT_STATUS = "bot_status"
    BOT_LOG = "bot_log"
    COMMAND_EXECUTED = "command_executed"


__all__ = [
    "APIResponse",
    "ErrorResponse",
    "PaginatedResponse",
    "PaginationMeta",
    "HealthResponse",
    "DiscordStatus",
    "UserBrief",
    "ModeratorBrief",
    "WSMessage",
    "WSEventType",
]
