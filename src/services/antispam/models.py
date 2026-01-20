"""
Anti-Spam Data Models
=====================

Dataclasses for tracking message records, user states, and join records.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class MessageRecord:
    """Record of a message for spam detection."""
    content: str
    timestamp: datetime
    has_links: bool = False
    has_attachments: bool = False
    has_invites: bool = False
    has_stickers: bool = False
    mention_count: int = 0
    emoji_count: int = 0
    attachment_hashes: List[str] = field(default_factory=list)


@dataclass
class UserSpamState:
    """Tracks spam state for a user (in-memory for recent messages)."""
    messages: List[MessageRecord] = field(default_factory=list)
    invite_count: int = 0
    last_invite_time: Optional[datetime] = None


@dataclass
class JoinRecord:
    """Record of a member join for raid detection."""
    user_id: int
    username: str
    display_name: str
    account_created: datetime
    has_default_avatar: bool
    avatar_hash: Optional[str]
    join_time: datetime


@dataclass
class WebhookState:
    """Tracks webhook message state."""
    messages: List[datetime] = field(default_factory=list)
