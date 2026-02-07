"""
AzabBot - Warn Modals
=====================

Modal dialogs for the warn command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.constants import MODAL_FIELD_MEDIUM

if TYPE_CHECKING:
    from src.bot import AzabBot
    from .cog import WarnCog


class WarnModal(discord.ui.Modal, title="Warn User"):
    """Modal for warning a user from context menu."""

    reason_input = discord.ui.TextInput(
        label="Reason",
        placeholder="Reason for the warning",
        required=False,
        max_length=MODAL_FIELD_MEDIUM,
        style=discord.TextStyle.paragraph,
    )

    def __init__(
        self,
        bot: "AzabBot",
        target_user: discord.Member,
        evidence: Optional[str],
        cog: "WarnCog",
    ) -> None:
        super().__init__()
        self.bot = bot
        self.target_user = target_user
        self.evidence = evidence
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        logger.tree("Warn Modal Submitted", [
            ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ("Target", f"{self.target_user.name} ({self.target_user.id})"),
        ], emoji="📋")

        reason = self.reason_input.value or None

        await interaction.response.defer(ephemeral=False)

        user = interaction.guild.get_member(self.target_user.id)
        if not user:
            await interaction.followup.send(
                "User not found in this server.",
                ephemeral=True,
            )
            return

        await self.cog.execute_warn(
            interaction=interaction,
            user=user,
            reason=reason,
            evidence=self.evidence,
        )


__all__ = ["WarnModal"]
