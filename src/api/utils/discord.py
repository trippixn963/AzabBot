"""
AzabBot - Discord API Utilities
================================

Shared utilities for Discord user fetching with caching.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.core.logger import logger


# =============================================================================
# User Info Cache
# =============================================================================

# Simple TTL cache for user info: {user_id: (name, avatar, expires_at)}
_user_cache: Dict[int, Tuple[str, Optional[str], float]] = {}
_CACHE_TTL = 300  # 5 minutes


def _get_cached_user(user_id: int) -> Optional[Tuple[str, Optional[str]]]:
    """Get user from cache if not expired."""
    if user_id in _user_cache:
        name, avatar, expires_at = _user_cache[user_id]
        if time.time() < expires_at:
            return (name, avatar)
        # Expired, remove it
        try:
            del _user_cache[user_id]
        except KeyError:
            pass
    return None


def _cache_user(user_id: int, name: str, avatar: Optional[str]) -> None:
    """Store user info in cache."""
    _user_cache[user_id] = (name, avatar, time.time() + _CACHE_TTL)


def clear_user_cache() -> None:
    """Clear the entire user cache."""
    _user_cache.clear()


# =============================================================================
# User Fetching
# =============================================================================

async def fetch_user_info(bot: Any, user_id: int) -> Tuple[int, Optional[str], Optional[str]]:
    """
    Fetch user info with timeout protection.

    Returns: (user_id, username, avatar_url)
    """
    # Check cache first
    cached = _get_cached_user(user_id)
    if cached:
        return (user_id, cached[0], cached[1])

    try:
        user = await asyncio.wait_for(bot.fetch_user(user_id), timeout=2.0)
        if user:
            avatar = str(user.display_avatar.url) if user.display_avatar else None
            _cache_user(user_id, user.name, avatar)
            return (user_id, user.name, avatar)
    except asyncio.TimeoutError:
        logger.debug("User Fetch Timeout", [("User ID", str(user_id))])
    except Exception:
        pass

    return (user_id, None, None)


async def batch_fetch_users(bot: Any, user_ids: List[int]) -> Dict[int, Tuple[str, Optional[str]]]:
    """
    Fetch multiple users in parallel with caching and timeouts.

    1. Checks local cache first
    2. Checks guild member cache
    3. Fetches remaining from Discord API (max 10 concurrent)

    Returns: {user_id: (username, avatar_url)}
    """
    if not bot or not user_ids:
        return {}

    user_info: Dict[int, Tuple[str, Optional[str]]] = {}
    remaining_ids: List[int] = []

    # Check local cache first
    for uid in user_ids:
        cached = _get_cached_user(uid)
        if cached:
            user_info[uid] = cached
        else:
            remaining_ids.append(uid)

    if not remaining_ids:
        return user_info

    # Check guild member cache
    guild = None
    if hasattr(bot, 'config') and bot.config.logging_guild_id:
        guild = bot.get_guild(bot.config.logging_guild_id)

    still_remaining: List[int] = []
    for uid in remaining_ids:
        if guild:
            member = guild.get_member(uid)
            if member:
                avatar = str(member.display_avatar.url) if member.display_avatar else None
                user_info[uid] = (member.name, avatar)
                _cache_user(uid, member.name, avatar)
                continue
        still_remaining.append(uid)

    # Fetch remaining users in parallel (max 10 concurrent)
    if still_remaining:
        semaphore = asyncio.Semaphore(10)

        async def fetch_with_semaphore(uid: int) -> Tuple[int, Optional[str], Optional[str]]:
            async with semaphore:
                return await fetch_user_info(bot, uid)

        results = await asyncio.gather(
            *[fetch_with_semaphore(uid) for uid in still_remaining],
            return_exceptions=True
        )

        for result in results:
            if isinstance(result, tuple) and len(result) == 3:
                uid, name, avatar = result
                if name:
                    user_info[uid] = (name, avatar)

    return user_info


# =============================================================================
# Timestamp Helpers
# =============================================================================

def to_iso_string(timestamp: Optional[float]) -> Optional[str]:
    """Convert Unix timestamp to ISO 8601 string with Z suffix."""
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def format_duration(seconds: Optional[int]) -> Optional[str]:
    """Format duration in seconds to human readable string (e.g., '2h', '7d')."""
    if not seconds:
        return None

    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m"
    elif seconds < 86400:
        return f"{seconds // 3600}h"
    else:
        return f"{seconds // 86400}d"


def format_relative_time(timestamp: float, now: Optional[float] = None) -> str:
    """Format timestamp as relative time (e.g., '5m ago', '2h ago')."""
    if now is None:
        now = time.time()

    diff = now - timestamp

    if diff < 60:
        return "just now"
    elif diff < 3600:
        return f"{int(diff // 60)}m ago"
    elif diff < 86400:
        return f"{int(diff // 3600)}h ago"
    else:
        return f"{int(diff // 86400)}d ago"


# =============================================================================
# Status Helpers
# =============================================================================

def calculate_case_status(
    status: str,
    duration_seconds: Optional[int] = None,
    created_at: Optional[float] = None,
    now: Optional[float] = None
) -> str:
    """
    Return case status from database.

    The database status is kept accurate by the CaseArchiveScheduler,
    which marks expired cases periodically. This function now just
    returns the raw status.

    Note: duration_seconds, created_at, and now params kept for
    backwards compatibility but are no longer used.
    """
    return status


def calculate_expires_at(
    duration_seconds: Optional[int],
    created_at: Optional[float]
) -> Optional[str]:
    """Calculate expiration timestamp as ISO string."""
    if not duration_seconds or not created_at:
        return None
    return to_iso_string(created_at + duration_seconds)


__all__ = [
    "fetch_user_info",
    "batch_fetch_users",
    "clear_user_cache",
    "to_iso_string",
    "format_duration",
    "format_relative_time",
    "calculate_case_status",
    "calculate_expires_at",
]
