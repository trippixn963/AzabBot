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


async def safe_async_operation(
    name: str,
    coro: Coroutine[Any, Any, Any],
    default: Any = None,
    log_level: str = "warning",
) -> Any:
    """
    Run a single async operation with error handling.

    Args:
        name: Name of the operation for logging.
        coro: The coroutine to run.
        default: Value to return if operation fails.
        log_level: Log level for errors ("debug", "warning", "error").

    Returns:
        Result of the coroutine, or default if it fails.
    """
    try:
        return await coro
    except Exception as e:
        error_details = [
            ("Operation", name),
            ("Error Type", type(e).__name__),
            ("Error", str(e)[:100]),
        ]

        if log_level == "debug":
            logger.debug("Async Operation Failed", error_details)
        elif log_level == "error":
            logger.error("Async Operation Failed", error_details)
        else:
            logger.warning("Async Operation Failed", error_details)

        return default


def log_gather_exceptions(
    results: List[Any],
    operation_names: List[str],
    context: Optional[str] = None,
) -> int:
    """
    Log any exceptions from asyncio.gather results.

    Use this when you have existing asyncio.gather calls and want to
    add logging without changing the call structure.

    Args:
        results: Results from asyncio.gather(..., return_exceptions=True).
        operation_names: Names of the operations in the same order.
        context: Optional context string for error logs.

    Returns:
        Number of failures logged.

    Example:
        results = await asyncio.gather(
            send_dm(),
            post_logs(),
            update_tracker(),
            return_exceptions=True,
        )
        log_gather_exceptions(
            results,
            ["Send DM", "Post Logs", "Mod Tracker"],
            context="Mute Command",
        )
    """
    failures = 0

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            failures += 1
            name = operation_names[i] if i < len(operation_names) else f"Operation {i}"

            error_details = [
                ("Operation", name),
                ("Error Type", type(result).__name__),
                ("Error", str(result)[:100]),
            ]
            if context:
                error_details.insert(0, ("Context", context))

            logger.warning("Async Operation Failed", error_details)

    return failures


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
            await coro
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
    "safe_async_operation",
    "log_gather_exceptions",
    "create_safe_task",
]
