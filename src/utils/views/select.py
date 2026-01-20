"""
User Info Select View
=====================

Dropdown for user info actions (Info, Avatar, History).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger

from .constants import INFO_EMOJI, DOWNLOAD_EMOJI, HISTORY_EMOJI

if TYPE_CHECKING:
    from src.bot import AzabBot


class UserInfoSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"user_info_select:(?P<user_id>\d+):(?P<guild_id>\d+)"):
    """
    Persistent dropdown for user info actions.

    Options: Info, Avatar, History
    Used across case logs, appeals, modmail, and tickets.
    """

    def __init__(self, user_id: int, guild_id: int):
        select = discord.ui.Select(
            placeholder="👤 User Info",
            options=[
                discord.SelectOption(
                    label="Info",
                    value="info",
                    emoji=INFO_EMOJI,
                    description="View user details",
                ),
                discord.SelectOption(
                    label="Avatar",
                    value="avatar",
                    emoji=DOWNLOAD_EMOJI,
                    description="Download user avatar",
                ),
                discord.SelectOption(
                    label="History",
                    value="history",
                    emoji=HISTORY_EMOJI,
                    description="View moderation history",
                ),
            ],
            custom_id=f"user_info_select:{user_id}:{guild_id}",
            row=0,
        )
        super().__init__(select)
        self.user_id = user_id
        self.guild_id = guild_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Select,
        match: re.Match[str],
    ) -> "UserInfoSelect":
        user_id = int(match.group("user_id"))
        guild_id = int(match.group("guild_id"))
        return cls(user_id, guild_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle dropdown selection."""
        # Import here to avoid circular imports
        from .info import InfoButton, DownloadButton
        from .history import HistoryButton

        # Get selected value from the underlying Select item
        selected = self.item.values[0] if self.item.values else None

        logger.tree("User Info Dropdown Selected", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Selection", selected or "None"),
            ("Target User ID", str(self.user_id)),
            ("Channel", "DM" if isinstance(interaction.channel, discord.DMChannel) else (interaction.channel.name if hasattr(interaction.channel, 'name') else str(interaction.channel))),
        ], emoji="👤")

        if selected == "info":
            # Delegate to InfoButton's callback logic
            info_btn = InfoButton(self.user_id, self.guild_id)
            await info_btn.callback(interaction)
        elif selected == "avatar":
            # Delegate to DownloadButton's callback logic
            avatar_btn = DownloadButton(self.user_id)
            await avatar_btn.callback(interaction)
        elif selected == "history":
            # Delegate to HistoryButton's callback logic
            history_btn = HistoryButton(self.user_id, self.guild_id)
            await history_btn.callback(interaction)


__all__ = [
    "UserInfoSelect",
]
