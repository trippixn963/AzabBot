"""
AzabBot - Ticket JSON Transcript Builder
========================================

Builds JSON transcripts for web viewer.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import Optional, List

import discord

from src.core.logger import logger
from src.utils.mention_resolver import collect_mentions_from_messages
from ..constants import MAX_TRANSCRIPT_MESSAGES, MAX_TRANSCRIPT_USER_LOOKUPS
from .models import (
    TicketTranscript,
    TicketTranscriptMessage,
    TicketTranscriptAttachment,
    TicketTranscriptEmbed,
    TicketTranscriptReaction,
    TicketTranscriptReplyTo,
    TicketTranscriptSticker,
)


async def build_json_transcript(
    thread: discord.Thread,
    ticket: dict,
    bot: discord.Client,
    user: Optional[discord.User] = None,
    claimed_by: Optional[discord.Member] = None,
    closed_by: Optional[discord.Member] = None,
) -> Optional[TicketTranscript]:
    """
    Build a JSON transcript from a ticket thread for web viewer.

    Args:
        thread: The ticket thread
        ticket: Ticket data from database
        bot: The bot client for API calls
        user: The ticket creator
        claimed_by: Staff member who claimed the ticket
        closed_by: Staff member who closed the ticket

    Returns:
        TicketTranscript object or None if failed
    """
    try:
        logger.tree("Building Ticket JSON Transcript", [
            ("Ticket ID", ticket.get("ticket_id", "Unknown")),
            ("Thread ID", str(thread.id)),
            ("Thread Name", thread.name[:50] if thread.name else "Unknown"),
        ], emoji="📝")

        messages: List[TicketTranscriptMessage] = []
        raw_messages: List[discord.Message] = []

        async for msg in thread.history(limit=MAX_TRANSCRIPT_MESSAGES, oldest_first=True):
            raw_messages.append(msg)

            # Build attachments
            attachments = []
            for att in msg.attachments:
                attachments.append(TicketTranscriptAttachment(
                    filename=att.filename,
                    url=att.url,
                    content_type=att.content_type,
                    size=att.size,
                ))

            # Build embeds
            embeds = []
            for embed in msg.embeds:
                embeds.append(TicketTranscriptEmbed(
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
                    fields=[
                        {"name": f.name, "value": f.value, "inline": f.inline}
                        for f in embed.fields
                    ] if embed.fields else None,
                ))

            # Build reactions
            reactions = []
            for reaction in msg.reactions:
                emoji_str = str(reaction.emoji)
                emoji_id = None
                emoji_name = None
                is_animated = False
                if hasattr(reaction.emoji, 'id'):
                    emoji_id = str(reaction.emoji.id) if reaction.emoji.id else None
                    emoji_name = reaction.emoji.name
                    is_animated = getattr(reaction.emoji, 'animated', False)
                reactions.append(TicketTranscriptReaction(
                    emoji=emoji_str,
                    emoji_id=emoji_id,
                    emoji_name=emoji_name,
                    count=reaction.count,
                    is_animated=is_animated,
                ))

            # Build reply reference
            reply_to = None
            if msg.reference and msg.reference.message_id:
                ref_msg = msg.reference.resolved
                if ref_msg and isinstance(ref_msg, discord.Message):
                    reply_to = TicketTranscriptReplyTo(
                        message_id=str(ref_msg.id),
                        author_name=ref_msg.author.display_name,
                        content=ref_msg.content[:100] if ref_msg.content else "",
                    )

            # Build stickers
            stickers = []
            for sticker in msg.stickers:
                stickers.append(TicketTranscriptSticker(
                    id=str(sticker.id),
                    name=sticker.name,
                    format_type=sticker.format.value if hasattr(sticker.format, 'value') else 1,
                ))

            # Get role color
            author_role_color = None
            if hasattr(msg.author, 'top_role') and msg.author.top_role:
                color = msg.author.top_role.color
                if color and color.value != 0:
                    author_role_color = f"#{color.value:06x}"

            # Check if staff
            is_staff = False
            if hasattr(msg.author, 'guild_permissions'):
                is_staff = msg.author.guild_permissions.manage_messages

            # Determine message type
            msg_type = "default"
            if msg.type == discord.MessageType.reply:
                msg_type = "reply"
            elif msg.type == discord.MessageType.new_member:
                msg_type = "join"
            elif msg.type == discord.MessageType.premium_guild_subscription:
                msg_type = "boost"
            elif msg.type == discord.MessageType.pins_add:
                msg_type = "pin"
            elif msg.type == discord.MessageType.thread_starter_message:
                msg_type = "thread_starter"

            messages.append(TicketTranscriptMessage(
                author_id=msg.author.id,
                author_name=msg.author.name,
                author_display_name=msg.author.display_name,
                author_avatar_url=str(msg.author.display_avatar.url) if msg.author.display_avatar else None,
                author_role_color=author_role_color,
                content=msg.content,
                timestamp=msg.created_at.timestamp(),
                attachments=attachments,
                embeds=embeds,
                reactions=reactions,
                reply_to=reply_to,
                stickers=stickers,
                is_bot=msg.author.bot,
                is_staff=is_staff,
                is_pinned=msg.pinned,
                is_edited=msg.edited_at is not None,
                edited_at=msg.edited_at.timestamp() if msg.edited_at else None,
                type=msg_type,
            ))

        # Use shared utility to collect and resolve mentions
        mention_map = await collect_mentions_from_messages(
            raw_messages,
            thread.guild,
            bot,
            max_api_lookups=MAX_TRANSCRIPT_USER_LOOKUPS,
        )

        transcript = TicketTranscript(
            ticket_id=ticket.get("ticket_id", ""),
            thread_id=thread.id,
            thread_name=thread.name,
            category=ticket.get("category", "support"),
            subject=ticket.get("subject", ""),
            status=ticket.get("status", "closed"),
            created_at=ticket.get("created_at", time.time()),
            closed_at=ticket.get("closed_at"),
            message_count=len(messages),
            messages=messages,
            user_id=user.id if user else ticket.get("user_id"),
            user_name=user.display_name if user else None,
            claimed_by_id=claimed_by.id if claimed_by else ticket.get("claimed_by"),
            claimed_by_name=claimed_by.display_name if claimed_by else None,
            closed_by_id=closed_by.id if closed_by else ticket.get("closed_by"),
            closed_by_name=closed_by.display_name if closed_by else None,
            mention_map=mention_map,
        )

        logger.tree("Ticket JSON Transcript Built", [
            ("Ticket ID", ticket.get("ticket_id", "Unknown")),
            ("Messages", str(len(messages))),
            ("User", f"{transcript.user_name} ({transcript.user_id})"),
        ], emoji="✅")

        return transcript

    except Exception as e:
        logger.error("Ticket JSON Transcript Build Failed", [
            ("Ticket ID", ticket.get("ticket_id", "Unknown")),
            ("Thread ID", str(thread.id)),
            ("Error", str(e)[:100]),
        ])
        return None


__all__ = ["build_json_transcript"]
