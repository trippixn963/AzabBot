"""
Unified Discord Rate Limit Utilities
=====================================

Rate limit handling for Discord API operations.

Features:
- Automatic retry on rate limit (429) errors
- Respects Discord's retry_after header
- Exponential backoff for other errors
- Decorator for easy function wrapping
- Helper functions for common operations with delays

Usage:
    from src.utils.discord_rate_limit import (
        add_reactions_with_delay,
        send_message_with_retry,
        edit_message_with_retry,
        with_rate_limit_retry,
    )

    # Using helper functions
    await add_reactions_with_delay(message, ["👍", "👎"])
    msg = await send_message_with_retry(channel, "Hello!")

    # Using decorator
    @with_rate_limit_retry()
    async def my_discord_operation():
        await channel.send("Test")

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import random
from functools import wraps
from typing import Any, Callable, List, Optional, Union

import discord

from src.core.logger import logger


# =============================================================================
# Configuration
# =============================================================================

class RateLimitConfig:
    """Configuration for Discord rate limit handling."""
    MAX_RETRIES: int = 3
    BASE_DELAY: float = 1.0  # seconds
    MAX_DELAY: float = 30.0  # seconds
    REACTION_DELAY: float = 0.3  # delay between reactions (300ms)
    MESSAGE_DELAY: float = 0.5  # delay between messages (500ms)


# Module-level constants for backwards compatibility
MAX_RETRIES = RateLimitConfig.MAX_RETRIES
BASE_DELAY = RateLimitConfig.BASE_DELAY
MAX_DELAY = RateLimitConfig.MAX_DELAY
REACTION_DELAY = RateLimitConfig.REACTION_DELAY


# HTTP status code descriptions for logging
HTTP_STATUS_DESCRIPTIONS = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    429: "Rate Limited",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


# =============================================================================
# Logging Helper
# =============================================================================

def log_http_error(
    e: discord.HTTPException,
    operation: str,
    context: Optional[list] = None,
) -> None:
    """
    Log a Discord HTTPException with comprehensive details.

    Args:
        e: The HTTPException that occurred
        operation: Description of what operation failed
        context: Additional context tuples for logging [(key, value), ...]
    """
    status_desc = HTTP_STATUS_DESCRIPTIONS.get(e.status, "Unknown")
    retry_after = getattr(e, 'retry_after', None)

    log_items = [
        ("Status", f"{e.status} ({status_desc})"),
        ("Error", str(e.text) if hasattr(e, 'text') and e.text else str(e)),
    ]

    if retry_after:
        log_items.append(("Retry After", f"{retry_after:.1f}s"))

    if context:
        log_items.extend(context)

    # Use warning for rate limits (recoverable), error for others
    if e.status == 429:
        logger.warning(f"🚦 {operation} Rate Limited", log_items)
    elif e.status == 403:
        logger.warning(f"🚫 {operation} Forbidden", log_items)
    elif e.status == 404:
        logger.warning(f"❓ {operation} Not Found", log_items)
    else:
        logger.error(f"❌ {operation} Failed", log_items)


# =============================================================================
# Rate Limit Decorator
# =============================================================================

def with_rate_limit_retry(
    max_retries: int = RateLimitConfig.MAX_RETRIES,
    base_delay: float = RateLimitConfig.BASE_DELAY,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that handles Discord rate limits with automatic retry.

    Args:
        max_retries: Maximum retry attempts
        base_delay: Base delay for exponential backoff

    Returns:
        Decorated function with rate limit handling

    Example:
        @with_rate_limit_retry()
        async def send_notification(channel, content):
            await channel.send(content)
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)

                except discord.RateLimited as e:
                    # Raised when rate limit exceeds bot's max_ratelimit_timeout
                    last_exception = e
                    delay = e.retry_after + 0.5  # Add buffer

                    logger.warning("Discord Rate Limited", [
                        ("Function", func.__name__),
                        ("Attempt", f"{attempt + 1}/{max_retries}"),
                        ("Retry After", f"{delay:.1f}s"),
                    ])

                    if attempt < max_retries - 1 and delay < RateLimitConfig.MAX_DELAY:
                        await asyncio.sleep(delay)
                        continue
                    raise

                except discord.HTTPException as e:
                    last_exception = e

                    # Rate limited (429)
                    if e.status == 429:
                        retry_after = getattr(e, 'retry_after', None)
                        if retry_after:
                            delay = retry_after + 0.5
                        else:
                            delay = min(base_delay * (2 ** attempt), RateLimitConfig.MAX_DELAY)

                        logger.warning("Discord Rate Limited", [
                            ("Function", func.__name__),
                            ("Attempt", f"{attempt + 1}/{max_retries}"),
                            ("Retry After", f"{delay:.1f}s"),
                        ])

                        if attempt < max_retries - 1:
                            await asyncio.sleep(delay)
                            continue

                    # Other HTTP errors - exponential backoff with jitter
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), RateLimitConfig.MAX_DELAY)
                        delay += random.uniform(0, delay * 0.1)  # Add jitter
                        logger.warning("Discord API Error", [
                            ("Function", func.__name__),
                            ("Attempt", f"{attempt + 1}/{max_retries}"),
                            ("Status", str(e.status)),
                            ("Retry In", f"{delay:.1f}s"),
                        ])
                        await asyncio.sleep(delay)
                        continue

                    raise

                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), RateLimitConfig.MAX_DELAY)
                        delay += random.uniform(0, delay * 0.1)
                        await asyncio.sleep(delay)
                        continue
                    raise

            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed without exception")

        return wrapper

    return decorator


# =============================================================================
# Helper Functions for Common Operations
# =============================================================================

async def add_reactions_with_delay(
    message: discord.Message,
    emojis: List[Union[str, discord.Emoji]],
    delay: float = RateLimitConfig.REACTION_DELAY,
) -> List[bool]:
    """
    Add multiple reactions to a message with delays between each.

    Args:
        message: The message to add reactions to
        emojis: List of emojis to add
        delay: Delay between reactions in seconds

    Returns:
        List of success status for each reaction
    """
    results = []

    for i, emoji in enumerate(emojis):
        try:
            await message.add_reaction(emoji)
            results.append(True)
        except discord.RateLimited as e:
            logger.warning("Rate Limited on Reaction", [
                ("Emoji", str(emoji)),
                ("Retry After", f"{e.retry_after:.1f}s"),
            ])
            if e.retry_after < RateLimitConfig.MAX_DELAY:
                await asyncio.sleep(e.retry_after + 0.5)
                try:
                    await message.add_reaction(emoji)
                    results.append(True)
                except (discord.RateLimited, discord.HTTPException):
                    results.append(False)
            else:
                results.append(False)
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = getattr(e, 'retry_after', None) or (delay * 2)
                await asyncio.sleep(retry_after)
                try:
                    await message.add_reaction(emoji)
                    results.append(True)
                except discord.HTTPException:
                    results.append(False)
            else:
                logger.warning("Failed to Add Reaction", [
                    ("Emoji", str(emoji)),
                    ("Error", str(e)),
                ])
                results.append(False)

        # Add delay before next reaction (except for last one)
        if i < len(emojis) - 1:
            await asyncio.sleep(delay)

    return results


async def send_message_with_retry(
    channel: Union[discord.TextChannel, discord.Thread, discord.VoiceChannel],
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    view: Optional[discord.ui.View] = None,
    max_retries: int = RateLimitConfig.MAX_RETRIES,
    **kwargs: Any,
) -> Optional[discord.Message]:
    """
    Send a message with automatic rate limit retry.

    Args:
        channel: Channel, thread, or voice channel to send to
        content: Message content
        embed: Optional embed
        view: Optional view
        max_retries: Maximum retry attempts
        **kwargs: Additional arguments to send()

    Returns:
        The sent message or None on failure
    """
    for attempt in range(max_retries):
        try:
            return await channel.send(
                content=content,
                embed=embed,
                view=view,
                **kwargs,
            )
        except discord.RateLimited as e:
            logger.warning("Rate Limited on Message Send", [
                ("Channel", str(channel.id)),
                ("Attempt", f"{attempt + 1}/{max_retries}"),
                ("Retry After", f"{e.retry_after:.1f}s"),
            ])
            if attempt < max_retries - 1 and e.retry_after < RateLimitConfig.MAX_DELAY:
                await asyncio.sleep(e.retry_after + 0.5)
                continue
            return None
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = getattr(e, 'retry_after', RateLimitConfig.BASE_DELAY * (2 ** attempt))
                logger.warning("Rate Limited on Message Send", [
                    ("Channel", str(channel.id)),
                    ("Attempt", f"{attempt + 1}/{max_retries}"),
                    ("Retry After", f"{retry_after:.1f}s"),
                ])
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_after + 0.5)
                    continue
            logger.error("Failed to Send Message", [
                ("Channel", str(channel.id)),
                ("Error", str(e)),
            ])
            return None
        except Exception as e:
            logger.error("Unexpected Error Sending Message", [
                ("Channel", str(channel.id)),
                ("Error", str(e)),
            ])
            return None

    return None


async def edit_message_with_retry(
    message: discord.Message,
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    max_retries: int = RateLimitConfig.MAX_RETRIES,
    **kwargs: Any,
) -> bool:
    """
    Edit a message with automatic rate limit retry.

    Args:
        message: Message to edit
        content: New content (None to keep existing)
        embed: New embed (None to keep existing)
        max_retries: Maximum retry attempts
        **kwargs: Additional arguments to edit()

    Returns:
        True on success, False on failure
    """
    for attempt in range(max_retries):
        try:
            await message.edit(content=content, embed=embed, **kwargs)
            return True
        except discord.RateLimited as e:
            logger.warning("Rate Limited on Message Edit", [
                ("Message ID", str(message.id)),
                ("Attempt", f"{attempt + 1}/{max_retries}"),
                ("Retry After", f"{e.retry_after:.1f}s"),
            ])
            if attempt < max_retries - 1 and e.retry_after < RateLimitConfig.MAX_DELAY:
                await asyncio.sleep(e.retry_after + 0.5)
                continue
            return False
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = getattr(e, 'retry_after', RateLimitConfig.BASE_DELAY * (2 ** attempt))
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_after + 0.5)
                    continue
            logger.error("Failed to Edit Message", [
                ("Message ID", str(message.id)),
                ("Error", str(e)),
            ])
            return False
        except Exception as e:
            logger.error("Unexpected Error Editing Message", [
                ("Message ID", str(message.id)),
                ("Error", str(e)),
            ])
            return False

    return False


async def edit_thread_with_retry(
    thread: discord.Thread,
    max_retries: int = RateLimitConfig.MAX_RETRIES,
    **kwargs: Any,
) -> bool:
    """
    Edit a thread with automatic rate limit retry.

    Args:
        thread: Thread to edit
        max_retries: Maximum retry attempts
        **kwargs: Arguments to pass to thread.edit()

    Returns:
        True on success, False on failure
    """
    for attempt in range(max_retries):
        try:
            await thread.edit(**kwargs)
            return True
        except discord.RateLimited as e:
            logger.warning("Rate Limited on Thread Edit", [
                ("Thread", thread.name[:50] if thread.name else str(thread.id)),
                ("Attempt", f"{attempt + 1}/{max_retries}"),
                ("Retry After", f"{e.retry_after:.1f}s"),
            ])
            if attempt < max_retries - 1 and e.retry_after < RateLimitConfig.MAX_DELAY:
                await asyncio.sleep(e.retry_after + 0.5)
                continue
            return False
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = getattr(e, 'retry_after', RateLimitConfig.BASE_DELAY * (2 ** attempt))
                logger.warning("Rate Limited on Thread Edit", [
                    ("Thread", thread.name[:50] if thread.name else str(thread.id)),
                    ("Attempt", f"{attempt + 1}/{max_retries}"),
                    ("Retry After", f"{retry_after:.1f}s"),
                ])
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_after + 0.5)
                    continue
            logger.error("Failed to Edit Thread", [
                ("Thread", thread.name[:50] if thread.name else str(thread.id)),
                ("Error", str(e)),
            ])
            return False
        except Exception as e:
            logger.error("Unexpected Error Editing Thread", [
                ("Thread", thread.name[:50] if thread.name else str(thread.id)),
                ("Error", str(e)),
            ])
            return False

    return False


async def delete_message_safe(
    message: discord.Message,
    delay: float = 0.0,
) -> bool:
    """
    Safely delete a message with optional delay.

    Args:
        message: Message to delete
        delay: Optional delay before deletion

    Returns:
        True if deleted, False otherwise
    """
    if delay > 0:
        await asyncio.sleep(delay)

    try:
        await message.delete()
        return True
    except discord.NotFound:
        # Already deleted - not an error
        return True
    except discord.HTTPException as e:
        if e.status != 429:  # Don't log rate limits as errors
            logger.warning("Failed to Delete Message", [
                ("Message ID", str(message.id)),
                ("Error", str(e)),
            ])
        return False


async def remove_reaction_safe(
    reaction: discord.Reaction,
    user: Union[discord.User, discord.Member],
) -> bool:
    """
    Safely remove a reaction without raising on failure.

    Args:
        reaction: The reaction to remove
        user: The user whose reaction to remove

    Returns:
        True if removed, False otherwise
    """
    try:
        await reaction.remove(user)
        return True
    except discord.HTTPException as e:
        if e.status != 429:  # Don't log rate limits
            logger.warning("Failed to Remove Reaction", [
                ("User", f"{user.name} ({user.id})"),
                ("Emoji", str(reaction.emoji)),
                ("Error", str(e)),
            ])
        return False


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Config
    "RateLimitConfig",
    # Logging
    "log_http_error",
    "HTTP_STATUS_DESCRIPTIONS",
    # Decorator
    "with_rate_limit_retry",
    # Helper functions
    "add_reactions_with_delay",
    "send_message_with_retry",
    "edit_message_with_retry",
    "edit_thread_with_retry",
    "delete_message_safe",
    "remove_reaction_safe",
    # Constants (backwards compatibility)
    "MAX_RETRIES",
    "BASE_DELAY",
    "MAX_DELAY",
    "REACTION_DELAY",
]
