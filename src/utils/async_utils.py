"""
AzabBot - Async Utilities
=========================

Utilities for handling async operations with proper error logging.
Eliminates silent failures in asyncio.gather and other async patterns.

Usage:
    from src.utils.async_utils import gather_with_logging

    # Instead of:
    await asyncio.gather(op1(), op2(), return_exceptions=True)

    # Use:
    await gather_with_logging(
        ("Send DM", send_dm()),
        ("Post Logs", post_logs()),
        ("Mod Tracker", update_tracker()),
    )

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import Tuple, Coroutine, Any, List, Optional

from src.core.logger import logger


async def gather_with_logging(
    *operations: Tuple[str, Coroutine[Any, Any, Any]],
    context: Optional[str] = None,
) -> List[Any]:
    """
    Run multiple async operations concurrently with error logging.

    Unlike asyncio.gather with return_exceptions=True, this function
    logs any exceptions that occur so failures aren't silent.

    Args:
        *operations: Tuples of (operation_name, coroutine).
        context: Optional context string for error logs (e.g., "Mute Command").

    Returns:
        List of results (including exceptions as values, not raised).

    Example:
        results = await gather_with_logging(
            ("Send DM", send_dm_to_user()),
            ("Post Mod Log", post_to_mod_log()),
            ("Update Tracker", update_mod_tracker()),
            context="Mute Command",
        )
    """
    names = [name for name, _ in operations]
    coros = [coro for _, coro in operations]

    results = await asyncio.gather(*coros, return_exceptions=True)

    # Log any failures
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            error_details = [
                ("Operation", names[i]),
                ("Error Type", type(result).__name__),
                ("Error", str(result)[:100]),
            ]
            if context:
                error_details.insert(0, ("Context", context))

            logger.warning("Async Operation Failed", error_details)

    return results


# =============================================================================
# Safe Background Tasks
# =============================================================================

def create_safe_task(
    coro: Coroutine[Any, Any, Any],
    name: str = "Background Task",
) -> asyncio.Task:
    """
    Create a background task with automatic error logging.

    Unlike raw asyncio.create_task(), this catches and logs any exceptions
    instead of letting them silently disappear.

    Args:
        coro: The coroutine to run as a background task.
        name: Name for logging purposes.

    Returns:
        The created asyncio.Task.

    Example:
        # Instead of:
        asyncio.create_task(self._cleanup_loop())

        # Use:
        create_safe_task(self._cleanup_loop(), "Cleanup Loop")
    """
    async def wrapped():
        try:
            return await coro
        except asyncio.CancelledError:
            # Task was cancelled, this is expected during shutdown
            pass
        except Exception as e:
            logger.error("Background Task Failed", [
                ("Task", name),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:200]),
            ])

    return asyncio.create_task(wrapped())


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "gather_with_logging",
    "create_safe_task",
]
