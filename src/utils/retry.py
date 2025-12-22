"""
Azab Discord Bot - Retry Utilities
===================================

Retry logic for Discord API calls with exponential backoff.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from functools import wraps
from typing import TypeVar, Callable, Any, Optional, Tuple, Type

import discord

from src.core.logger import logger

T = TypeVar("T")

# Exceptions that should trigger a retry
RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    discord.HTTPException,
    asyncio.TimeoutError,
    ConnectionError,
)


async def retry_async(
    coro_func: Callable[..., Any],
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    exceptions: Tuple[Type[Exception], ...] = RETRYABLE_EXCEPTIONS,
    **kwargs,
) -> Any:
    """
    Retry an async function with exponential backoff.

    Args:
        coro_func: Async function to call.
        *args: Arguments to pass to the function.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay between retries (seconds).
        max_delay: Maximum delay between retries (seconds).
        exceptions: Tuple of exception types that trigger retry.
        **kwargs: Keyword arguments to pass to the function.

    Returns:
        Result of the coroutine function.

    Raises:
        The last exception if all retries fail.
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await coro_func(*args, **kwargs)
        except exceptions as e:
            last_exception = e

            if attempt < max_retries:
                # Exponential backoff: 1s, 2s, 4s, etc. (capped at max_delay)
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(f"Retry {attempt + 1}/{max_retries}: {type(e).__name__} - retrying in {delay:.1f}s")
                await asyncio.sleep(delay)
            else:
                logger.error(f"All {max_retries} retries failed: {type(e).__name__}: {e}")

    raise last_exception


async def with_timeout(
    coro: Any,
    timeout: float = 10.0,
    default: Optional[T] = None,
) -> Optional[T]:
    """
    Run a coroutine with a timeout, returning default on timeout.

    Args:
        coro: Coroutine to run.
        timeout: Timeout in seconds.
        default: Value to return on timeout.

    Returns:
        Result of coroutine or default on timeout.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"Operation timed out after {timeout}s")
        return default


async def safe_fetch_channel(bot, channel_id: int) -> Optional[discord.abc.GuildChannel]:
    """
    Safely fetch a channel with retry logic.

    Args:
        bot: Bot instance.
        channel_id: Channel ID to fetch.

    Returns:
        Channel object or None if not found/failed.
    """
    if not channel_id:
        return None

    # Try cache first
    channel = bot.get_channel(channel_id)
    if channel:
        return channel

    # Fetch with retry
    try:
        return await retry_async(
            bot.fetch_channel,
            channel_id,
            max_retries=2,
            base_delay=0.5,
        )
    except (discord.NotFound, discord.Forbidden):
        return None
    except Exception as e:
        logger.error(f"Failed to fetch channel {channel_id}: {e}")
        return None


async def safe_fetch_message(
    channel: discord.abc.Messageable,
    message_id: int,
) -> Optional[discord.Message]:
    """
    Safely fetch a message with retry logic.

    Args:
        channel: Channel to fetch from.
        message_id: Message ID to fetch.

    Returns:
        Message object or None if not found/failed.
    """
    if not channel or not message_id:
        return None

    try:
        return await retry_async(
            channel.fetch_message,
            message_id,
            max_retries=2,
            base_delay=0.5,
        )
    except (discord.NotFound, discord.Forbidden):
        return None
    except Exception as e:
        logger.error(f"Failed to fetch message {message_id}: {e}")
        return None


async def safe_send(
    channel: discord.abc.Messageable,
    content: Optional[str] = None,
    **kwargs,
) -> Optional[discord.Message]:
    """
    Safely send a message with retry logic.

    Args:
        channel: Channel to send to.
        content: Message content.
        **kwargs: Additional arguments (embed, view, etc.)

    Returns:
        Sent message or None on failure.
    """
    if not channel:
        return None

    try:
        return await retry_async(
            channel.send,
            content,
            max_retries=2,
            base_delay=0.5,
            **kwargs,
        )
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.error(f"Failed to send message: {e}")
        return None


async def safe_edit(
    message: discord.Message,
    **kwargs,
) -> Optional[discord.Message]:
    """
    Safely edit a message with retry logic.

    Args:
        message: Message to edit.
        **kwargs: Edit arguments (content, embed, etc.)

    Returns:
        Edited message or None on failure.
    """
    if not message:
        return None

    try:
        return await retry_async(
            message.edit,
            max_retries=2,
            base_delay=0.5,
            **kwargs,
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
        logger.error(f"Failed to edit message {message.id}: {e}")
        return None


async def safe_delete(message: discord.Message) -> bool:
    """
    Safely delete a message with retry logic.

    Args:
        message: Message to delete.

    Returns:
        True if deleted, False on failure.
    """
    if not message:
        return False

    try:
        await retry_async(
            message.delete,
            max_retries=2,
            base_delay=0.5,
        )
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "retry_async",
    "with_timeout",
    "safe_fetch_channel",
    "safe_fetch_message",
    "safe_send",
    "safe_edit",
    "safe_delete",
    "RETRYABLE_EXCEPTIONS",
]
