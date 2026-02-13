"""
AzabBot - User Lookup Helpers
=============================

Helper functions for user data fetching and processing.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import Any, List, Optional

import aiohttp
import discord

from src.core.logger import logger
from .models import UserRole


# SyriaBot API for activity stats
SYRIABOT_API_URL = "http://localhost:8088/api/syria/user"


async def fetch_syriabot_data(user_id: int) -> Optional[dict]:
    """Fetch user activity data from SyriaBot API (includes channels)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SYRIABOT_API_URL}/{user_id}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        logger.warning("SyriaBot API Fetch Failed", [
            ("User ID", str(user_id)),
            ("Error Type", type(e).__name__),
            ("Error", str(e)[:50]),
        ])
    return None


def get_previous_usernames(db, user_id: int, limit: int = 10) -> List[str]:
    """Get user's previous usernames from history."""
    rows = db.fetchall(
        """
        SELECT DISTINCT username FROM username_history
        WHERE user_id = ? AND username IS NOT NULL
        ORDER BY changed_at DESC
        LIMIT ?
        """,
        (user_id, limit)
    )
    return [row[0] for row in rows if row[0]]


def get_invite_info(db, user_id: int, guild_id: int) -> tuple[Optional[str], Optional[int]]:
    """Get invite code and inviter ID for a user."""
    row = db.fetchone(
        """
        SELECT invite_code, inviter_id FROM user_join_info
        WHERE user_id = ? AND guild_id = ?
        """,
        (user_id, guild_id)
    )
    if row:
        return row[0], row[1]
    return None, None


def get_user_roles(member: Optional[discord.Member]) -> List[UserRole]:
    """Get user's roles sorted by position."""
    if not member:
        return []

    roles = []
    for role in sorted(member.roles, key=lambda r: r.position, reverse=True):
        if role.name == "@everyone":
            continue
        color_hex = f"#{role.color.value:06x}" if role.color.value else "#99aab5"
        roles.append(UserRole(
            id=str(role.id),
            name=role.name,
            color=color_hex,
            position=role.position,
        ))
    return roles


def roles_from_snapshot(snapshot: dict) -> List[UserRole]:
    """Convert snapshot roles to UserRole list."""
    roles = []
    for role_data in snapshot.get("roles", []):
        roles.append(UserRole(
            id=role_data.get("id", "0"),
            name=role_data.get("name", "Unknown"),
            color=role_data.get("color", "#99aab5"),
            position=role_data.get("position", 0),
        ))
    return roles


async def batch_fetch_moderators(bot: Any, mod_ids: set[int]) -> dict[int, str]:
    """
    Batch fetch moderator names. Returns dict of mod_id -> username.
    Uses bot cache first, then fetches missing ones concurrently.
    """
    result = {}
    to_fetch = []

    # First pass: check bot cache
    for mod_id in mod_ids:
        cached = bot.get_user(mod_id)
        if cached:
            result[mod_id] = cached.name
        else:
            to_fetch.append(mod_id)

    # Fetch missing ones concurrently (max 10 at a time to avoid rate limits)
    if to_fetch:
        async def fetch_one(uid: int) -> tuple[int, Optional[str]]:
            try:
                user = await bot.fetch_user(uid)
                return (uid, user.name if user else None)
            except (discord.NotFound, discord.HTTPException):
                return (uid, None)

        # Batch in groups of 10
        for i in range(0, len(to_fetch), 10):
            batch = to_fetch[i:i+10]
            fetched = await asyncio.gather(*[fetch_one(uid) for uid in batch])
            for uid, name in fetched:
                if name:
                    result[uid] = name

    if to_fetch:
        logger.debug("Moderators Batch Fetched", [
            ("Requested", str(len(to_fetch))),
            ("Resolved", str(len([uid for uid in to_fetch if uid in result]))),
        ])

    return result


__all__ = [
    "SYRIABOT_API_URL",
    "fetch_syriabot_data",
    "get_previous_usernames",
    "get_invite_info",
    "get_user_roles",
    "roles_from_snapshot",
    "batch_fetch_moderators",
]
