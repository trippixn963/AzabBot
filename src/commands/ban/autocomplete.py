"""
AzabBot - Ban Autocomplete
==========================

Autocomplete functions for ban/unban commands.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import List

import discord
from discord import app_commands

from src.core.config import get_config
from src.core.constants import MODERATION_REASONS, MODERATION_REMOVAL_REASONS, MAX_AUTOCOMPLETE_RESULTS
from src.core.logger import logger


async def reason_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Provide common moderation reasons."""
    choices = []
    current_lower = current.lower()

    for reason in MODERATION_REASONS:
        if current_lower in reason.lower():
            choices.append(app_commands.Choice(name=reason, value=reason))

    # Include custom input if provided
    if current and current not in MODERATION_REASONS:
        choices.insert(0, app_commands.Choice(name=current, value=current))

    return choices[:25]


async def removal_reason_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Provide common reasons for removing punishments."""
    choices = []
    current_lower = current.lower()

    for reason in MODERATION_REMOVAL_REASONS:
        if current_lower in reason.lower():
            choices.append(app_commands.Choice(name=reason, value=reason))

    # Include custom input if provided
    if current and current not in MODERATION_REMOVAL_REASONS:
        choices.insert(0, app_commands.Choice(name=current, value=current))

    return choices[:25]


async def banned_user_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Provide autocomplete for banned users (supports cross-server)."""
    try:
        config = get_config()

        # Determine target guild (cross-server support)
        target_guild = interaction.guild
        if (config.mod_server_id and
            config.main_guild_id and
            interaction.guild.id == config.mod_server_id):
            main_guild = interaction.client.get_guild(config.main_guild_id)
            if main_guild:
                target_guild = main_guild

        bans = [entry async for entry in target_guild.bans(limit=MAX_AUTOCOMPLETE_RESULTS)]
        choices = []
        for ban_entry in bans:
            user = ban_entry.user
            display = f"{user.name} ({user.id})"
            if current.lower() in display.lower() or current in str(user.id):
                choices.append(app_commands.Choice(
                    name=display[:100],
                    value=str(user.id),
                ))
        return choices[:25]
    except Exception as e:
        logger.warning("Banned User Autocomplete Failed", [
            ("Guild", interaction.guild.name if interaction.guild else "Unknown"),
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Input", current[:50] if current else "None"),
            ("Error", str(e)[:100]),
        ])
        return []


__all__ = [
    "reason_autocomplete",
    "removal_reason_autocomplete",
    "banned_user_autocomplete",
]
