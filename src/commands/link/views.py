"""
AzabBot - Link Views
====================

Persistent views and buttons for link confirmation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer

from .constants import APPROVE_EMOJI, DENY_EMOJI

if TYPE_CHECKING:
    from src.bot import AzabBot


class LinkApproveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"la:(?P<msg>\d+):(?P<chan>\d+):(?P<mem>\d+):(?P<gid>\d+)"):
    """Persistent approve button for link confirmation."""

    def __init__(self, message_id: int, channel_id: int, member_id: int, guild_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Approve",
                style=discord.ButtonStyle.secondary,
                emoji=APPROVE_EMOJI,
                custom_id=f"la:{message_id}:{channel_id}:{member_id}:{guild_id}",
            )
        )
        self.message_id = message_id
        self.channel_id = channel_id
        self.member_id = member_id
        self.guild_id = guild_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match) -> "LinkApproveButton":
        return cls(
            int(match.group("msg")),
            int(match.group("chan")),
            int(match.group("mem")),
            int(match.group("gid")),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        # Check if user has permission (developer or in link_allowed_user_ids)
        config = get_config()
        allowed_ids = {config.owner_id}
        if config.link_allowed_user_ids:
            allowed_ids |= config.link_allowed_user_ids

        if interaction.user.id not in allowed_ids:
            await interaction.response.send_message(
                "You don't have permission to approve links.",
                ephemeral=True,
            )
            return

        db = get_db()
        bot = interaction.client

        # Save the link
        saved = db.save_linked_message(
            message_id=self.message_id,
            channel_id=self.channel_id,
            member_id=self.member_id,
            guild_id=self.guild_id,
            linked_by=interaction.user.id,
        )

        if not saved:
            await interaction.response.edit_message(
                content="Failed to save link. Message may already be linked.",
                embed=None,
                view=None,
            )
            return

        # Get member for display
        guild = bot.get_guild(self.guild_id)
        member = guild.get_member(self.member_id) if guild else None
        member_mention = f"<@{self.member_id}>"

        # Get message URL
        message_url = f"https://discord.com/channels/{self.guild_id}/{self.channel_id}/{self.message_id}"

        logger.tree("Message Linked", [
            ("Message ID", str(self.message_id)),
            ("Member", f"{member} ({self.member_id})" if member else str(self.member_id)),
            ("Linked By", str(interaction.user)),
        ], emoji="🔗")

        success_embed = discord.Embed(
            title="Message Linked",
            description=(
                f"Successfully linked message to {member_mention}.\n"
                f"The message will be deleted if they leave the server."
            ),
            color=EmbedColors.GREEN,
            timestamp=datetime.now(NY_TZ),
        )
        success_embed.add_field(
            name="Message",
            value=f"[Jump to Message]({message_url})",
            inline=True,
        )
        success_embed.add_field(
            name="Member",
            value=f"{member_mention}\n`{self.member_id}`",
            inline=True,
        )
        set_footer(success_embed)

        await interaction.response.edit_message(
            embed=success_embed,
            view=None,
        )


class LinkDenyButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ld:(?P<msg>\d+):(?P<mem>\d+)"):
    """Persistent deny button for link confirmation."""

    def __init__(self, message_id: int, member_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Deny",
                style=discord.ButtonStyle.secondary,
                emoji=DENY_EMOJI,
                custom_id=f"ld:{message_id}:{member_id}",
            )
        )
        self.message_id = message_id
        self.member_id = member_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match) -> "LinkDenyButton":
        return cls(
            int(match.group("msg")),
            int(match.group("mem")),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        # Check if user has permission
        config = get_config()
        allowed_ids = {config.owner_id}
        if config.link_allowed_user_ids:
            allowed_ids |= config.link_allowed_user_ids

        if interaction.user.id not in allowed_ids:
            await interaction.response.send_message(
                "You don't have permission to deny links.",
                ephemeral=True,
            )
            return

        logger.tree("Link Denied", [
            ("Message ID", str(self.message_id)),
            ("Member ID", str(self.member_id)),
            ("Denied By", str(interaction.user)),
        ], emoji="❌")

        deny_embed = discord.Embed(
            title="Link Cancelled",
            description="The link request was cancelled.",
            color=EmbedColors.GOLD,
            timestamp=datetime.now(NY_TZ),
        )
        set_footer(deny_embed)

        await interaction.response.edit_message(
            embed=deny_embed,
            view=None,
        )


class LinkConfirmView(discord.ui.View):
    """View with approve/deny buttons for link confirmation."""

    def __init__(
        self,
        bot: "AzabBot",
        message: discord.Message,
        member: discord.Member,
        moderator: discord.Member,
        target_guild: discord.Guild,
        is_cross_server: bool,
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.message = message
        self.member = member
        self.moderator = moderator
        self.target_guild = target_guild
        self.is_cross_server = is_cross_server

        # Add persistent buttons
        self.add_item(LinkApproveButton(
            message.id, message.channel.id, member.id, target_guild.id
        ))
        self.add_item(LinkDenyButton(message.id, member.id))

    async def _log_link_created(self, interaction: discord.Interaction) -> None:
        """Log link creation to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="🔗 Message Linked",
                color=EmbedColors.BLUE,
                timestamp=datetime.now(NY_TZ),
            )

            embed.add_field(
                name="Moderator",
                value=f"{self.moderator.mention}\n`{self.moderator.id}`",
                inline=True,
            )
            embed.add_field(
                name="Linked Member",
                value=f"{self.member.mention}\n`{self.member.id}`",
                inline=True,
            )
            embed.add_field(
                name="Channel",
                value=f"{self.message.channel.mention}",
                inline=True,
            )
            embed.add_field(
                name="Message",
                value=f"[Jump to Message]({self.message.jump_url})",
                inline=True,
            )

            if self.is_cross_server:
                embed.add_field(
                    name="Cross-Server",
                    value=f"From {interaction.guild.name} → {self.target_guild.name}",
                    inline=True,
                )

            # Show message preview if available
            if self.message.content:
                preview = self.message.content[:200]
                if len(self.message.content) > 200:
                    preview += "..."
                embed.add_field(
                    name="Message Preview",
                    value=f"```{preview}```",
                    inline=False,
                )

            set_footer(embed)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.ALLIANCES,
                embed,
            )

        except Exception as e:
            logger.debug("Link Log Failed", [("Error", str(e)[:50])])


__all__ = ["LinkApproveButton", "LinkDenyButton", "LinkConfirmView"]
