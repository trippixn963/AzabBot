"""
Azab Discord Bot - Link Command Cog
====================================

Links alliance channel messages to members for auto-deletion on leave.

DESIGN:
    When a member posts in the alliances channel, moderators can link
    that message to the member. If the member leaves the server, their
    linked messages are automatically deleted.

    Supports cross-server moderation: command can be run from mod server
    to link messages in the main server's alliance channel.

Features:
    - /link <message_id> <member>: Link a message to a member
    - Confirmation flow with approve/deny buttons
    - Logging when links are created
    - Auto-delete linked messages on member leave with logging

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.core.constants import EMOJI_ID_APPROVE, EMOJI_ID_DENY
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Custom emojis (black themed) - IDs from constants.py
APPROVE_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon18", id=EMOJI_ID_APPROVE)
DENY_EMOJI = discord.PartialEmoji(name="deny", id=EMOJI_ID_DENY)


# =============================================================================
# Link Confirmation View
# =============================================================================

class LinkApproveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"la:(?P<msg>\d+):(?P<chan>\d+):(?P<mem>\d+):(?P<gid>\d+)"):
    """Persistent approve button for link confirmation."""

    def __init__(self, message_id: int, channel_id: int, member_id: int, guild_id: int):
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
        allowed_ids = {config.developer_id}
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

    def __init__(self, message_id: int, member_id: int):
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
        allowed_ids = {config.developer_id}
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
            color=EmbedColors.RED,
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
            logger.debug(f"Failed to log link creation: {e}")


# =============================================================================
# Link Cog
# =============================================================================

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
    # Cross-Server Helpers
    # =========================================================================

    def _get_target_guild(self, interaction: discord.Interaction) -> discord.Guild:
        """
        Get the target guild for the link command.

        If command is run from mod server, targets the main server.
        Otherwise, targets the current server.
        """
        if (self.config.mod_server_id and
            self.config.logging_guild_id and
            interaction.guild.id == self.config.mod_server_id):
            main_guild = self.bot.get_guild(self.config.logging_guild_id)
            if main_guild:
                return main_guild
        return interaction.guild

    def _is_cross_server(self, interaction: discord.Interaction) -> bool:
        """Check if this is a cross-server action."""
        return (self.config.mod_server_id and
                self.config.logging_guild_id and
                interaction.guild.id == self.config.mod_server_id)

    # =========================================================================
    # Link Command
    # =========================================================================

    @app_commands.command(name="link", description="Link an alliance message to a member")
    @app_commands.describe(
        message_id="The message ID to link",
        member_id="The member ID to link the message to",
    )
    async def link(
        self,
        interaction: discord.Interaction,
        message_id: str,
        member_id: str,
    ) -> None:
        """Link a message to a member for auto-deletion on leave."""
        try:
            # Permission check - only specific user IDs can use this command
            allowed_ids = {self.config.developer_id}
            if self.config.link_allowed_user_ids:
                allowed_ids |= self.config.link_allowed_user_ids
            if interaction.user.id not in allowed_ids:
                logger.tree("Link Command Denied", [
                    ("User", f"{interaction.user} ({interaction.user.id})"),
                    ("Reason", "Not in allowed user list"),
                ], emoji="🚫")
                await interaction.response.send_message(
                    "You don't have permission to use this command.",
                    ephemeral=True,
                )
                return

            # Check if alliances channel is configured
            if not self.config.alliances_channel_id:
                logger.error("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Reason", "ALLIANCES_CHANNEL_ID not configured"),
                ])
                await interaction.response.send_message(
                    "Alliance channel is not configured.",
                    ephemeral=True,
                )
                return

            # Parse message ID
            try:
                msg_id = int(message_id)
            except ValueError:
                logger.tree("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Message ID", message_id),
                    ("Reason", "Invalid message ID format"),
                ], emoji="⚠️")
                await interaction.response.send_message(
                    "Invalid message ID. Please provide a valid number.",
                    ephemeral=True,
                )
                return

            # Parse member ID
            try:
                parsed_member_id = int(member_id)
            except ValueError:
                logger.tree("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Member ID", member_id),
                    ("Reason", "Invalid member ID format"),
                ], emoji="⚠️")
                await interaction.response.send_message(
                    "Invalid member ID. Please provide a valid number.",
                    ephemeral=True,
                )
                return

            # Get target guild (supports cross-server)
            target_guild = self._get_target_guild(interaction)
            is_cross_server = self._is_cross_server(interaction)

            # Fetch member from target guild
            member = target_guild.get_member(parsed_member_id)
            if not member:
                logger.tree("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Member ID", str(parsed_member_id)),
                    ("Reason", "Member not found in target guild"),
                    ("Target Guild", target_guild.name),
                ], emoji="⚠️")
                await interaction.response.send_message(
                    f"Member with ID `{parsed_member_id}` not found in {target_guild.name}.",
                    ephemeral=True,
                )
                return

            logger.tree("Link Command Started", [
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                ("Message ID", str(msg_id)),
                ("Target Member", f"{member} ({member.id})"),
                ("Target Guild", target_guild.name),
                ("Cross-Server", "Yes" if is_cross_server else "No"),
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
                    ephemeral=True,
                )
                return

            # Verify message exists
            try:
                message = await channel.fetch_message(msg_id)
            except discord.NotFound:
                logger.tree("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Message ID", str(msg_id)),
                    ("Reason", "Message not found"),
                ], emoji="⚠️")
                await interaction.response.send_message(
                    "Message not found in the alliance channel.",
                    ephemeral=True,
                )
                return
            except discord.HTTPException as e:
                logger.error("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Message ID", str(msg_id)),
                    ("Error", str(e)[:50]),
                ])
                await interaction.response.send_message(
                    f"Failed to fetch message: {e}",
                    ephemeral=True,
                )
                return

            # Check if already linked
            existing = self.db.get_linked_message(msg_id, channel.id)
            if existing:
                logger.tree("Link Command Failed", [
                    ("User", str(interaction.user)),
                    ("Message ID", str(msg_id)),
                    ("Reason", "Message already linked"),
                    ("Linked To", str(existing['member_id'])),
                ], emoji="⚠️")
                await interaction.response.send_message(
                    f"This message is already linked to <@{existing['member_id']}>.",
                    ephemeral=True,
                )
                return

            # Create confirmation embed
            confirm_embed = discord.Embed(
                title="Confirm Message Link",
                description="Review the details below and click **Approve** to link this message.",
                color=EmbedColors.GOLD,
                timestamp=datetime.now(NY_TZ),
            )

            confirm_embed.add_field(
                name="Member",
                value=f"{member.mention}\n`{member.id}`",
                inline=True,
            )
            confirm_embed.add_field(
                name="Message",
                value=f"[Jump to Message]({message.jump_url})",
                inline=True,
            )

            if is_cross_server:
                confirm_embed.add_field(
                    name="Server",
                    value=target_guild.name,
                    inline=True,
                )

            # Show message preview
            if message.content:
                preview = message.content[:300]
                if len(message.content) > 300:
                    preview += "..."
                confirm_embed.add_field(
                    name="Message Preview",
                    value=f"```{preview}```",
                    inline=False,
                )
            elif message.attachments:
                confirm_embed.add_field(
                    name="Message Content",
                    value=f"*{len(message.attachments)} attachment(s)*",
                    inline=False,
                )
            elif message.embeds:
                confirm_embed.add_field(
                    name="Message Content",
                    value=f"*{len(message.embeds)} embed(s)*",
                    inline=False,
                )

            confirm_embed.set_footer(text="This will auto-delete the message if the member leaves")

            # Create view with buttons
            view = LinkConfirmView(
                bot=self.bot,
                message=message,
                member=member,
                moderator=interaction.user,
                target_guild=target_guild,
                is_cross_server=is_cross_server,
            )

            await interaction.response.send_message(
                embed=confirm_embed,
                view=view,
                ephemeral=True,
            )

        except Exception as e:
            logger.error("Link Command Failed", [
                ("User", str(interaction.user)),
                ("Error", str(e)[:100]),
            ])
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"An error occurred: {e}",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        f"An error occurred: {e}",
                        ephemeral=True,
                    )
            except Exception:
                pass


# =============================================================================
# Setup Function
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Add the link cog to the bot."""
    bot.add_dynamic_items(LinkApproveButton, LinkDenyButton)
    await bot.add_cog(LinkCog(bot))
    logger.debug("Link Cog Loaded")
