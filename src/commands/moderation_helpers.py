"""
AzabBot - Shared Moderation Helpers
===================================

Common helper functions for moderation commands (ban, mute, etc.).
Reduces code duplication across operation files.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional

import discord

from src.core.logger import logger
from src.core.constants import CASE_LOG_TIMEOUT
from src.utils.discord_rate_limit import log_http_error

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Case Logging Helper
# =============================================================================

async def log_case_with_fallback(
    bot: "AzabBot",
    case_log_coro: Coroutine[Any, Any, Optional[dict]],
    action_type: str,
    user: discord.User,
    timeout: float = CASE_LOG_TIMEOUT,
) -> Optional[dict]:
    """
    Log a moderation case with timeout handling and error alerting.

    Args:
        bot: Bot instance (for case_log_service and webhook_alert_service).
        case_log_coro: Coroutine to call for case logging (e.g., case_log_service.log_ban(...)).
        action_type: Action type for logging ("Ban", "Mute", "Unmute", "Unban").
        user: Target user for logging context.
        timeout: Timeout in seconds (default: CASE_LOG_TIMEOUT).

    Returns:
        Case info dict if successful, None otherwise.
    """
    if not bot.case_log_service:
        return None

    try:
        case_info = await asyncio.wait_for(case_log_coro, timeout=timeout)

        if case_info:
            logger.tree("Case Created", [
                ("Action", action_type),
                ("Case ID", case_info["case_id"]),
                ("User", f"{user.name} ({user.id})"),
            ], emoji="📋")

        return case_info

    except asyncio.TimeoutError:
        logger.warning("Case Log Timeout", [
            ("Action", action_type),
            ("User", user.name),
            ("ID", str(user.id)),
        ])
        if bot.webhook_alert_service:
            await bot.webhook_alert_service.send_error_alert(
                "Case Log Timeout",
                f"{action_type} case logging timed out for {user} ({user.id})"
            )
        return None

    except Exception as e:
        logger.error("Case Log Failed", [
            ("Action", action_type),
            ("User", user.name),
            ("ID", str(user.id)),
            ("Error", str(e)[:100]),
        ])
        if bot.webhook_alert_service:
            await bot.webhook_alert_service.send_error_alert(
                "Case Log Failed",
                f"{action_type} case logging failed for {user} ({user.id}): {str(e)[:200]}"
            )
        return None


# =============================================================================
# Discord API Error Handler
# =============================================================================

async def handle_discord_api_error(
    error: Exception,
    action_type: str,
    target: discord.User,
    moderator: discord.Member,
    guild: discord.Guild,
    interaction: discord.Interaction,
) -> bool:
    """
    Handle Discord API errors for moderation actions.

    Args:
        error: The caught exception.
        action_type: Action type for logging ("ban", "mute", etc.).
        target: Target user.
        moderator: Moderator who performed action.
        guild: Guild where action was performed.
        interaction: Discord interaction (must be deferred).

    Returns:
        False (always - indicates failure).
    """
    action_title = action_type.title()

    if isinstance(error, discord.Forbidden):
        logger.warning(f"{action_title} Failed (Forbidden)", [
            ("User", f"{target.name} ({target.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})"),
            ("Guild", guild.name),
        ])
        await interaction.followup.send(
            f"I don't have permission to {action_type} this user.",
            ephemeral=True,
        )
    elif isinstance(error, discord.HTTPException):
        log_http_error(error, action_title, [
            ("User", f"{target.name} ({target.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})"),
        ])
        await interaction.followup.send(
            f"Failed to {action_type} user: {error}",
            ephemeral=True,
        )
    else:
        logger.error(f"{action_title} Failed", [
            ("User", f"{target.name} ({target.id})"),
            ("Moderator", f"{moderator.name} ({moderator.id})"),
            ("Guild", guild.name),
            ("Error", str(error)[:100]),
        ])
        await interaction.followup.send(
            f"An unexpected error occurred while trying to {action_type} this user.",
            ephemeral=True,
        )

    return False


# =============================================================================
# Action Logging Helper
# =============================================================================

def log_moderation_action(
    action_type: str,
    target: discord.User,
    moderator: discord.Member,
    guild: discord.Guild,
    reason: Optional[str] = None,
    cross_server: bool = False,
    source_guild: Optional[discord.Guild] = None,
    emoji: str = "🔨",
    **extra_fields,
) -> None:
    """
    Log a moderation action with standardized format.

    Args:
        action_type: Action name for log (e.g., "USER BANNED", "USER MUTED").
        target: Target user.
        moderator: Moderator who performed action.
        guild: Guild where action was performed.
        reason: Action reason (truncated to 50 chars).
        cross_server: Whether this was a cross-server action.
        source_guild: Source guild for cross-server actions.
        emoji: Emoji for log entry.
        **extra_fields: Additional fields as key=value pairs.
    """
    log_items = [
        ("User", f"{target.name} ({target.id})"),
        ("Guild", f"{guild.name} ({guild.id})"),
        ("Moderator", f"{moderator.name} ({moderator.id})"),
        ("Reason", (reason or "None")[:50]),
    ]

    # Insert cross-server indicator after User
    if cross_server and source_guild:
        log_items.insert(1, ("Cross-Server", f"From {source_guild.name}"))

    # Add extra fields
    for key, value in extra_fields.items():
        # Convert key from snake_case to Title Case
        display_key = key.replace("_", " ").title()
        log_items.append((display_key, str(value)))

    logger.tree(action_type, log_items, emoji=emoji)


# =============================================================================
# Case Resolution Logging Helper
# =============================================================================

async def log_case_resolution(
    bot: "AzabBot",
    case_log_coro: Coroutine[Any, Any, Optional[dict]],
    action_type: str,
    target: discord.User,
    timeout: float = CASE_LOG_TIMEOUT,
) -> Optional[dict]:
    """
    Log a case resolution (unmute, unban) with timeout handling.

    Args:
        bot: Bot instance.
        case_log_coro: Coroutine to call for case resolution.
        action_type: Action type for logging ("Unmute", "Unban").
        target: Target user.
        timeout: Timeout in seconds.

    Returns:
        Case info dict if successful, None otherwise.
    """
    if not bot.case_log_service:
        return None

    try:
        case_info = await asyncio.wait_for(case_log_coro, timeout=timeout)

        if case_info:
            logger.tree("Case Resolved", [
                ("Action", action_type),
                ("Case ID", case_info["case_id"]),
                ("User", f"{target.name} ({target.id})"),
            ], emoji="📋")

        return case_info

    except asyncio.TimeoutError:
        logger.warning("Case Log Timeout", [
            ("Action", action_type),
            ("User", target.name if hasattr(target, 'name') else str(target)),
            ("ID", str(target.id)),
        ])
        if bot.webhook_alert_service:
            await bot.webhook_alert_service.send_error_alert(
                "Case Log Timeout",
                f"{action_type} case logging timed out for {target} ({target.id})"
            )
        return None

    except Exception as e:
        logger.error("Case Log Failed", [
            ("Action", action_type),
            ("User", target.name if hasattr(target, 'name') else str(target)),
            ("ID", str(target.id)),
            ("Error", str(e)[:100]),
        ])
        if bot.webhook_alert_service:
            await bot.webhook_alert_service.send_error_alert(
                "Case Log Failed",
                f"{action_type} case logging failed for {target} ({target.id}): {str(e)[:200]}"
            )
        return None


__all__ = [
    "log_case_with_fallback",
    "log_case_resolution",
    "handle_discord_api_error",
    "log_moderation_action",
]
