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
    # Constants (backwards compatibility)
    "MAX_RETRIES",
    "BASE_DELAY",
    "MAX_DELAY",
    "REACTION_DELAY",
]
