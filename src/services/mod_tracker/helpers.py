"""
Mod Tracker Service - Helpers
=============================

Data classes and utility functions for the mod tracker service.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple, Callable, Any
import asyncio
import re

import discord

from .constants import MAX_RETRIES, BASE_RETRY_DELAY


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class CachedMessage:
    """Cached message with downloaded attachments."""
    message_id: int
    author_id: int
    channel_id: int
    content: str
    cached_at: datetime
    attachments: List[Tuple[str, bytes]] = field(default_factory=list)  # (filename, data)


@dataclass(order=True)
class QueueItem:
    """Item in the priority queue for mod tracker messages."""
    priority: int
    timestamp: float = field(compare=False)
    thread_id: int = field(compare=False)
    content: Optional[str] = field(compare=False, default=None)
    embed: discord.Embed = field(compare=False, default=None)
    view: Optional[discord.ui.View] = field(compare=False, default=None)
    is_alert: bool = field(compare=False, default=False)


# =============================================================================
# Emoji Handling
# =============================================================================

# Regex pattern to match ONLY standard emojis (not custom fonts)
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Misc Symbols and Pictographs
    "\U0001F680-\U0001F6FF"  # Transport and Map
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
    "\U0001FA00-\U0001FA6F"  # Chess Symbols
    "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
    "\U00002702-\U000027B0"  # Dingbats
    "\U0001F1E0-\U0001F1FF"  # Flags
    "]+",
    flags=re.UNICODE,
)


def strip_emojis(text: str) -> str:
    """
    Remove standard emojis from text, keeping custom fonts.

    Args:
        text: Input string that may contain emojis.

    Returns:
        String with emojis removed but custom fonts preserved.
    """
    cleaned = EMOJI_PATTERN.sub("", text)
    cleaned = " ".join(cleaned.split())
    return cleaned.strip()


# =============================================================================
# Async Retry Helper
# =============================================================================

async def retry_async(
    coro_func: Callable,
    *args,
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_RETRY_DELAY,
    **kwargs,
) -> Any:
    """
    Retry an async function with exponential backoff.

    Args:
        coro_func: Async function to retry.
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay between retries (doubles each retry).

    Returns:
        Result of the function call.

    Raises:
        Last exception if all retries fail.
    """
    last_exception = None
    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except discord.HTTPException as e:
            last_exception = e
            if e.status == 429:  # Rate limited
                retry_after = getattr(e, 'retry_after', base_delay * (2 ** attempt))
                await asyncio.sleep(retry_after)
            elif e.status >= 500:  # Server error, retry
                await asyncio.sleep(base_delay * (2 ** attempt))
            else:
                raise  # Client error, don't retry
        except (asyncio.TimeoutError, ConnectionError) as e:
            last_exception = e
            await asyncio.sleep(base_delay * (2 ** attempt))
    raise last_exception
