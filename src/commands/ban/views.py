"""
Azab Discord Bot - Ban Views
=============================

UI views and modals for the ban command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger

if TYPE_CHECKING:
    from src.bot import AzabBot


class BanModal(discord.ui.Modal, title="Ban User"):
    """Modal for banning a user from context menu."""

    reason_input = discord.ui.TextInput(
        label="Reason",
        placeholder="Enter ban reason...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, target: discord.Member, cog, evidence: Optional[str] = None) -> None:
        super().__init__()
        self.target = target
        self.cog = cog  # BanCog - avoiding circular import
        self.evidence = evidence

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Process the ban when modal is submitted."""
        logger.tree("Ban Modal Submitted", [
            ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ("Target", f"{self.target.name} ({self.target.id})"),
        ], emoji="🔨")

        reason = self.reason_input.value or None

        await self.cog.execute_ban(
            interaction=interaction,
            user=self.target,
            reason=reason,
            evidence=self.evidence,
        )


__all__ = [
    "BanModal",
]
