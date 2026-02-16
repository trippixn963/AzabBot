"""
AzabBot - Ticket Transcript Models
==================================

Data classes for ticket transcript serialization.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any


@dataclass
class TicketTranscriptAttachment:
    """Represents an attachment in a ticket transcript."""
    filename: str
    url: str
    content_type: Optional[str] = None
    size: int = 0


@dataclass
class TicketTranscriptEmbed:
    """Represents an embed in a ticket transcript."""
    title: Optional[str] = None
    description: Optional[str] = None
    color: Optional[int] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    author_name: Optional[str] = None
    author_icon_url: Optional[str] = None
    footer_text: Optional[str] = None
    footer_icon_url: Optional[str] = None
    fields: Optional[List[Dict[str, Any]]] = None


@dataclass
class TicketTranscriptReaction:
    """Represents a reaction on a message."""
    emoji: str  # Unicode emoji or custom emoji name
    emoji_id: Optional[str] = None  # Custom emoji ID
    emoji_name: Optional[str] = None  # Custom emoji name
    count: int = 1
    is_animated: bool = False


@dataclass
class TicketTranscriptReplyTo:
    """Represents a reply reference."""
    message_id: str
    author_name: str
    content: str  # Truncated preview


@dataclass
class TicketTranscriptSticker:
    """Represents a Discord sticker."""
    id: str
    name: str
    format_type: int  # 1=PNG, 2=APNG, 3=Lottie, 4=GIF


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
    embeds: List[TicketTranscriptEmbed] = field(default_factory=list)
    reactions: List[TicketTranscriptReaction] = field(default_factory=list)
    reply_to: Optional[TicketTranscriptReplyTo] = None
    stickers: List[TicketTranscriptSticker] = field(default_factory=list)
    author_role_color: Optional[str] = None  # Hex color like "#ff0000"
    is_bot: bool = False
    is_staff: bool = False
    is_pinned: bool = False
    is_edited: bool = False
    edited_at: Optional[float] = None
    type: str = "default"  # default, reply, join, boost, pin, thread_starter

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "author_id": self.author_id,
            "author_name": self.author_name,
            "author_display_name": self.author_display_name,
            "author_avatar_url": self.author_avatar_url,
            "author_role_color": self.author_role_color,
            "content": self.content,
            "timestamp": self.timestamp,
            "attachments": [asdict(a) for a in self.attachments],
            "embeds": [asdict(e) for e in self.embeds] if self.embeds else [],
            "reactions": [asdict(r) for r in self.reactions] if self.reactions else [],
            "reply_to": asdict(self.reply_to) if self.reply_to else None,
            "stickers": [asdict(s) for s in self.stickers] if self.stickers else [],
            "is_bot": self.is_bot,
            "is_staff": self.is_staff,
            "is_pinned": self.is_pinned,
            "is_edited": self.is_edited,
            "edited_at": self.edited_at,
            "type": self.type,
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
            embeds = [
                TicketTranscriptEmbed(**e) for e in m.get("embeds", [])
            ]
            reactions = [
                TicketTranscriptReaction(**r) for r in m.get("reactions", [])
            ]
            stickers = [
                TicketTranscriptSticker(**s) for s in m.get("stickers", [])
            ]
            reply_to = None
            if m.get("reply_to"):
                reply_to = TicketTranscriptReplyTo(**m["reply_to"])

            messages.append(TicketTranscriptMessage(
                author_id=m["author_id"],
                author_name=m["author_name"],
                author_display_name=m["author_display_name"],
                author_avatar_url=m.get("author_avatar_url"),
                author_role_color=m.get("author_role_color"),
                content=m["content"],
                timestamp=m["timestamp"],
                attachments=attachments,
                embeds=embeds,
                reactions=reactions,
                reply_to=reply_to,
                stickers=stickers,
                is_bot=m.get("is_bot", False),
                is_staff=m.get("is_staff", False),
                is_pinned=m.get("is_pinned", False),
                is_edited=m.get("is_edited", False),
                edited_at=m.get("edited_at"),
                type=m.get("type", "default"),
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
    "TicketTranscriptEmbed",
    "TicketTranscriptReaction",
    "TicketTranscriptReplyTo",
    "TicketTranscriptSticker",
    "TicketTranscriptMessage",
    "TicketTranscript",
]
