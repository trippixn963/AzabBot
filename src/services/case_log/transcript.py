"""
AzabBot - Case Transcript Service
=================================

Handles building and storing transcripts of case threads before deletion.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List, Dict, Any

import discord

from src.core.logger import logger
from src.core.config import get_config, NY_TZ

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class TranscriptAttachment:
    """Represents an attachment in a transcript."""
    filename: str
    url: str  # Permanent URL after re-upload
    content_type: Optional[str] = None
    size: int = 0


@dataclass
class TranscriptEmbedField:
    """Represents a field in an embed."""
    name: str
    value: str
    inline: bool = False


@dataclass
class TranscriptEmbed:
    """Represents a Discord embed in a transcript."""
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
    fields: List[TranscriptEmbedField] = None

    def __post_init__(self):
        if self.fields is None:
            self.fields = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = {
            "title": self.title,
            "description": self.description,
            "color": self.color,
            "url": self.url,
            "image_url": self.image_url,
            "thumbnail_url": self.thumbnail_url,
            "author_name": self.author_name,
            "author_icon_url": self.author_icon_url,
            "footer_text": self.footer_text,
            "footer_icon_url": self.footer_icon_url,
            "fields": [asdict(f) for f in self.fields] if self.fields else [],
        }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TranscriptEmbed":
        """Create from dictionary."""
        fields = [
            TranscriptEmbedField(**f) for f in data.get("fields", [])
        ]
        return cls(
            title=data.get("title"),
            description=data.get("description"),
            color=data.get("color"),
            url=data.get("url"),
            image_url=data.get("image_url"),
            thumbnail_url=data.get("thumbnail_url"),
            author_name=data.get("author_name"),
            author_icon_url=data.get("author_icon_url"),
            footer_text=data.get("footer_text"),
            footer_icon_url=data.get("footer_icon_url"),
            fields=fields,
        )

    @classmethod
    def from_discord_embed(cls, embed: "discord.Embed") -> "TranscriptEmbed":
        """Create from a Discord embed object."""
        fields = []
        for field in embed.fields:
            fields.append(TranscriptEmbedField(
                name=field.name or "",
                value=field.value or "",
                inline=field.inline,
            ))

        return cls(
            title=embed.title,
            description=embed.description,
            color=embed.color.value if embed.color else None,
            url=embed.url,
            image_url=embed.image.url if embed.image else None,
            thumbnail_url=embed.thumbnail.url if embed.thumbnail else None,
            author_name=embed.author.name if embed.author else None,
            author_icon_url=embed.author.icon_url if embed.author else None,
            footer_text=embed.footer.text if embed.footer else None,
            footer_icon_url=embed.footer.icon_url if embed.footer else None,
            fields=fields,
        )


@dataclass
class TranscriptMessage:
    """Represents a single message in a transcript."""
    author_id: int
    author_name: str
    author_display_name: str
    author_avatar_url: Optional[str]
    content: str
    timestamp: float
    attachments: List[TranscriptAttachment]
    embeds: List[TranscriptEmbed] = None
    embeds_count: int = 0  # Kept for backwards compatibility
    is_pinned: bool = False

    def __post_init__(self):
        if self.embeds is None:
            self.embeds = []

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
            "embeds": [e.to_dict() for e in self.embeds] if self.embeds else [],
            "embeds_count": self.embeds_count,
            "is_pinned": self.is_pinned,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TranscriptMessage":
        """Create from dictionary."""
        attachments = [
            TranscriptAttachment(**a) for a in data.get("attachments", [])
        ]
        embeds = [
            TranscriptEmbed.from_dict(e) for e in data.get("embeds", [])
        ]
        return cls(
            author_id=data["author_id"],
            author_name=data["author_name"],
            author_display_name=data["author_display_name"],
            author_avatar_url=data.get("author_avatar_url"),
            content=data["content"],
            timestamp=data["timestamp"],
            attachments=attachments,
            embeds=embeds,
            embeds_count=data.get("embeds_count", 0),
            is_pinned=data.get("is_pinned", False),
        )


@dataclass
class Transcript:
    """Complete transcript of a case thread."""
    case_id: str
    thread_id: int
    thread_name: str
    created_at: float
    message_count: int
    messages: List[TranscriptMessage]
    target_user_id: Optional[int] = None
    target_user_name: Optional[str] = None
    moderator_id: Optional[int] = None
    moderator_name: Optional[str] = None

    def to_json(self) -> str:
        """Serialize transcript to JSON string."""
        data = {
            "case_id": self.case_id,
            "thread_id": self.thread_id,
            "thread_name": self.thread_name,
            "created_at": self.created_at,
            "message_count": self.message_count,
            "messages": [m.to_dict() for m in self.messages],
            "target_user_id": self.target_user_id,
            "target_user_name": self.target_user_name,
            "moderator_id": self.moderator_id,
            "moderator_name": self.moderator_name,
        }
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "Transcript":
        """Deserialize transcript from JSON string."""
        data = json.loads(json_str)
        messages = [
            TranscriptMessage.from_dict(m) for m in data.get("messages", [])
        ]
        return cls(
            case_id=data["case_id"],
            thread_id=data["thread_id"],
            thread_name=data["thread_name"],
            created_at=data["created_at"],
            message_count=data["message_count"],
            messages=messages,
            target_user_id=data.get("target_user_id"),
            target_user_name=data.get("target_user_name"),
            moderator_id=data.get("moderator_id"),
            moderator_name=data.get("moderator_name"),
        )


# =============================================================================
# Transcript Builder
# =============================================================================

class TranscriptBuilder:
    """
    Builds transcripts from Discord threads.

    Handles fetching messages, re-uploading attachments to permanent storage,
    and serializing the transcript for database storage.
    """

    def __init__(self, bot: "AzabBot", assets_thread_id: Optional[int] = None):
        self.bot = bot
        self.config = get_config()
        self.assets_thread_id = assets_thread_id or self.config.transcript_assets_thread_id

    async def build_from_thread(
        self,
        thread: discord.Thread,
        case_id: str,
        target_user_id: Optional[int] = None,
        target_user_name: Optional[str] = None,
        moderator_id: Optional[int] = None,
        moderator_name: Optional[str] = None,
    ) -> Optional[Transcript]:
        """
        Build a transcript from a Discord thread.

        Args:
            thread: The Discord thread to transcribe.
            case_id: The case ID for this transcript.
            target_user_id: ID of the target user (punished user).
            target_user_name: Display name of the target user.
            moderator_id: ID of the moderator who took the action.
            moderator_name: Display name of the moderator.

        Returns:
            Transcript object or None if failed.
        """
        try:
            logger.tree("Building Transcript", [
                ("Case ID", case_id),
                ("Thread ID", str(thread.id)),
                ("Thread Name", thread.name[:50] if thread.name else "Unknown"),
                ("Target User", f"{target_user_name} ({target_user_id})" if target_user_name else str(target_user_id)),
                ("Moderator", f"{moderator_name} ({moderator_id})" if moderator_name else str(moderator_id)),
            ], emoji="📝")

            messages: List[TranscriptMessage] = []
            pinned_ids = set()

            # Get pinned messages
            try:
                pinned = await thread.pins()
                pinned_ids = {m.id for m in pinned}
                logger.tree("Pinned Messages Fetched", [
                    ("Count", str(len(pinned_ids))),
                ], emoji="📌")
            except discord.HTTPException as e:
                logger.warning("Pinned Messages Fetch Failed", [
                    ("Case ID", case_id),
                    ("Thread ID", str(thread.id)),
                    ("Error", str(e)[:50]),
                ])

            # Fetch all messages (oldest first for chronological order)
            async for message in thread.history(limit=None, oldest_first=True):
                transcript_msg = await self._process_message(
                    message,
                    is_pinned=message.id in pinned_ids
                )
                if transcript_msg:
                    messages.append(transcript_msg)

            transcript = Transcript(
                case_id=case_id,
                thread_id=thread.id,
                thread_name=thread.name,
                created_at=thread.created_at.timestamp() if thread.created_at else datetime.now(NY_TZ).timestamp(),
                message_count=len(messages),
                messages=messages,
                target_user_id=target_user_id,
                target_user_name=target_user_name,
                moderator_id=moderator_id,
                moderator_name=moderator_name,
            )

            total_attachments = sum(len(m.attachments) for m in messages)
            total_embeds = sum(len(m.embeds) for m in messages)

            logger.tree("Transcript Built", [
                ("Case ID", case_id),
                ("Messages", str(len(messages))),
                ("Attachments", str(total_attachments)),
                ("Embeds", str(total_embeds)),
                ("Pinned", str(sum(1 for m in messages if m.is_pinned))),
            ], emoji="✅")

            return transcript

        except Exception as e:
            logger.error("Transcript Build Failed", [
                ("Case ID", case_id),
                ("Thread ID", str(thread.id)),
                ("Error", str(e)[:100]),
            ])
            return None

    async def _process_message(
        self,
        message: discord.Message,
        is_pinned: bool = False,
    ) -> Optional[TranscriptMessage]:
        """Process a single message into a TranscriptMessage."""
        try:
            # Re-upload attachments to permanent storage
            attachments = []
            for attachment in message.attachments:
                permanent = await self._reupload_attachment(attachment)
                if permanent:
                    attachments.append(permanent)

            # Extract embeds
            embeds = []
            for embed in message.embeds:
                try:
                    embeds.append(TranscriptEmbed.from_discord_embed(embed))
                except Exception as e:
                    logger.warning("Embed Extraction Failed", [
                        ("Message ID", str(message.id)),
                        ("Embed Title", str(embed.title)[:30] if embed.title else "None"),
                        ("Error", str(e)[:50]),
                    ])

            # Log if message has significant content
            if attachments or embeds:
                logger.tree("Message Processed", [
                    ("Author", message.author.name),
                    ("Attachments", str(len(attachments))),
                    ("Embeds", str(len(embeds))),
                    ("Pinned", "Yes" if is_pinned else "No"),
                ], emoji="💬")

            # Get avatar URL (use display_avatar which handles server avatars)
            avatar_url = None
            if message.author.display_avatar:
                avatar_url = message.author.display_avatar.url

            return TranscriptMessage(
                author_id=message.author.id,
                author_name=message.author.name,
                author_display_name=message.author.display_name,
                author_avatar_url=avatar_url,
                content=message.content or "",
                timestamp=message.created_at.timestamp(),
                attachments=attachments,
                embeds=embeds,
                embeds_count=len(message.embeds),
                is_pinned=is_pinned,
            )

        except discord.HTTPException as e:
            logger.warning("Message Process Failed (HTTP)", [
                ("Message ID", str(message.id)),
                ("Author", message.author.name if message.author else "Unknown"),
                ("Error", str(e)[:50]),
            ])
            return None
        except Exception as e:
            logger.warning("Message Process Failed", [
                ("Message ID", str(message.id)),
                ("Author", message.author.name if message.author else "Unknown"),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:50]),
            ])
            return None

    async def _reupload_attachment(
        self,
        attachment: discord.Attachment,
    ) -> Optional[TranscriptAttachment]:
        """
        Re-upload an attachment to the assets thread for permanent storage.

        Returns TranscriptAttachment with permanent URL, or None if failed.
        """
        if not self.assets_thread_id:
            # No assets thread configured, use original URL (may expire)
            logger.warning("No Assets Thread Configured", [
                ("Filename", attachment.filename),
                ("Using", "Original URL (may expire)"),
            ])
            return TranscriptAttachment(
                filename=attachment.filename,
                url=attachment.url,
                content_type=attachment.content_type,
                size=attachment.size,
            )

        try:
            # Get the assets thread
            assets_thread = self.bot.get_channel(self.assets_thread_id)
            if not assets_thread:
                assets_thread = await self.bot.fetch_channel(self.assets_thread_id)

            if not assets_thread or not isinstance(assets_thread, discord.Thread):
                logger.warning("Assets Thread Not Found", [
                    ("Thread ID", str(self.assets_thread_id)),
                ])
                return TranscriptAttachment(
                    filename=attachment.filename,
                    url=attachment.url,
                    content_type=attachment.content_type,
                    size=attachment.size,
                )

            # Download and re-upload
            file = await attachment.to_file()
            permanent_msg = await assets_thread.send(
                content=f"`{attachment.filename}`",
                file=file,
            )

            if permanent_msg.attachments:
                permanent_url = permanent_msg.attachments[0].url
                logger.tree("Attachment Reuploaded", [
                    ("Filename", attachment.filename),
                    ("Size", f"{attachment.size:,} bytes"),
                ], emoji="📎")
                return TranscriptAttachment(
                    filename=attachment.filename,
                    url=permanent_url,
                    content_type=attachment.content_type,
                    size=attachment.size,
                )

        except discord.HTTPException as e:
            logger.warning("Attachment Reupload Failed (HTTP)", [
                ("Filename", attachment.filename),
                ("Error", str(e)[:50]),
                ("Fallback", "Using original URL"),
            ])
        except Exception as e:
            logger.warning("Attachment Reupload Failed", [
                ("Filename", attachment.filename),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:50]),
                ("Fallback", "Using original URL"),
            ])

        # Fallback to original URL
        logger.tree("Using Original URL", [
            ("Filename", attachment.filename),
            ("Reason", "Reupload failed or no permanent URL"),
        ], emoji="⚠️")
        return TranscriptAttachment(
            filename=attachment.filename,
            url=attachment.url,
            content_type=attachment.content_type,
            size=attachment.size,
        )


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "TranscriptAttachment",
    "TranscriptMessage",
    "Transcript",
    "TranscriptBuilder",
]
