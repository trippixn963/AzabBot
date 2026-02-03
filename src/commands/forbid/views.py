"""
AzabBot - Forbid Views
======================

UI views and modals for the forbid command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.constants import MODAL_FIELD_LONG
from src.views import APPEAL_EMOJI
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


class ForbidAppealButton(discord.ui.DynamicItem[discord.ui.Button], template=r"forbid_appeal:(?P<guild_id>\d+):(?P<user_id>\d+)"):
    """Persistent appeal button for forbid DMs."""

    def __init__(self, guild_id: int, user_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Appeal Restriction",
                style=discord.ButtonStyle.secondary,
                emoji=APPEAL_EMOJI,
                custom_id=f"forbid_appeal:{guild_id}:{user_id}",
            )
        )
        self.guild_id = guild_id
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "ForbidAppealButton":
        guild_id = int(match.group("guild_id"))
        user_id = int(match.group("user_id"))
        return cls(guild_id, user_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle appeal button click."""
        logger.tree("Forbid Appeal Button Clicked", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Guild ID", str(self.guild_id)),
        ], emoji="📝")

        # Show appeal modal
        modal = ForbidAppealModal(self.guild_id)
        await interaction.response.send_modal(modal)


class ForbidAppealView(discord.ui.View):
    """View with appeal button for forbid DMs."""

    def __init__(self, guild_id: int, user_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(ForbidAppealButton(guild_id, user_id))


class ForbidAppealModal(discord.ui.Modal):
    """Modal for submitting a forbid appeal."""

    def __init__(self, guild_id: int) -> None:
        super().__init__(title="Appeal Restriction")
        self.guild_id = guild_id

        self.reason = discord.ui.TextInput(
            label="Why should this restriction be removed?",
            style=discord.TextStyle.paragraph,
            placeholder="Explain why you believe the restriction was unfair or provide context...",
            required=True,
            max_length=MODAL_FIELD_LONG,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle appeal submission."""
        logger.tree("Forbid Appeal Modal Submitted", [
            ("User", f"{interaction.user.name} ({interaction.user.id})"),
            ("Guild ID", str(self.guild_id)),
            ("Reason Length", str(len(self.reason.value))),
        ], emoji="📝")

        from src.bot import AzabBot

        bot: AzabBot = interaction.client  # type: ignore
        config = get_config()

        # Send appeal to mod channel
        try:
            guild = bot.get_guild(self.guild_id)
            if not guild:
                await interaction.response.send_message(
                    "Unable to submit appeal - server not found.",
                    ephemeral=True,
                )
                return

            # Try to send to alert channel or mod logs
            alert_channel = None
            if config.alert_channel_id:
                alert_channel = bot.get_channel(config.alert_channel_id)

            if not alert_channel and bot.logging_service and bot.logging_service.enabled:
                # Try to use the logging service
                try:
                    embed = discord.Embed(
                        title="📝 Forbid Appeal Submitted",
                        color=EmbedColors.INFO,
                        timestamp=datetime.now(NY_TZ),
                    )
                    embed.add_field(
                        name="User",
                        value=f"{interaction.user.mention}\n`{interaction.user.id}`",
                        inline=True,
                    )
                    embed.add_field(
                        name="Appeal Reason",
                        value=self.reason.value,
                        inline=False,
                    )
                    embed.set_thumbnail(url=interaction.user.display_avatar.url)
                    set_footer(embed)

                    await bot.logging_service._send_log(
                        bot.logging_service.LogCategory.MOD_ACTIONS,
                        embed,
                    )

                    await interaction.response.send_message(
                        "Your appeal has been submitted! A moderator will review it soon.",
                        ephemeral=True,
                    )
                    return

                except Exception as e:
                    logger.debug(f"Appeal via logging service failed: {e}")

            if alert_channel:
                embed = discord.Embed(
                    title="📝 Forbid Appeal Submitted",
                    color=EmbedColors.INFO,
                    timestamp=datetime.now(NY_TZ),
                )
                embed.add_field(
                    name="User",
                    value=f"{interaction.user.mention}\n`{interaction.user.id}`",
                    inline=True,
                )
                embed.add_field(
                    name="Appeal Reason",
                    value=self.reason.value,
                    inline=False,
                )
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
                set_footer(embed)

                await alert_channel.send(embed=embed)

            await interaction.response.send_message(
                "Your appeal has been submitted! A moderator will review it soon.",
                ephemeral=True,
            )

        except Exception as e:
            logger.debug(f"Failed to submit forbid appeal: {e}")
            await interaction.response.send_message(
                "Failed to submit appeal. Please contact a moderator directly.",
                ephemeral=True,
            )


def setup_forbid_views(bot: "AzabBot") -> None:
    """Register persistent views for forbid buttons. Call this on bot startup."""
    bot.add_dynamic_items(ForbidAppealButton)


__all__ = [
    "ForbidAppealButton",
    "ForbidAppealView",
    "ForbidAppealModal",
    "setup_forbid_views",
]
