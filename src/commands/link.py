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
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Custom emojis (black themed) - these are server emoji IDs, not user/role IDs
APPROVE_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon18", id=1454788180485345341)
DENY_EMOJI = discord.PartialEmoji(name="deny", id=1454788303567065242)


# =============================================================================
# Link Confirmation View
# =============================================================================

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
        super().__init__(timeout=60)
        self.bot = bot
        self.message = message
        self.member = member
        self.moderator = moderator
        self.target_guild = target_guild
        self.is_cross_server = is_cross_server
        self.db = get_db()

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.secondary, emoji=APPROVE_EMOJI)
    async def approve_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Handle approve button click."""
        # Only the original moderator can approve
        if interaction.user.id != self.moderator.id:
            await interaction.response.send_message(
                "Only the moderator who initiated this can approve.",
                ephemeral=True,
            )
            return

        # Save the link
        saved = self.db.save_linked_message(
            message_id=self.message.id,
            channel_id=self.message.channel.id,
            member_id=self.member.id,
            guild_id=self.target_guild.id,
            linked_by=self.moderator.id,
        )

        if not saved:
            await interaction.response.edit_message(
                content="Failed to save link. Message may already be linked.",
                embed=None,
                view=None,
            )
            return

        log_items = [
            ("Message ID", str(self.message.id)),
            ("Member", f"{self.member} ({self.member.id})"),
            ("Linked By", str(self.moderator)),
        ]
        if self.is_cross_server:
            log_items.insert(1, ("Cross-Server", f"From {interaction.guild.name} → {self.target_guild.name}"))
        logger.tree("Message Linked", log_items, emoji="🔗")

        # Update the confirmation message
        success_embed = discord.Embed(
            title="Message Linked",
            description=(
                f"Successfully linked message to {self.member.mention}.\n"
                f"The message will be deleted if they leave the server."
            ),
            color=EmbedColors.GREEN,
            timestamp=datetime.now(NY_TZ),
        )
        success_embed.add_field(
            name="Message",
            value=f"[Jump to Message]({self.message.jump_url})",
            inline=True,
        )
        success_embed.add_field(
            name="Member",
            value=f"{self.member.mention}\n`{self.member.id}`",
            inline=True,
        )
        if self.is_cross_server:
            success_embed.add_field(
                name="Server",
                value=self.target_guild.name,
                inline=True,
            )
        set_footer(success_embed)

        await interaction.response.edit_message(
            embed=success_embed,
            view=None,
        )

        # Log to server logs
        await self._log_link_created(interaction)

        self.stop()

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.secondary, emoji=DENY_EMOJI)
    async def deny_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Handle deny button click."""
        # Only the original moderator can deny
        if interaction.user.id != self.moderator.id:
            await interaction.response.send_message(
                "Only the moderator who initiated this can deny.",
                ephemeral=True,
            )
            return

        logger.tree("Link Denied", [
            ("Message ID", str(self.message.id)),
            ("Member", f"{self.member} ({self.member.id})"),
            ("Denied By", str(self.moderator)),
        ], emoji="❌")

        # Update the confirmation message
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

        self.stop()

    async def on_timeout(self) -> None:
        """Handle view timeout."""
        pass

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
    await bot.add_cog(LinkCog(bot))
    logger.debug("Link Cog Loaded")
