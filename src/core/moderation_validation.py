"""
AzabBot - Centralized Moderation Validation
============================================

Shared validation logic for moderation commands (ban, mute, warn, forbid).
Eliminates duplicate validation code and ensures consistent behavior.

Usage:
    from src.core.moderation_validation import (
        validate_moderation_target,
        get_target_guild,
        is_cross_server,
    )

    # In your command:
    result = await validate_moderation_target(
        interaction=interaction,
        target=user,
        bot=self.bot,
        action="ban",
    )
    if not result.is_valid:
        await interaction.followup.send(result.error_message, ephemeral=True)
        return

Author: John Hamwi
Server: discord.gg/syria
"""

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

import discord

from src.core.config import get_config, is_developer, EmbedColors
from src.core.logger import logger
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Result Types
# =============================================================================

@dataclass
class ValidationResult:
    """Result of a validation check."""
    is_valid: bool
    error_message: Optional[str] = None
    should_log_attempt: bool = False  # For management protection logging


# =============================================================================
# Cross-Server Helpers
# =============================================================================

def get_target_guild(
    interaction: discord.Interaction,
    bot: "AzabBot",
) -> discord.Guild:
    """
    Get the target guild for moderation actions.

    If command is run from mod server, targets the main server.
    Otherwise, targets the current server.

    Args:
        interaction: Discord interaction context.
        bot: Bot instance for guild lookup.

    Returns:
        The target guild for the moderation action.
    """
    config = get_config()

    if (config.mod_server_id and
        config.logging_guild_id and
        interaction.guild and
        interaction.guild.id == config.mod_server_id):
        main_guild = bot.get_guild(config.logging_guild_id)
        if main_guild:
            return main_guild

    return interaction.guild


def is_cross_server(interaction: discord.Interaction) -> bool:
    """
    Check if this is a cross-server moderation action.

    Args:
        interaction: Discord interaction context.

    Returns:
        True if moderating from mod server to main server.
    """
    config = get_config()
    return (
        config.mod_server_id is not None and
        config.logging_guild_id is not None and
        interaction.guild is not None and
        interaction.guild.id == config.mod_server_id
    )


# =============================================================================
# Individual Validation Checks
# =============================================================================

def validate_self_action(
    moderator: discord.User,
    target: discord.User,
    action: str,
) -> ValidationResult:
    """
    Check if moderator is trying to action themselves.

    Args:
        moderator: The moderator performing the action.
        target: The target of the action.
        action: Action name for error message (e.g., "ban", "mute").

    Returns:
        ValidationResult with is_valid=False if self-action attempted.
    """
    if target.id == moderator.id:
        logger.tree(f"{action.upper()} BLOCKED", [
            ("Reason", "Self-action attempt"),
            ("Moderator", f"{moderator} ({moderator.id})"),
        ], emoji="🚫")
        return ValidationResult(
            is_valid=False,
            error_message=f"You cannot {action} yourself.",
        )
    return ValidationResult(is_valid=True)


def validate_bot_self_action(
    target: discord.User,
    bot_user: discord.User,
    action: str,
) -> ValidationResult:
    """
    Check if trying to action the bot itself.

    Args:
        target: The target of the action.
        bot_user: The bot's user object.
        action: Action name for error message.

    Returns:
        ValidationResult with is_valid=False if targeting bot.
    """
    if target.id == bot_user.id:
        logger.tree(f"{action.upper()} BLOCKED", [
            ("Reason", "Bot self-action attempt"),
        ], emoji="🚫")
        return ValidationResult(
            is_valid=False,
            error_message=f"I cannot {action} myself.",
        )
    return ValidationResult(is_valid=True)


def validate_target_not_bot(
    moderator: discord.User,
    target: discord.User,
    action: str,
) -> ValidationResult:
    """
    Check if target is a bot (bots can't be moderated, except by developers).

    Args:
        moderator: The moderator performing the action.
        target: The target of the action.
        action: Action name for error message.

    Returns:
        ValidationResult with is_valid=False if target is bot and mod isn't developer.
    """
    if target.bot and not is_developer(moderator.id):
        logger.tree(f"{action.upper()} BLOCKED", [
            ("Reason", "Target is a bot"),
            ("Moderator", f"{moderator} ({moderator.id})"),
            ("Target", f"{target} ({target.id})"),
        ], emoji="🚫")
        return ValidationResult(
            is_valid=False,
            error_message=f"You cannot {action} bots.",
        )
    return ValidationResult(is_valid=True)


def validate_role_hierarchy(
    moderator: discord.Member,
    target: discord.Member,
    target_guild: discord.Guild,
    action: str,
    cross_server: bool = False,
) -> ValidationResult:
    """
    Check role hierarchy - can't action someone with equal/higher role.

    Args:
        moderator: The moderator performing the action.
        target: The target member (must be in target guild).
        target_guild: The guild where action is being performed.
        action: Action name for error message.
        cross_server: Whether this is a cross-server action.

    Returns:
        ValidationResult with is_valid=False if hierarchy check fails.
    """
    # Developers bypass hierarchy
    if is_developer(moderator.id):
        return ValidationResult(is_valid=True)

    # For cross-server, get mod's member object from target guild
    if cross_server:
        mod_in_target = target_guild.get_member(moderator.id)
        if not mod_in_target:
            # Mod not in target guild - can't check hierarchy, allow action
            return ValidationResult(is_valid=True)
        moderator = mod_in_target

    if target.top_role >= moderator.top_role:
        logger.tree(f"{action.upper()} BLOCKED", [
            ("Reason", "Role hierarchy"),
            ("Moderator", f"{moderator} ({moderator.id})"),
            ("Mod Role", moderator.top_role.name),
            ("Target", f"{target} ({target.id})"),
            ("Target Role", target.top_role.name),
        ], emoji="🚫")
        return ValidationResult(
            is_valid=False,
            error_message=f"You cannot {action} someone with an equal or higher role.",
        )
    return ValidationResult(is_valid=True)


def validate_management_protection(
    moderator: discord.Member,
    target: discord.Member,
    target_guild: discord.Guild,
    action: str,
    cross_server: bool = False,
) -> ValidationResult:
    """
    Check management protection - management members can't action each other.

    Args:
        moderator: The moderator performing the action.
        target: The target member.
        target_guild: The guild where action is being performed.
        action: Action name for error message.
        cross_server: Whether this is a cross-server action.

    Returns:
        ValidationResult with is_valid=False if management protection triggered.
        Sets should_log_attempt=True for mod tracker logging.
    """
    config = get_config()

    # No management role configured
    if not config.moderation_role_id:
        return ValidationResult(is_valid=True)

    # Developers bypass protection
    if is_developer(moderator.id):
        return ValidationResult(is_valid=True)

    management_role = target_guild.get_role(config.moderation_role_id)
    if not management_role:
        return ValidationResult(is_valid=True)

    # For cross-server, get mod's member object from target guild
    mod_member = moderator
    if cross_server:
        mod_in_target = target_guild.get_member(moderator.id)
        if not mod_in_target:
            return ValidationResult(is_valid=True)
        mod_member = mod_in_target

    # Check if both have management role
    target_has_management = management_role in target.roles
    mod_has_management = management_role in mod_member.roles

    if target_has_management and mod_has_management:
        logger.tree(f"{action.upper()} BLOCKED", [
            ("Reason", "Management protection"),
            ("Moderator", f"{moderator} ({moderator.id})"),
            ("Target", f"{target} ({target.id})"),
        ], emoji="🚫")
        return ValidationResult(
            is_valid=False,
            error_message=f"Management members cannot {action} each other.",
            should_log_attempt=True,
        )
    return ValidationResult(is_valid=True)


def validate_bot_can_action(
    target: discord.Member,
    bot_member: discord.Member,
    action: str,
) -> ValidationResult:
    """
    Check if bot has permission to action the target (role hierarchy).

    Args:
        target: The target member.
        bot_member: The bot's member object in the guild.
        action: Action name for error message.

    Returns:
        ValidationResult with is_valid=False if bot can't action target.
    """
    if target.top_role >= bot_member.top_role:
        logger.tree(f"{action.upper()} BLOCKED", [
            ("Reason", "Bot role too low"),
            ("Target Role", target.top_role.name),
            ("Bot Top Role", bot_member.top_role.name),
        ], emoji="🚫")
        return ValidationResult(
            is_valid=False,
            error_message=f"I cannot {action} this user because their role is higher than mine.",
        )
    return ValidationResult(is_valid=True)


# =============================================================================
# Combined Validation
# =============================================================================

async def validate_moderation_target(
    interaction: discord.Interaction,
    target: discord.User,
    bot: "AzabBot",
    action: str,
    require_member: bool = False,
    check_bot_hierarchy: bool = True,
) -> ValidationResult:
    """
    Run all standard moderation validation checks.

    This is the main entry point for validation. It runs:
    1. Self-action check
    2. Bot self-action check
    3. Target is bot check
    4. Role hierarchy check (if target is member)
    5. Management protection check (if target is member)
    6. Bot permission check (if target is member and check_bot_hierarchy=True)

    Args:
        interaction: Discord interaction context.
        target: The target user/member.
        bot: Bot instance.
        action: Action name (e.g., "ban", "mute", "warn").
        require_member: If True, fails if target isn't a member of target guild.
        check_bot_hierarchy: If True, checks if bot can action the target.

    Returns:
        ValidationResult with is_valid=True if all checks pass.
    """
    moderator = interaction.user
    target_guild = get_target_guild(interaction, bot)
    cross_server = is_cross_server(interaction)

    # 1. Self-action check
    result = validate_self_action(moderator, target, action)
    if not result.is_valid:
        return result

    # 2. Bot self-action check
    result = validate_bot_self_action(target, bot.user, action)
    if not result.is_valid:
        return result

    # 3. Target is bot check
    result = validate_target_not_bot(moderator, target, action)
    if not result.is_valid:
        return result

    # Get target as member in target guild
    target_member = target_guild.get_member(target.id) if target_guild else None

    # If member required but not found
    if require_member and not target_member:
        guild_name = target_guild.name if cross_server else "this server"
        return ValidationResult(
            is_valid=False,
            error_message=f"User is not a member of {guild_name}.",
        )

    # Member-specific checks (only if target is a member)
    if target_member and isinstance(moderator, discord.Member):
        # 4. Role hierarchy check
        result = validate_role_hierarchy(
            moderator=moderator,
            target=target_member,
            target_guild=target_guild,
            action=action,
            cross_server=cross_server,
        )
        if not result.is_valid:
            return result

        # 5. Management protection check
        result = validate_management_protection(
            moderator=moderator,
            target=target_member,
            target_guild=target_guild,
            action=action,
            cross_server=cross_server,
        )
        if not result.is_valid:
            # Log to mod tracker if needed
            if result.should_log_attempt and bot.mod_tracker:
                await bot.mod_tracker.log_management_mute_attempt(
                    mod=moderator,
                    target=target_member,
                )
            return result

        # 6. Bot permission check
        if check_bot_hierarchy and target_guild:
            result = validate_bot_can_action(
                target=target_member,
                bot_member=target_guild.me,
                action=action,
            )
            if not result.is_valid:
                return result

    return ValidationResult(is_valid=True)


async def send_management_blocked_embed(
    interaction: discord.Interaction,
    action: str,
) -> None:
    """
    Send a styled embed when management protection blocks an action.

    Args:
        interaction: Discord interaction context.
        action: Action name for the message.
    """
    embed = discord.Embed(
        title="Action Blocked",
        description=f"Management members cannot {action} each other.",
        color=EmbedColors.WARNING,
    )
    set_footer(embed)
    await interaction.followup.send(embed=embed, ephemeral=True)


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "ValidationResult",
    "get_target_guild",
    "is_cross_server",
    "validate_self_action",
    "validate_bot_self_action",
    "validate_target_not_bot",
    "validate_role_hierarchy",
    "validate_management_protection",
    "validate_bot_can_action",
    "validate_moderation_target",
    "send_management_blocked_embed",
]
