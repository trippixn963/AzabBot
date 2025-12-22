"""
Azab Discord Bot - Shared UI Views
===================================

Reusable UI components for moderation commands.

Features:
    - InfoButton: Persistent button showing user details
    - CaseButtonView: View with Case link and Info button

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from datetime import datetime
from typing import TYPE_CHECKING

import discord

from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# UI Constants
# =============================================================================

CASE_EMOJI = "<:case:1452426909077213255>"
INFO_EMOJI = "<:info:1452426910901604362>"


# =============================================================================
# Persistent Info Button
# =============================================================================

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
        db = get_db()

        # Get member from guild
        guild = interaction.client.get_guild(self.guild_id)
        if not guild:
            await interaction.response.send_message(
                "Could not find guild.",
                ephemeral=True,
            )
            return

        member = guild.get_member(self.user_id)

        # Build info embed
        embed = discord.Embed(
            title="📋 User Info",
            color=EmbedColors.INFO,
        )

        if member:
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Username", value=f"`{member.name}`", inline=True)
            embed.add_field(name="Display Name", value=f"`{member.display_name}`", inline=True)
            embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)

            # Discord account creation
            embed.add_field(
                name="Discord Joined",
                value=f"<t:{int(member.created_at.timestamp())}:R>",
                inline=True,
            )

            # Server join date
            if member.joined_at:
                embed.add_field(
                    name="Server Joined",
                    value=f"<t:{int(member.joined_at.timestamp())}:R>",
                    inline=True,
                )

            # Account age
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
            # User not in server (banned/left)
            try:
                user = await interaction.client.fetch_user(self.user_id)
                embed.set_thumbnail(url=user.display_avatar.url)
                embed.add_field(name="Username", value=f"`{user.name}`", inline=True)
                embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)
                embed.add_field(name="Status", value="⚠️ Not in Server", inline=True)
            except Exception:
                embed.add_field(name="User ID", value=f"`{self.user_id}`", inline=True)
                embed.add_field(name="Status", value="⚠️ User Not Found", inline=True)

        # Mute count
        mute_count = db.get_user_mute_count(self.user_id, self.guild_id)
        embed.add_field(
            name="Total Mutes",
            value=f"`{mute_count}`" if mute_count > 0 else "`0`",
            inline=True,
        )

        # Ban count
        ban_count = db.get_user_ban_count(self.user_id, self.guild_id)
        embed.add_field(
            name="Total Bans",
            value=f"`{ban_count}`" if ban_count > 0 else "`0`",
            inline=True,
        )

        # Warning for repeat offenders
        if mute_count >= 3 or ban_count >= 2:
            warnings = []
            if mute_count >= 3:
                warnings.append(f"{mute_count} mutes")
            if ban_count >= 2:
                warnings.append(f"{ban_count} bans")
            embed.add_field(
                name="⚠️ Warning",
                value=f"Repeat offender: {', '.join(warnings)}",
                inline=False,
            )

        set_footer(embed)

        await interaction.response.send_message(embed=embed, ephemeral=True)


# =============================================================================
# Case Button View
# =============================================================================

class CaseButtonView(discord.ui.View):
    """View with Case link and Info buttons."""

    def __init__(self, guild_id: int, thread_id: int, user_id: int):
        super().__init__(timeout=None)

        # Case link button
        url = f"https://discord.com/channels/{guild_id}/{thread_id}"
        self.add_item(discord.ui.Button(
            label="Case",
            url=url,
            style=discord.ButtonStyle.link,
            emoji=CASE_EMOJI,
        ))

        # Info button (persistent)
        self.add_item(InfoButton(user_id, guild_id))


# =============================================================================
# View Registration
# =============================================================================

def setup_moderation_views(bot: "AzabBot") -> None:
    """
    Register persistent views for moderation buttons.

    Call this on bot startup to enable button persistence after restart.
    """
    bot.add_dynamic_items(InfoButton)


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "CASE_EMOJI",
    "INFO_EMOJI",
    "InfoButton",
    "CaseButtonView",
    "setup_moderation_views",
]
