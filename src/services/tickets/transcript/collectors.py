"""
AzabBot - Ticket Transcript Collectors
======================================

Message collection and mention resolution for transcripts.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import html as html_lib
import re
from typing import List, Dict, Any, Tuple

import discord

from src.core.logger import logger
from src.utils.mention_resolver import collect_mentions_from_messages
from ..constants import MAX_TRANSCRIPT_MESSAGES, MAX_TRANSCRIPT_USER_LOOKUPS


async def collect_transcript_messages(
    thread: discord.Thread,
    bot: discord.Client,
    limit: int = MAX_TRANSCRIPT_MESSAGES,
) -> Tuple[List[Dict[str, Any]], Dict[int, str]]:
    """
    Collect messages from a ticket thread for transcript.

    Args:
        thread: The ticket thread
        bot: The bot client for API calls
        limit: Maximum number of messages to collect

    Returns:
        Tuple of (messages list, mention_map for mention resolution)
    """
    messages = []
    raw_messages: List[discord.Message] = []

    try:
        async for msg in thread.history(limit=limit, oldest_first=True):
            raw_messages.append(msg)

            attachments = [att.url for att in msg.attachments] if msg.attachments else []

            messages.append({
                "author": msg.author.display_name,
                "author_id": str(msg.author.id),
                "content": msg.content,
                "timestamp": msg.created_at.strftime("%b %d, %Y %I:%M %p"),
                "attachments": attachments,
                "avatar_url": str(msg.author.display_avatar.url) if msg.author.display_avatar else "",
                "is_bot": msg.author.bot,
                "is_staff": msg.author.guild_permissions.manage_messages if hasattr(msg.author, 'guild_permissions') else False,
            })

        # Use shared utility to collect and resolve mentions
        mention_map = await collect_mentions_from_messages(
            raw_messages,
            thread.guild,
            bot,
            max_api_lookups=MAX_TRANSCRIPT_USER_LOOKUPS,
        )

        logger.debug("Transcript Messages Collected", [
            ("Thread", f"{thread.name} ({thread.id})"),
            ("Messages", str(len(messages))),
            ("Mentions Mapped", str(len(mention_map))),
        ])

    except Exception as e:
        logger.error("Failed to collect transcript messages", [
            ("Thread", f"{thread.name} ({thread.id})"),
            ("Error", str(e)),
        ])
        mention_map = {}

    return messages, mention_map


def resolve_mentions(content: str, mention_map: Dict[int, str]) -> str:
    """
    Convert Discord mention syntax to readable names.

    Converts:
        <@123456789> or <@!123456789> -> @username
        <#123456789> -> #channel-name
        <@&123456789> -> @role-name

    Works with both raw and HTML-escaped content.
    """
    def replace_mention(match):
        mention_type = match.group(1)  # @, @!, #, or @&
        user_id = int(match.group(2))

        name = mention_map.get(user_id)
        if name:
            if mention_type in ('@', '@!'):
                return f'<span class="mention">@{html_lib.escape(name)}</span>'
            elif mention_type == '#':
                return f'<span class="mention channel">#{html_lib.escape(name)}</span>'
            elif mention_type == '@&':
                return f'<span class="mention role">@{html_lib.escape(name)}</span>'

        # Fallback: keep original but style it
        return f'<span class="mention unknown">&lt;{mention_type}{user_id}&gt;</span>'

    # Match user mentions <@123> or <@!123>, channel mentions <#123>, role mentions <@&123>
    # First try raw format
    pattern = r'<(@!?|#|@&)(\d+)>'
    result = re.sub(pattern, replace_mention, content)

    # Also match HTML-escaped format: &lt;@123&gt;
    escaped_pattern = r'&lt;(@!?|#|@&amp;)(\d+)&gt;'
    def replace_escaped_mention(match):
        mention_type = match.group(1).replace('&amp;', '&')  # Unescape &amp; back to &
        user_id = int(match.group(2))

        name = mention_map.get(user_id)
        if name:
            if mention_type in ('@', '@!'):
                return f'<span class="mention">@{html_lib.escape(name)}</span>'
            elif mention_type == '#':
                return f'<span class="mention channel">#{html_lib.escape(name)}</span>'
            elif mention_type == '@&':
                return f'<span class="mention role">@{html_lib.escape(name)}</span>'

        # Fallback: keep original but style it
        return f'<span class="mention unknown">&lt;{mention_type}{user_id}&gt;</span>'

    result = re.sub(escaped_pattern, replace_escaped_mention, result)

    return result


__all__ = [
    "collect_transcript_messages",
    "resolve_mentions",
]
