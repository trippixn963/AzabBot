"""
Mute Command - Autocomplete Mixin
=================================

Autocomplete handlers for mute/unmute commands.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, List

import discord
from discord import app_commands

from src.utils.duration import parse_duration, format_duration
from src.core.constants import MODERATION_REASONS, MODERATION_REMOVAL_REASONS

from .constants import DURATION_CHOICES

if TYPE_CHECKING:
    from .cog import MuteCog


class AutocompleteMixin:
    """Mixin for autocomplete handlers."""

    async def duration_autocomplete(
        self: "MuteCog",
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """
        Autocomplete for duration parameter.

        Args:
            interaction: Discord interaction.
            current: Current input value.

        Returns:
            List of duration choices.
        """
        choices = []
        current_lower = current.lower().strip()

        # Always add user's custom input first if it's a valid duration
        if current:
            parsed = parse_duration(current)
            if parsed is not None:
                formatted = format_duration(parsed)
                choices.append(app_commands.Choice(name=f"{formatted}", value=current))
            elif current_lower in ("perm", "permanent", "forever"):
                choices.append(app_commands.Choice(name="Permanent", value="permanent"))

        # Add matching preset choices
        for label, value in DURATION_CHOICES:
            # Skip if we already added this exact value as custom
            if current_lower == value.lower():
                continue
            if current_lower in label.lower() or current_lower in value.lower():
                choices.append(app_commands.Choice(name=label, value=value))

        # If no input, show all choices
        if not current:
            choices = [app_commands.Choice(name=label, value=value) for label, value in DURATION_CHOICES]

        return choices[:25]  # Discord limit

    async def reason_autocomplete(
        self: "MuteCog",
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """
        Autocomplete for reason parameter.

        Args:
            interaction: Discord interaction.
            current: Current input value.

        Returns:
            List of reason choices.
        """
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
        self: "MuteCog",
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for removal reason parameter (unmute)."""
        choices = []
        current_lower = current.lower()

        for reason in MODERATION_REMOVAL_REASONS:
            if current_lower in reason.lower():
                choices.append(app_commands.Choice(name=reason, value=reason))

        # Include custom input if provided
        if current and current not in MODERATION_REMOVAL_REASONS:
            choices.insert(0, app_commands.Choice(name=current, value=current))

        return choices[:25]


__all__ = ["AutocompleteMixin"]
