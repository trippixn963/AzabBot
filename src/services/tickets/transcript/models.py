"""
AzabBot - Ticket Transcript Models
==================================

Data classes for ticket transcript serialization.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any


@dataclass
class TicketTranscriptAttachment:
    """Represents an attachment in a ticket transcript."""
    filename: str
    url: str
    content_type: Optional[str] = None
    size: int = 0


@dataclass
class TicketTranscriptMessage:
    """Represents a single message in a ticket transcript."""
    author_id: int
    author_name: str
    author_display_name: str
    author_avatar_url: Optional[str]
    content: str
    timestamp: float
    attachments: List[TicketTranscriptAttachment]
    is_bot: bool = False
    is_staff: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "author_id": self.author_id,
            "author_name": self.author_name,
            "author_display_name": self.author_display_name,
            "author_avatar_url": self.author_avatar_url,
            "content": self.content,
            "timestamp": self.timestamp,
            "attachments": [asdict(a) for a in self.attachments],
            "is_bot": self.is_bot,
            "is_staff": self.is_staff,
        }


@dataclass
class TicketTranscript:
    """Complete JSON transcript of a ticket thread."""
    ticket_id: str
    thread_id: int
    thread_name: str
    category: str
    subject: str
    status: str
    created_at: float
    closed_at: Optional[float]
    message_count: int
    messages: List[TicketTranscriptMessage]
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    claimed_by_id: Optional[int] = None
    claimed_by_name: Optional[str] = None
    closed_by_id: Optional[int] = None
    closed_by_name: Optional[str] = None
    mention_map: Optional[Dict[int, str]] = None  # user/channel/role ID -> name

    def to_json(self) -> str:
        """Serialize transcript to JSON string."""
        # Convert mention_map keys to strings for JSON compatibility
        mention_map_str = None
        if self.mention_map:
            mention_map_str = {str(k): v for k, v in self.mention_map.items()}

        data = {
            "ticket_id": self.ticket_id,
            "thread_id": self.thread_id,
            "thread_name": self.thread_name,
            "category": self.category,
            "subject": self.subject,
            "status": self.status,
            "created_at": self.created_at,
            "closed_at": self.closed_at,
            "message_count": self.message_count,
            "messages": [m.to_dict() for m in self.messages],
            "user_id": self.user_id,
            "user_name": self.user_name,
            "claimed_by_id": self.claimed_by_id,
            "claimed_by_name": self.claimed_by_name,
            "closed_by_id": self.closed_by_id,
            "closed_by_name": self.closed_by_name,
            "mention_map": mention_map_str,
        }
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "TicketTranscript":
        """Deserialize transcript from JSON string."""
        data = json.loads(json_str)
        messages = []
        for m in data.get("messages", []):
            attachments = [
                TicketTranscriptAttachment(**a) for a in m.get("attachments", [])
            ]
            messages.append(TicketTranscriptMessage(
                author_id=m["author_id"],
                author_name=m["author_name"],
                author_display_name=m["author_display_name"],
                author_avatar_url=m.get("author_avatar_url"),
                content=m["content"],
                timestamp=m["timestamp"],
                attachments=attachments,
                is_bot=m.get("is_bot", False),
                is_staff=m.get("is_staff", False),
            ))
        # Convert mention_map keys back to integers
        mention_map = None
        if data.get("mention_map"):
            mention_map = {int(k): v for k, v in data["mention_map"].items()}

        return cls(
            ticket_id=data["ticket_id"],
            thread_id=data["thread_id"],
            thread_name=data["thread_name"],
            category=data["category"],
            subject=data["subject"],
            status=data["status"],
            created_at=data["created_at"],
            closed_at=data.get("closed_at"),
            message_count=data["message_count"],
            messages=messages,
            user_id=data.get("user_id"),
            user_name=data.get("user_name"),
            claimed_by_id=data.get("claimed_by_id"),
            claimed_by_name=data.get("claimed_by_name"),
            closed_by_id=data.get("closed_by_id"),
            closed_by_name=data.get("closed_by_name"),
            mention_map=mention_map,
        )


__all__ = [
    "TicketTranscriptAttachment",
    "TicketTranscriptMessage",
    "TicketTranscript",
]
