"""
AzabBot - Mute Views
====================

UI views and modals for the mute command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger

if TYPE_CHECKING:
    from src.bot import AzabBot


class MuteModal(discord.ui.Modal, title="Mute User"):
    """Modal for muting a user from context menu."""

    duration_input = discord.ui.TextInput(
        label="Duration",
        placeholder="e.g., 10m, 1h, 1d, permanent",
        required=False,
        max_length=50,
    )

    reason_input = discord.ui.TextInput(
        label="Reason",
        placeholder="Reason for the mute",
        required=False,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )

    def __init__(
        self,
        bot: "AzabBot",
        target_user: discord.Member,
        evidence: Optional[str],
        cog,  # MuteCog - avoiding circular import
    ):
        super().__init__()
        self.bot = bot
        self.target_user = target_user
        self.evidence = evidence
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        logger.tree("Mute Modal Submitted", [
            ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ("Target", f"{self.target_user.name} ({self.target_user.id})"),
        ], emoji="🔇")

        duration = self.duration_input.value or None
        reason = self.reason_input.value or None

        # Defer the response
        await interaction.response.defer(ephemeral=False)

        # Get the target as a Member
        user = interaction.guild.get_member(self.target_user.id)
        if not user:
            logger.debug(f"Mute modal target not found: {self.target_user.id}")
            await interaction.followup.send(
                "User not found in this server.",
                ephemeral=True,
            )
            return

        # Use shared mute logic from cog
        await self.cog.execute_mute(
            interaction=interaction,
            user=user,
            duration=duration,
            reason=reason,
            evidence=self.evidence,
        )


__all__ = [
    "MuteModal",
]
