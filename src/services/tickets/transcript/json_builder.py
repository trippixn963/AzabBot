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
from .models import TicketTranscript, TicketTranscriptMessage, TicketTranscriptAttachment


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

            # Check if staff
            is_staff = False
            if hasattr(msg.author, 'guild_permissions'):
                is_staff = msg.author.guild_permissions.manage_messages

            messages.append(TicketTranscriptMessage(
                author_id=msg.author.id,
                author_name=msg.author.name,
                author_display_name=msg.author.display_name,
                author_avatar_url=str(msg.author.display_avatar.url) if msg.author.display_avatar else None,
                content=msg.content,
                timestamp=msg.created_at.timestamp(),
                attachments=attachments,
                is_bot=msg.author.bot,
                is_staff=is_staff,
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
