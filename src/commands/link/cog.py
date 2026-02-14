"""
AzabBot - Link Cog
==================

Links alliance channel messages to members for auto-deletion on leave.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.validation import get_target_guild, is_cross_server
from src.utils.interaction import safe_respond
from src.utils.discord_rate_limit import log_http_error

from .views import LinkConfirmView

if TYPE_CHECKING:
    from src.bot import AzabBot


class LinkCog(commands.Cog):
    """Cog for linking messages to members. Supports cross-server moderation."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        logger.tree("Link Cog Loaded", [
            ("Commands", "/link"),
            ("Alliances Channel", str(self.config.alliances_channel_id) if self.config.alliances_channel_id else "Not configured"),
            ("Cross-Server", "Enabled"),
        ], emoji="🔗")

    # =========================================================================
    # Link Command
    # =========================================================================

    @app_commands.command(name="link", description="Link an alliance message to a member")
    @app_commands.describe(
        message_id="The message ID to link",
        member_id="The member ID to link the message to")
    async def link(
        self,
        interaction: discord.Interaction,
        message_id: str,
        member_id: str) -> None:
        """Link a message to a member for auto-deletion on leave."""
        try:
            # Permission check - only specific user IDs can use this command
            allowed_ids = {self.config.owner_id}
            if self.config.link_allowed_user_ids:
                allowed_ids |= self.config.link_allowed_user_ids
            if interaction.user.id not in allowed_ids:
                logger.tree("Link Command Denied", [
                    ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                    ("User ID", str(interaction.user.id)),
                    ("Reason", "Not in allowed user list"),
                ], emoji="🚫")
                await interaction.response.send_message(
                    "You don't have permission to use this command.",
                    ephemeral=True)
                return

            # Check if alliances channel is configured
            if not self.config.alliances_channel_id:
                logger.error("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Reason", "ALLIANCES_CHANNEL_ID not configured"),
                ])
                await interaction.response.send_message(
                    "Alliance channel is not configured.",
                    ephemeral=True)
                return

            # Parse message ID with range validation
            try:
                msg_id = int(message_id)
                # Discord snowflake IDs must be positive and fit in int64
                if msg_id <= 0 or msg_id > 9223372036854775807:
                    raise ValueError("ID out of range")
            except ValueError:
                logger.warning("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Message ID", message_id),
                    ("Reason", "Invalid message ID format"),
                ])
                await interaction.response.send_message(
                    "Invalid message ID. Please provide a valid Discord ID.",
                    ephemeral=True)
                return

            # Parse member ID with range validation
            try:
                parsed_member_id = int(member_id)
                # Discord snowflake IDs must be positive and fit in int64
                if parsed_member_id <= 0 or parsed_member_id > 9223372036854775807:
                    raise ValueError("ID out of range")
            except ValueError:
                logger.warning("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Member ID", member_id),
                    ("Reason", "Invalid member ID format"),
                ])
                await interaction.response.send_message(
                    "Invalid member ID. Please provide a valid Discord ID.",
                    ephemeral=True)
                return

            # Get target guild (supports cross-server)
            target_guild = get_target_guild(interaction, self.bot)
            cross_server = is_cross_server(interaction)

            # Fetch member from target guild
            member = target_guild.get_member(parsed_member_id)
            if not member:
                logger.warning("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Member ID", str(parsed_member_id)),
                    ("Reason", "Member not found in target guild"),
                    ("Target Guild", target_guild.name),
                ])
                await interaction.response.send_message(
                    f"Member with ID `{parsed_member_id}` not found in {target_guild.name}.",
                    ephemeral=True)
                return

            logger.tree("Link Command Started", [
                ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("Mod ID", str(interaction.user.id)),
                ("Message ID", str(msg_id)),
                ("Target Member", f"{member} ({member.id})"),
                ("Target Guild", target_guild.name),
                ("Cross-Server", "Yes" if cross_server else "No"),
            ], emoji="🔗")

            # Get the alliances channel from target guild
            channel = target_guild.get_channel(self.config.alliances_channel_id)
            if not channel:
                logger.error("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Reason", "Alliance channel not found"),
                    ("Guild", target_guild.name),
                ])
                await interaction.response.send_message(
                    f"Alliance channel not found in {target_guild.name}.",
                    ephemeral=True)
                return

            # Verify message exists
            try:
                message = await channel.fetch_message(msg_id)
            except discord.NotFound:
                logger.warning("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Message ID", str(msg_id)),
                    ("Reason", "Message not found"),
                ])
                await interaction.response.send_message(
                    "Message not found in the alliance channel.",
                    ephemeral=True)
                return
            except discord.HTTPException as e:
                log_http_error(e, "Link Message Fetch", [
                    ("User", str(interaction.user)),
                    ("Message ID", str(msg_id)),
                ])
                await interaction.response.send_message(
                    f"Failed to fetch message: {e}",
                    ephemeral=True)
                return

            # Check if already linked
            existing = self.db.get_linked_message(msg_id, channel.id)
            if existing:
                logger.warning("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Message ID", str(msg_id)),
                    ("Reason", "Message already linked"),
                    ("Linked To", str(existing['member_id'])),
                ])
                await interaction.response.send_message(
                    f"This message is already linked to <@{existing['member_id']}>.",
                    ephemeral=True)
                return

            # Create confirmation embed
            confirm_embed = discord.Embed(
                title="Confirm Message Link",
                description="Review the details below and click **Approve** to link this message.",
                color=EmbedColors.GOLD
            )

            confirm_embed.add_field(
                name="Member",
                value=f"{member.mention}\n`{member.id}`",
                inline=True)
            confirm_embed.add_field(
                name="Message",
                value=f"[Jump to Message]({message.jump_url})",
                inline=True)

            if cross_server:
                confirm_embed.add_field(
                    name="Server",
                    value=target_guild.name,
                    inline=True)

            # Show message preview
            if message.content:
                preview = message.content[:300]
                if len(message.content) > 300:
                    preview += "..."
                confirm_embed.add_field(
                    name="Message Preview",
                    value=f"```{preview}```",
                    inline=False)
            elif message.attachments:
                confirm_embed.add_field(
                    name="Message Content",
                    value=f"*{len(message.attachments)} attachment(s)*",
                    inline=False)
            elif message.embeds:
                confirm_embed.add_field(
                    name="Message Content",
                    value=f"*{len(message.embeds)} embed(s)*",
                    inline=False)

            # Create view with buttons
            view = LinkConfirmView(
                bot=self.bot,
                message=message,
                member=member,
                moderator=interaction.user,
                target_guild=target_guild,
                cross_server=cross_server)

            await interaction.response.send_message(
                embed=confirm_embed,
                view=view,
                ephemeral=True)

        except Exception as e:
            logger.error("Link Command Failed", [
                ("User", str(interaction.user)),
                ("Error", str(e)[:100]),
            ])
            await safe_respond(
                interaction,
                "An error occurred. Please try again.",
                ephemeral=True)


__all__ = ["LinkCog"]
