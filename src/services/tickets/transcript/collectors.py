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
from src.utils.discord_rate_limit import log_http_error
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
        Tuple of (messages list, user_map for mention resolution)
    """
    messages = []
    user_map: Dict[int, str] = {}  # user_id -> display_name
    channel_map: Dict[int, str] = {}  # channel_id -> name
    role_map: Dict[int, str] = {}  # role_id -> name
    raw_mention_ids: set = set()  # IDs found in raw text that need resolution

    try:
        # Collect role names from guild
        if thread.guild:
            for role in thread.guild.roles:
                role_map[role.id] = role.name

        async for msg in thread.history(limit=limit, oldest_first=True):
            attachments = [att.url for att in msg.attachments] if msg.attachments else []

            # Collect user info for mention resolution
            user_map[msg.author.id] = msg.author.display_name

            # Collect mentioned users
            for mentioned_user in msg.mentions:
                user_map[mentioned_user.id] = mentioned_user.display_name

            # Collect mentioned channels
            for mentioned_channel in msg.channel_mentions:
                channel_map[mentioned_channel.id] = mentioned_channel.name

            # Find raw mention-like text in content (e.g., <@123456789>)
            if msg.content:
                raw_mentions = re.findall(r'<@!?(\d+)>', msg.content)
                for user_id_str in raw_mentions:
                    user_id = int(user_id_str)
                    if user_id not in user_map:
                        raw_mention_ids.add(user_id)

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

        # Resolve raw mention IDs to usernames (limited to prevent API spam)
        if raw_mention_ids and thread.guild:
            api_calls = 0
            for user_id in raw_mention_ids:
                # Try to get member from guild cache first (no API call)
                member = thread.guild.get_member(user_id)
                if member:
                    user_map[user_id] = member.display_name
                    continue

                # Try bot's user cache (no API call)
                cached_user = bot.get_user(user_id)
                if cached_user:
                    user_map[user_id] = cached_user.display_name
                    continue

                # Only make API call if under limit
                if api_calls >= MAX_TRANSCRIPT_USER_LOOKUPS:
                    continue  # Leave unresolved, don't spam API

                try:
                    user = await bot.fetch_user(user_id)
                    if user:
                        user_map[user_id] = user.display_name
                    api_calls += 1
                except discord.NotFound:
                    api_calls += 1  # Count failed lookups too
                except discord.HTTPException as e:
                    api_calls += 1
                    log_http_error(e, "Transcript User Fetch", [
                        ("User ID", str(user_id)),
                    ])

    except Exception as e:
        logger.error("Failed to collect transcript messages", [
            ("Thread", f"{thread.name} ({thread.id})"),
            ("Error", str(e)),
        ])

    # Merge channel and role maps into user_map with prefixes
    mention_map = {**user_map}
    for channel_id, name in channel_map.items():
        mention_map[channel_id] = f"#{name}"
    for role_id, name in role_map.items():
        mention_map[role_id] = f"@{name}"

    logger.debug("Transcript Messages Collected", [
        ("Thread", f"{thread.name} ({thread.id})"),
        ("Messages", str(len(messages))),
        ("Users Mapped", str(len(user_map))),
        ("Channels Mapped", str(len(channel_map))),
        ("Roles Mapped", str(len(role_map))),
    ])

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
