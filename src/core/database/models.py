"""
AzabBot - Database Type Definitions
===================================

TypedDict definitions for database records.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Optional, TypedDict


class MuteRecord(TypedDict, total=False):
    """Type for mute records returned from database."""
    id: int
    user_id: int
    guild_id: int
    muted_at: float
    duration_minutes: Optional[int]
    reason: Optional[str]
    moderator_id: Optional[int]
    unmuted_at: Optional[float]


class CaseLogRecord(TypedDict, total=False):
    """Type for case log records."""
    id: int
    case_id: str
    user_id: int
    thread_id: int
    profile_message_id: Optional[int]
    created_at: float


class TrackedModRecord(TypedDict, total=False):
    """Type for tracked mod records."""
    id: int
    mod_id: int
    thread_id: int
    added_at: float


class AltLinkRecord(TypedDict, total=False):
    """Type for alt link records."""
    id: int
    banned_user_id: int
    potential_alt_id: int
    guild_id: int
    confidence: str
    total_score: int
    signals: str
    detected_at: float
    reviewed: int


class JoinInfoRecord(TypedDict, total=False):
    """Type for user join info records."""
    user_id: int
    guild_id: int
    invite_code: Optional[str]
    inviter_id: Optional[int]
    joined_at: float
    avatar_hash: Optional[str]


class ModNoteRecord(TypedDict, total=False):
    """Type for moderator note records."""
    id: int
    user_id: int
    guild_id: int
    moderator_id: int
    note: str
    created_at: float


class UsernameHistoryRecord(TypedDict, total=False):
    """Type for username history records."""
    id: int
    user_id: int
    username: Optional[str]
    display_name: Optional[str]
    guild_id: Optional[int]
    changed_at: float


class AppealRecord(TypedDict, total=False):
    """Type for appeal records."""
    id: int
    appeal_id: str
    case_id: str
    user_id: int
    guild_id: int
    thread_id: int
    action_type: str
    reason: Optional[str]
    status: str
    created_at: float
    resolved_at: Optional[float]
    resolved_by: Optional[int]
    resolution: Optional[str]
    resolution_reason: Optional[str]


class MemberActivityRecord(TypedDict, total=False):
    """Type for member activity records."""
    user_id: int
    guild_id: int
    join_count: int
    last_join: float
    message_count: int
    last_message: Optional[float]


class PendingReasonRecord(TypedDict, total=False):
    """Type for pending reason records."""
    id: int
    thread_id: int
    moderator_id: int
    action_type: str
    created_at: float


class TicketRecord(TypedDict, total=False):
    """Type for ticket records."""
    id: int
    ticket_id: str
    user_id: int
    guild_id: int
    thread_id: int
    category: str
    subject: str
    status: str
    priority: str
    claimed_by: Optional[int]
    assigned_to: Optional[int]
    created_at: float
    closed_at: Optional[float]
    closed_by: Optional[int]
    close_reason: Optional[str]
