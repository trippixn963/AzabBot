"""
AzabBot - Case API Models
=========================

Moderation case request/response models.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
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
    REVERSED = "reversed"


# =============================================================================
# Case List Response
# =============================================================================

class CaseListItem(BaseModel):
    """Case item for list responses."""

    id: int = Field(description="Database row ID")
    case_id: str = Field(description="Unique case ID (e.g., 001A)")
    case_type: str = Field(description="Action type: mute, ban, warn, kick")
    status: str = Field(description="Case status: active, resolved, expired")
    user_id: str = Field(description="Target user Discord ID")
    user_name: str = Field(description="Target username")
    user_avatar: Optional[str] = Field(None, description="Target avatar URL")
    moderator_id: str = Field(description="Moderator Discord ID")
    moderator_name: str = Field(description="Moderator username")
    moderator_avatar: Optional[str] = Field(None, description="Moderator avatar URL")
    reason: str = Field(description="Action reason")
    created_at: str = Field(description="ISO timestamp")
    expires_at: Optional[str] = Field(None, description="ISO timestamp for expiry")


class CaseListData(BaseModel):
    """Data payload for case list response."""

    cases: List[CaseListItem]
    total: int = Field(description="Total cases matching filters")
    total_pages: int = Field(description="Total pages available")


class CaseListResponse(BaseModel):
    """Response for GET /cases endpoint."""

    success: bool = True
    data: CaseListData


# =============================================================================
# Case Stats Response
# =============================================================================

class CaseStatsData(BaseModel):
    """Case statistics data."""

    total_cases: int = Field(description="Total number of cases")
    active_mutes: int = Field(description="Currently active mutes")
    active_bans: int = Field(description="Currently active bans")
    cases_today: int = Field(description="Cases created today")
    cases_this_week: int = Field(description="Cases created this week")
    pending_appeals: int = Field(description="Appeals awaiting review")


class CaseStatsResponse(BaseModel):
    """Response for GET /cases/stats endpoint."""

    success: bool = True
    data: CaseStatsData


# =============================================================================
# Case Detail Response
# =============================================================================

class EvidenceItem(BaseModel):
    """Evidence attachment for a case."""

    id: int = Field(description="Evidence item ID")
    type: str = Field(description="Evidence type: image, link, text")
    content: str = Field(description="URL or text content")
    added_by: str = Field(description="Who added this evidence")
    added_at: str = Field(description="ISO timestamp")


class AppealInfo(BaseModel):
    """Appeal information for a case."""

    id: int = Field(description="Appeal database ID")
    status: str = Field(description="Appeal status: pending, approved, denied")
    reason: Optional[str] = Field(None, description="Appeal reason from user")
    submitted_at: Optional[str] = Field(None, description="ISO timestamp")
    reviewed_by: Optional[str] = Field(None, description="Reviewer username")
    reviewed_at: Optional[str] = Field(None, description="ISO timestamp")
    response: Optional[str] = Field(None, description="Resolution reason")


class TranscriptMessage(BaseModel):
    """Message in a case transcript."""

    id: Optional[str] = Field(None, description="Message ID")
    author_id: str = Field(description="Author Discord ID")
    author_name: Optional[str] = Field(None, description="Author display name")
    author_avatar: Optional[str] = Field(None, description="Author avatar URL")
    content: str = Field(description="Message content")
    timestamp: Optional[str] = Field(None, description="ISO timestamp")
    attachments: List[str] = Field(default_factory=list, description="Attachment URLs")
    is_bot: bool = Field(False, description="Whether author is the bot")


class CaseTranscript(BaseModel):
    """Thread transcript for a case."""

    thread_id: str = Field(description="Thread Discord ID")
    thread_name: Optional[str] = Field(None, description="Thread name")
    message_count: int = Field(description="Messages in response")
    total_messages: int = Field(description="Total messages in thread")
    has_more: bool = Field(description="Whether more messages exist")
    messages: List[TranscriptMessage]


class CaseDetailData(BaseModel):
    """Detailed case information."""

    id: int = Field(description="Database row ID")
    case_id: str = Field(description="Unique case ID (e.g., 001A)")
    case_type: str = Field(description="Action type")
    status: str = Field(description="Case status")
    user_id: str = Field(description="Target user Discord ID")
    user_name: str = Field(description="Target username")
    user_avatar: Optional[str] = Field(None)
    moderator_id: str = Field(description="Moderator Discord ID")
    moderator_name: str = Field(description="Moderator username")
    moderator_avatar: Optional[str] = Field(None)
    reason: str = Field(description="Action reason")
    duration: Optional[str] = Field(None, description="Human-readable duration")
    created_at: str = Field(description="ISO timestamp")
    updated_at: str = Field(description="ISO timestamp")
    expires_at: Optional[str] = Field(None, description="ISO timestamp")
    notes: Optional[str] = Field(None, description="Resolution notes")
    evidence: List[EvidenceItem] = Field(default_factory=list)
    appeal: Optional[AppealInfo] = Field(None)
    related_cases: List[str] = Field(default_factory=list, description="Related case IDs")
    transcript: Optional[CaseTranscript] = Field(None)


class CaseDetailResponse(BaseModel):
    """Response for GET /cases/{case_id} endpoint."""

    success: bool = True
    data: CaseDetailData


# =============================================================================
# Case Transcript Response (Full Transcript View)
# =============================================================================

class ExtendedUserInfo(BaseModel):
    """Extended user info for transcripts."""
    id: str = Field(description="Discord user ID")
    username: Optional[str] = Field(None, description="Discord username")
    display_name: Optional[str] = Field(None, description="Display name")
    avatar_url: Optional[str] = Field(None, description="Avatar URL")
    joined_at: Optional[float] = Field(None, description="Timestamp when joined server")
    created_at: Optional[float] = Field(None, description="Account creation timestamp")


class TranscriptAttachment(BaseModel):
    """Attachment in a transcript message."""
    filename: str = Field(description="File name")
    url: str = Field(description="File URL")
    content_type: Optional[str] = Field(None, description="MIME type")
    size: Optional[int] = Field(None, description="File size in bytes")


class TranscriptEmbed(BaseModel):
    """Embed in a transcript message."""
    title: Optional[str] = Field(None, description="Embed title")
    description: Optional[str] = Field(None, description="Embed description")
    color: Optional[int] = Field(None, description="Embed color value")
    url: Optional[str] = Field(None, description="Embed URL")
    image_url: Optional[str] = Field(None, description="Image URL")
    thumbnail_url: Optional[str] = Field(None, description="Thumbnail URL")
    author_name: Optional[str] = Field(None, description="Author name")
    footer_text: Optional[str] = Field(None, description="Footer text")
    fields: List[Dict[str, Any]] = Field(default_factory=list, description="Embed fields")


class FullTranscriptMessage(BaseModel):
    """Full message in a transcript with all details."""
    message_id: Optional[str] = Field(None, description="Message ID")
    author_id: int = Field(description="Author Discord ID")
    author_name: Optional[str] = Field(None, description="Author username")
    author_display_name: Optional[str] = Field(None, description="Author display name")
    author_avatar_url: Optional[str] = Field(None, description="Author avatar URL")
    author_role_color: Optional[str] = Field(None, description="Author role color hex")
    content: str = Field(description="Message content")
    timestamp: float = Field(description="Unix timestamp")
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="Attachments")
    embeds: List[Dict[str, Any]] = Field(default_factory=list, description="Embeds")
    embeds_count: int = Field(0, description="Number of embeds")
    is_pinned: bool = Field(False, description="Whether message is pinned")
    reactions: List[Dict[str, Any]] = Field(default_factory=list, description="Reactions")
    reply_to: Optional[Dict[str, Any]] = Field(None, description="Reply reference")
    is_edited: bool = Field(False, description="Whether message was edited")
    edited_at: Optional[float] = Field(None, description="Edit timestamp")
    type: str = Field("default", description="Message type")


class FullTranscriptData(BaseModel):
    """Full transcript data for case/ticket transcripts."""
    case_id: Optional[str] = Field(None, description="Case ID if applicable")
    ticket_id: Optional[str] = Field(None, description="Ticket ID if applicable")
    thread_id: Optional[int] = Field(None, description="Thread/channel Discord ID")
    thread_name: Optional[str] = Field(None, description="Thread/channel name")
    created_at: Optional[float] = Field(None, description="Thread creation timestamp")
    total_messages: int = Field(description="Total messages available")
    message_count: int = Field(description="Messages in this response")
    messages: List[Dict[str, Any]] = Field(description="Message list")
    mention_map: Optional[Dict[str, str]] = Field(None, description="User ID to name mapping")
    offset: int = Field(0, description="Message offset")
    has_more: bool = Field(False, description="More messages available")
    is_live: bool = Field(description="Whether fetched live from Discord")


class CaseTranscriptResponse(BaseModel):
    """Response for GET /case-transcripts/{case_id} endpoint."""
    case_id: str = Field(description="Case ID")
    user_id: int = Field(description="Target user ID")
    action_type: str = Field(description="Case action type")
    reason: Optional[str] = Field(None, description="Case reason")
    moderator_id: int = Field(description="Moderator ID")
    created_at: float = Field(description="Case creation timestamp")
    evidence: List[str] = Field(default_factory=list, description="Evidence URLs")
    transcript: Optional[Dict[str, Any]] = Field(None, description="Transcript data")
    target_user: Dict[str, Any] = Field(description="Target user info")
    moderator: Dict[str, Any] = Field(description="Moderator info")


class TicketTranscriptResponse(BaseModel):
    """Response for GET /ticket-transcripts/{ticket_id} endpoint."""
    ticket_id: str = Field(description="Ticket ID")
    user_id: int = Field(description="Ticket creator ID")
    category: str = Field(description="Ticket category")
    subject: str = Field(description="Ticket subject")
    status: str = Field(description="Ticket status")
    claimed_by: Optional[int] = Field(None, description="Claimer ID")
    closed_by: Optional[int] = Field(None, description="Closer ID")
    closed_at: Optional[float] = Field(None, description="Close timestamp")
    created_at: float = Field(description="Creation timestamp")
    transcript: Optional[Dict[str, Any]] = Field(None, description="Transcript data")


# =============================================================================
# Legacy Model (kept for backwards compatibility)
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
    # Enums
    "CaseType",
    "CaseStatus",
    # List response
    "CaseListItem",
    "CaseListData",
    "CaseListResponse",
    # Stats response
    "CaseStatsData",
    "CaseStatsResponse",
    # Detail response
    "EvidenceItem",
    "AppealInfo",
    "TranscriptMessage",
    "CaseTranscript",
    "CaseDetailData",
    "CaseDetailResponse",
    # Full transcript response
    "ExtendedUserInfo",
    "TranscriptAttachment",
    "TranscriptEmbed",
    "FullTranscriptMessage",
    "FullTranscriptData",
    "CaseTranscriptResponse",
    "TicketTranscriptResponse",
    # Legacy
    "CaseBrief",
]
