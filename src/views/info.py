"""
AzabBot - Info Button Views
===========================

Buttons for displaying user info and downloading avatars.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from datetime import datetime
from typing import TYPE_CHECKING

import discord

from src.core.config import EmbedColors, NY_TZ
from src.core.database import get_db
from src.core.logger import logger
from src.core.constants import QUERY_LIMIT_TINY

from .constants import INFO_EMOJI, DOWNLOAD_EMOJI

if TYPE_CHECKING:
    from src.bot import AzabBot


class InfoButton(discord.ui.DynamicItem[discord.ui.Button], template=r"mod_info:(?P<user_id>\d+):(?P<guild_id>\d+)"):
    """
    Persistent info button that shows user details when clicked.

    Works after bot restart by using DynamicItem with regex pattern.
    """

    def __init__(self, user_id: int, guild_id: int):
        super().__init__(
            discord.ui.Button(
                label="Info",
                style=discord.ButtonStyle.secondary,
                emoji=INFO_EMOJI,
                custom_id=f"mod_info:{user_id}:{guild_id}",
            )
        )
        self.user_id = user_id
        self.guild_id = guild_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "InfoButton":
        """Reconstruct the button from the custom_id regex match."""
        user_id = int(match.group("user_id"))
        guild_id = int(match.group("guild_id"))
        return cls(user_id, guild_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show user info embed when clicked."""
        logger.tree("Info Button Clicked", [
            ("Clicked By", f"{interaction.user} ({interaction.user.id})"),
            ("Target User ID", str(self.user_id)),
            ("Guild ID", str(self.guild_id)),
        ], emoji="ℹ️")

        db = get_db()

        guild = interaction.client.get_guild(self.guild_id)
        if not guild:
            await interaction.response.send_message(
                "Could not find guild.",
                ephemeral=True,
            )
            return

        member = guild.get_member(self.user_id)

        embed = discord.Embed(
            title="📋 User Info",
            color=EmbedColors.INFO,
        )

        if member:
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Username", value=f"`{member.name}`", inline=True)
            embed.add_field(name="Display Name", value=f"`{member.display_name}`", inline=True)
            embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)

            embed.add_field(
                name="Discord Joined",
                value=f"<t:{int(member.created_at.timestamp())}:R>",
                inline=True,
            )

            if member.joined_at:
                embed.add_field(
                    name="Server Joined",
                    value=f"<t:{int(member.joined_at.timestamp())}:R>",
                    inline=True,
                )

            now = datetime.now(NY_TZ)
            created_at = member.created_at.replace(tzinfo=NY_TZ) if member.created_at.tzinfo is None else member.created_at
            age_days = (now - created_at).days
            if age_days < 30:
                age_str = f"{age_days} days"
            elif age_days < 365:
                age_str = f"{age_days // 30} months"
            else:
                age_str = f"{age_days // 365} years, {(age_days % 365) // 30} months"
            embed.add_field(name="Account Age", value=f"`{age_str}`", inline=True)
        else:
            try:
                user = await interaction.client.fetch_user(self.user_id)
                embed.set_thumbnail(url=user.display_avatar.url)
                embed.add_field(name="Username", value=f"`{user.name}`", inline=True)
                embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)
                embed.add_field(name="Status", value="⚠️ Not in Server", inline=True)
            except discord.HTTPException:
                # User may not exist or be fetchable
                embed.add_field(name="User ID", value=f"`{self.user_id}`", inline=True)
                embed.add_field(name="Status", value="⚠️ User Not Found", inline=True)

        mute_count = db.get_user_mute_count(self.user_id, self.guild_id)
        embed.add_field(
            name="Total Mutes",
            value=f"`{mute_count}`" if mute_count > 0 else "`0`",
            inline=True,
        )

        ban_count = db.get_user_ban_count(self.user_id, self.guild_id)
        embed.add_field(
            name="Total Bans",
            value=f"`{ban_count}`" if ban_count > 0 else "`0`",
            inline=True,
        )

        active_warns, total_warns = db.get_warn_counts(self.user_id, self.guild_id)
        if active_warns != total_warns:
            embed.add_field(
                name="Warnings",
                value=f"`{active_warns}` active (`{total_warns}` total)",
                inline=True,
            )
        else:
            embed.add_field(
                name="Warnings",
                value=f"`{active_warns}`",
                inline=True,
            )

        last_mute = db.get_last_mute_info(self.user_id)
        if last_mute and last_mute.get("last_mute_at"):
            mute_timestamp = int(last_mute["last_mute_at"])
            mute_duration = last_mute.get("last_mute_duration") or "Unknown"
            mute_mod_id = last_mute.get("last_mute_moderator_id")
            mute_mod_str = f"by <@{mute_mod_id}>" if mute_mod_id else ""
            embed.add_field(
                name="Last Muted",
                value=f"<t:{mute_timestamp}:R>\n`{mute_duration}` {mute_mod_str}",
                inline=True,
            )

        last_ban = db.get_last_ban_info(self.user_id)
        if last_ban and last_ban.get("last_ban_at"):
            ban_timestamp = int(last_ban["last_ban_at"])
            ban_mod_id = last_ban.get("last_ban_moderator_id")
            ban_mod_str = f"by <@{ban_mod_id}>" if ban_mod_id else ""
            embed.add_field(
                name="Last Banned",
                value=f"<t:{ban_timestamp}:R> {ban_mod_str}",
                inline=True,
            )

        if mute_count >= 3 or ban_count >= 2 or active_warns >= 3:
            warnings = []
            if mute_count >= 3:
                warnings.append(f"{mute_count} mutes")
            if ban_count >= 2:
                warnings.append(f"{ban_count} bans")
            if active_warns >= 3:
                warnings.append(f"{active_warns} warnings")
            embed.add_field(
                name="⚠️ Warning",
                value=f"Repeat offender: {', '.join(warnings)}",
                inline=False,
            )

        username_history = db.get_username_history(self.user_id, limit=QUERY_LIMIT_TINY)
        if username_history:
            history_lines = []
            for record in username_history:
                name = record.get("username") or record.get("display_name")
                if name:
                    timestamp = int(record.get("changed_at", 0))
                    history_lines.append(f"`{name}` <t:{timestamp}:R>")
            if history_lines:
                embed.add_field(
                    name="Previous Names",
                    value="\n".join(history_lines),
                    inline=False,
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)


class DownloadButton(discord.ui.DynamicItem[discord.ui.Button], template=r"download_pfp:(?P<user_id>\d+)"):
    """
    Persistent download button that sends avatar as ephemeral message.

    Works after bot restart by using DynamicItem with regex pattern.
    """

    def __init__(self, user_id: int):
        super().__init__(
            discord.ui.Button(
                label="Avatar",
                style=discord.ButtonStyle.secondary,
                emoji=DOWNLOAD_EMOJI,
                custom_id=f"download_pfp:{user_id}",
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "DownloadButton":
        """Reconstruct the button from the custom_id regex match."""
        user_id = int(match.group("user_id"))
        return cls(user_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Send avatar URL as ephemeral message."""
        logger.tree("Avatar Download Clicked", [
            ("Clicked By", f"{interaction.user} ({interaction.user.id})"),
            ("Target User ID", str(self.user_id)),
        ], emoji="📥")

        try:
            user = None
            if interaction.guild:
                user = interaction.guild.get_member(self.user_id)

            if not user:
                user = await interaction.client.fetch_user(self.user_id)

            avatar_url = user.display_avatar.replace(size=4096).url
            await interaction.response.send_message(avatar_url, ephemeral=True)
        except discord.NotFound:
            await interaction.response.send_message("User not found.", ephemeral=True)
        except discord.HTTPException:
            # Other Discord API error
            await interaction.response.send_message("Failed to fetch avatar.", ephemeral=True)


__all__ = [
    "InfoButton",
    "DownloadButton",
]
