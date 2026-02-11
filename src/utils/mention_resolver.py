"""
AzabBot - Mention Resolver
==========================

Shared utility for collecting and resolving Discord mentions.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import Dict, List, Optional, Set, Any, TYPE_CHECKING

import discord

from src.core.logger import logger

if TYPE_CHECKING:
    from discord import Guild, Message


# Default limit for API lookups to prevent spam
DEFAULT_MAX_LOOKUPS = 10


async def collect_mentions_from_messages(
    messages: List["Message"],
    guild: Optional["Guild"],
    bot: discord.Client,
    max_api_lookups: int = DEFAULT_MAX_LOOKUPS,
) -> Dict[int, str]:
    """
    Collect and resolve all mentions from a list of Discord messages.

    Resolves:
    - User mentions (<@id> or <@!id>)
    - Channel mentions (<#id>)
    - Role mentions (<@&id>)

    Args:
        messages: List of Discord Message objects
        guild: The guild for member/role lookups
        bot: Bot client for user cache and API fetches
        max_api_lookups: Max API calls to make for unresolved users

    Returns:
        Dict mapping ID -> display name (users get name, channels get #name, roles get @name)
    """
    try:
        user_map: Dict[int, str] = {}
        channel_map: Dict[int, str] = {}
        role_map: Dict[int, str] = {}
        raw_mention_ids: Set[int] = set()

        # Collect role names from guild
        if guild:
            for role in guild.roles:
                role_map[role.id] = role.name

        # Process each message
        for msg in messages:
            # Collect message author
            user_map[msg.author.id] = msg.author.display_name

            # Collect mentioned users (Discord resolves these for us)
            for mentioned_user in msg.mentions:
                user_map[mentioned_user.id] = mentioned_user.display_name

            # Collect mentioned channels
            for mentioned_channel in msg.channel_mentions:
                channel_map[mentioned_channel.id] = mentioned_channel.name

            # Find raw mention IDs in content that weren't resolved
            if msg.content:
                raw_mentions = re.findall(r'<@!?(\d+)>', msg.content)
                for user_id_str in raw_mentions:
                    user_id = int(user_id_str)
                    if user_id not in user_map:
                        raw_mention_ids.add(user_id)

        # Resolve raw mention IDs
        api_resolved = 0
        if raw_mention_ids:
            resolved = await _resolve_user_ids(
                raw_mention_ids, guild, bot, max_api_lookups
            )
            api_resolved = len(resolved)
            user_map.update(resolved)

        # Build combined mention_map
        mention_map: Dict[int, str] = {**user_map}
        for channel_id, name in channel_map.items():
            mention_map[channel_id] = f"#{name}"
        for role_id, name in role_map.items():
            mention_map[role_id] = f"@{name}"

        logger.debug("Mentions Collected", [
            ("Messages", str(len(messages))),
            ("Users", str(len(user_map))),
            ("Channels", str(len(channel_map))),
            ("Roles", str(len(role_map))),
            ("API Resolved", str(api_resolved)),
        ])

        return mention_map

    except Exception as e:
        logger.error("Mention Collection Failed", [
            ("Messages", str(len(messages))),
            ("Error", str(e)[:100]),
        ])
        return {}


async def _resolve_user_ids(
    user_ids: Set[int],
    guild: Optional["Guild"],
    bot: discord.Client,
    max_api_lookups: int,
) -> Dict[int, str]:
    """
    Resolve user IDs to display names using cache and API.

    Priority:
    1. Guild member cache (no API call)
    2. Bot user cache (no API call)
    3. API fetch (limited)

    Args:
        user_ids: Set of user IDs to resolve
        guild: Guild for member lookup
        bot: Bot client for user cache and API
        max_api_lookups: Max API calls to make

    Returns:
        Dict mapping user_id -> display_name
    """
    resolved: Dict[int, str] = {}
    api_calls = 0
    cache_hits = 0
    not_found = 0

    for user_id in user_ids:
        # Try guild member cache first
        if guild:
            member = guild.get_member(user_id)
            if member:
                resolved[user_id] = member.display_name
                cache_hits += 1
                continue

        # Try bot's user cache
        cached_user = bot.get_user(user_id)
        if cached_user:
            resolved[user_id] = cached_user.display_name
            cache_hits += 1
            continue

        # API fetch (limited)
        if api_calls >= max_api_lookups:
            continue

        try:
            fetched_user = await bot.fetch_user(user_id)
            if fetched_user:
                resolved[user_id] = fetched_user.display_name
            api_calls += 1
        except discord.NotFound:
            api_calls += 1
            not_found += 1
        except discord.HTTPException as e:
            api_calls += 1
            logger.warning("User Fetch Failed", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:50]),
            ])

    if api_calls > 0:
        logger.debug("User IDs Resolved", [
            ("Total", str(len(user_ids))),
            ("Cache Hits", str(cache_hits)),
            ("API Calls", str(api_calls)),
            ("Not Found", str(not_found)),
        ])

    return resolved


def mention_map_to_json(mention_map: Dict[int, str]) -> Dict[str, str]:
    """Convert mention_map keys to strings for JSON serialization."""
    return {str(k): v for k, v in mention_map.items()}


__all__ = [
    "collect_mentions_from_messages",
    "mention_map_to_json",
]
