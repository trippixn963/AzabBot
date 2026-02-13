"""
AzabBot - Avatar Button Views
=============================

Buttons for viewing old/new avatars from log messages.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re

import discord

from src.core.logger import logger

from .constants import DOWNLOAD_EMOJI


class OldAvatarButton(discord.ui.DynamicItem[discord.ui.Button], template=r"avatar_old:(?P<channel_id>\d+):(?P<message_id>\d+)"):
    """Button that sends old avatar URL from log message attachment."""

    def __init__(self, channel_id: int, message_id: int):
        super().__init__(
            discord.ui.Button(
                label="Avatar (Old)",
                style=discord.ButtonStyle.secondary,
                emoji=DOWNLOAD_EMOJI,
                custom_id=f"avatar_old:{channel_id}:{message_id}",
            )
        )
        self.channel_id = channel_id
        self.message_id = message_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "OldAvatarButton":
        channel_id = int(match.group("channel_id"))
        message_id = int(match.group("message_id"))
        return cls(channel_id, message_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Fetch old avatar from message attachment and send ephemeral."""
        logger.tree("Old Avatar Button Clicked", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Message ID", str(self.message_id)),
        ], emoji="🖼️")

        try:
            channel = interaction.client.get_channel(self.channel_id)
            if not channel:
                channel = await interaction.client.fetch_channel(self.channel_id)
            message = await channel.fetch_message(self.message_id)
            if message.attachments:
                await interaction.response.send_message(message.attachments[0].url, ephemeral=True)
            else:
                await interaction.response.send_message("Old avatar not found.", ephemeral=True)
        except discord.HTTPException:
            # Channel/message may not exist or be fetchable
            await interaction.response.send_message("Failed to fetch old avatar.", ephemeral=True)


class NewAvatarButton(discord.ui.DynamicItem[discord.ui.Button], template=r"avatar_new:(?P<channel_id>\d+):(?P<message_id>\d+)"):
    """Button that sends new avatar URL from log message embed image."""

    def __init__(self, channel_id: int, message_id: int):
        super().__init__(
            discord.ui.Button(
                label="Avatar (New)",
                style=discord.ButtonStyle.secondary,
                emoji=DOWNLOAD_EMOJI,
                custom_id=f"avatar_new:{channel_id}:{message_id}",
            )
        )
        self.channel_id = channel_id
        self.message_id = message_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "NewAvatarButton":
        channel_id = int(match.group("channel_id"))
        message_id = int(match.group("message_id"))
        return cls(channel_id, message_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Fetch new avatar from message embed image and send ephemeral."""
        logger.tree("New Avatar Button Clicked", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Message ID", str(self.message_id)),
        ], emoji="🖼️")

        try:
            channel = interaction.client.get_channel(self.channel_id)
            if not channel:
                channel = await interaction.client.fetch_channel(self.channel_id)
            message = await channel.fetch_message(self.message_id)
            if message.embeds and message.embeds[0].image:
                await interaction.response.send_message(message.embeds[0].image.url, ephemeral=True)
            else:
                await interaction.response.send_message("New avatar not found.", ephemeral=True)
        except discord.HTTPException:
            # Channel/message may not exist or be fetchable
            await interaction.response.send_message("Failed to fetch new avatar.", ephemeral=True)


__all__ = [
    "OldAvatarButton",
    "NewAvatarButton",
]
