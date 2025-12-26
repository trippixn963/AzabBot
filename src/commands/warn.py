"""
Azab Discord Bot - Warn Command Cog
====================================

Server moderation warning command.

DESIGN:
    Issues warnings to users without applying any role or timeout.
    Warnings are tracked in the database and displayed in user history.

Features:
    - /warn <user> [reason] [evidence]: Issue a warning
    - Reason autocomplete with common options
    - Permission checks (moderator only)
    - DM notification to warned user
    - Case log integration
    - Mod tracker integration

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config, is_developer, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.views import CaseButtonView

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

REASON_CHOICES = [
    "Spam",
    "Inappropriate content",
    "Harassment",
    "Advertising",
    "NSFW content",
    "Trolling",
    "Disrespect",
    "Rule violation",
    "Bypassing filters",
    "Excessive mentions",
    "Off-topic discussion",
    "Impersonation",
]
"""Common warning reasons for autocomplete."""


# =============================================================================
# Warn Modal (for context menu)
# =============================================================================

class WarnModal(discord.ui.Modal, title="Warn User"):
    """Modal for warning a user from context menu."""

    reason_input = discord.ui.TextInput(
        label="Reason",
        placeholder="Reason for the warning",
        required=False,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )

    def __init__(
        self,
        bot: "AzabBot",
        target_user: discord.Member,
        evidence: Optional[str],
        cog: "WarnCog",
    ):
        super().__init__()
        self.bot = bot
        self.target_user = target_user
        self.evidence = evidence
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        reason = self.reason_input.value or None

        await interaction.response.defer(ephemeral=False)

        user = interaction.guild.get_member(self.target_user.id)
        if not user:
            await interaction.followup.send(
                "User not found in this server.",
                ephemeral=True,
            )
            return

        await self.cog.execute_warn(
            interaction=interaction,
            user=user,
            reason=reason,
            evidence=self.evidence,
        )


# =============================================================================
# Warn Cog
# =============================================================================

class WarnCog(commands.Cog):
    """Cog for warning users. Supports cross-server moderation from mod server."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        # Register context menus
        self.warn_message_ctx = app_commands.ContextMenu(
            name="Warn Author",
            callback=self._warn_from_message,
        )
        self.warn_user_ctx = app_commands.ContextMenu(
            name="Warn User",
            callback=self._warn_from_user,
        )
        self.bot.tree.add_command(self.warn_message_ctx)
        self.bot.tree.add_command(self.warn_user_ctx)

        logger.tree("Warn Cog Loaded", [
            ("Commands", "/warn, context menus"),
        ], emoji="⚠️")

    # =========================================================================
    # Cross-Server Helpers
    # =========================================================================

    def _get_target_guild(self, interaction: discord.Interaction) -> discord.Guild:
        """
        Get the target guild for moderation actions.

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
        """Check if this is a cross-server moderation action."""
        return (self.config.mod_server_id and
                self.config.logging_guild_id and
                interaction.guild.id == self.config.mod_server_id)

    async def cog_unload(self) -> None:
        """Unload the cog."""
        self.bot.tree.remove_command(self.warn_message_ctx.name, type=self.warn_message_ctx.type)
        self.bot.tree.remove_command(self.warn_user_ctx.name, type=self.warn_user_ctx.type)

    # =========================================================================
    # Autocomplete
    # =========================================================================

    async def reason_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for reason parameter."""
        choices = []
        current_lower = current.lower()

        for reason in REASON_CHOICES:
            if current_lower in reason.lower():
                choices.append(app_commands.Choice(name=reason, value=reason))

        if current and current not in REASON_CHOICES:
            choices.insert(0, app_commands.Choice(name=current, value=current))

        return choices[:25]

    # =========================================================================
    # Shared Warn Logic
    # =========================================================================

    async def execute_warn(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
    ) -> None:
        """
        Execute warn logic (shared by /warn command and context menu).

        Supports cross-server moderation: when run from mod server,
        the warning is recorded for the main server.

        Args:
            interaction: Discord interaction context.
            user: The user to warn.
            reason: Optional reason for warning.
            evidence: Optional evidence link/description.
        """
        # -----------------------------------------------------------------
        # Get Target Guild (for cross-server moderation)
        # -----------------------------------------------------------------

        target_guild = self._get_target_guild(interaction)
        is_cross_server = self._is_cross_server(interaction)

        # Try to get member from target guild for role checks
        target_member = target_guild.get_member(user.id)

        # ---------------------------------------------------------------------
        # Validation
        # ---------------------------------------------------------------------

        if user.id == interaction.user.id:
            logger.tree("WARN BLOCKED", [
                ("Reason", "Self-warn attempt"),
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
            ], emoji="🚫")
            await interaction.followup.send("You cannot warn yourself.", ephemeral=True)
            return

        if user.id == self.bot.user.id:
            logger.tree("WARN BLOCKED", [
                ("Reason", "Bot self-warn attempt"),
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
            ], emoji="🚫")
            await interaction.followup.send("I cannot warn myself.", ephemeral=True)
            return

        if user.bot:
            logger.tree("WARN BLOCKED", [
                ("Reason", "Target is a bot"),
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                ("Target", f"{user} ({user.id})"),
            ], emoji="🚫")
            await interaction.followup.send("I cannot warn bots.", ephemeral=True)
            return

        # Role hierarchy check (only if target is a member)
        if target_member and isinstance(interaction.user, discord.Member):
            mod_member = target_guild.get_member(interaction.user.id) if is_cross_server else interaction.user
            if mod_member and target_member.top_role >= mod_member.top_role and not is_developer(interaction.user.id):
                logger.tree("WARN BLOCKED", [
                    ("Reason", "Role hierarchy"),
                    ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                    ("Mod Role", mod_member.top_role.name),
                    ("Target", f"{user} ({user.id})"),
                    ("Target Role", target_member.top_role.name),
                ], emoji="🚫")
                await interaction.followup.send(
                    "You cannot warn someone with an equal or higher role.",
                    ephemeral=True,
                )
                return

        # ---------------------------------------------------------------------
        # Record Warning
        # ---------------------------------------------------------------------

        self.db.add_warning(
            user_id=user.id,
            guild_id=target_guild.id,
            moderator_id=interaction.user.id,
            reason=reason,
            evidence=evidence,
        )

        active_warns, total_warns = self.db.get_warn_counts(user.id, target_guild.id)

        log_items = [
            ("User", f"{user} ({user.id})"),
            ("Moderator", str(interaction.user)),
            ("Active Warnings", str(active_warns)),
            ("Total Warnings", str(total_warns)),
            ("Reason", (reason or "None")[:50]),
        ]
        if is_cross_server:
            log_items.insert(1, ("Cross-Server", f"From {interaction.guild.name} → {target_guild.name}"))
        logger.tree("USER WARNED", log_items, emoji="⚠️")

        # ---------------------------------------------------------------------
        # Log to Case Forum (creates per-action case)
        # ---------------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            case_info = await self.bot.case_log_service.log_warn(
                user=target_member or user,
                moderator=interaction.user,
                reason=reason,
                evidence=evidence,
                active_warns=active_warns,
                total_warns=total_warns,
            )

        # ---------------------------------------------------------------------
        # Build & Send Embed
        # ---------------------------------------------------------------------

        display_name = target_member.display_name if target_member else user.name
        avatar_url = target_member.display_avatar.url if target_member else user.display_avatar.url

        embed = discord.Embed(
            title="⚠️ User Warned",
            description=f"**{display_name}** has received a warning.",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="User", value=f"`{user.name}`\n{user.mention}", inline=True)
        embed.add_field(name="Moderator", value=f"`{interaction.user.display_name}`\n{interaction.user.mention}", inline=True)

        # Show active warnings with total in parentheses if different
        if active_warns != total_warns:
            embed.add_field(name="Warnings", value=f"`{active_warns}` active\n(`{total_warns}` total)", inline=True)
        else:
            embed.add_field(name="Warning #", value=f"`{active_warns}`", inline=True)

        if case_info:
            embed.add_field(name="Case", value=f"`#{case_info['case_id']}`", inline=True)

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        # Note: Evidence is intentionally not shown in public embed
        # It's only visible in DMs, case logs, and mod logs

        embed.set_thumbnail(url=avatar_url)
        set_footer(embed)

        sent_message = None
        try:
            if case_info:
                view = CaseButtonView(target_guild.id, case_info["thread_id"], user.id)
                sent_message = await interaction.followup.send(embed=embed, view=view)
            else:
                sent_message = await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Warn followup failed: {e}")

        # ---------------------------------------------------------------------
        # Concurrent Post-Response Operations
        # ---------------------------------------------------------------------

        async def _dm_user():
            try:
                dm_embed = discord.Embed(title="You have been warned", color=EmbedColors.WARNING)
                dm_embed.add_field(name="Server", value=f"`{target_guild.name}`", inline=False)
                if active_warns != total_warns:
                    dm_embed.add_field(name="Active Warnings", value=f"`{active_warns}` (`{total_warns}` total)", inline=True)
                else:
                    dm_embed.add_field(name="Warning #", value=f"`{active_warns}`", inline=True)
                dm_embed.add_field(name="Moderator", value=f"`{interaction.user.display_name}`", inline=True)
                dm_embed.add_field(name="Reason", value=f"`{reason or 'No reason provided'}`", inline=False)
                if evidence:
                    dm_embed.add_field(name="Evidence", value=evidence, inline=False)
                dm_embed.set_thumbnail(url=avatar_url)
                set_footer(dm_embed)
                await user.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

        async def _post_logs():
            await self._post_mod_log(
                action="Warn",
                user=target_member or user,
                moderator=interaction.user,
                reason=reason,
                active_warns=active_warns,
                total_warns=total_warns,
                color=EmbedColors.WARNING,
            )

        async def _mod_tracker():
            if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(interaction.user.id):
                await self.bot.mod_tracker.log_warn(
                    mod=interaction.user,
                    target=target_member or user,
                    reason=reason,
                )

        # Run all post-response operations concurrently
        await asyncio.gather(
            _dm_user(),
            _post_logs(),
            _mod_tracker(),
            return_exceptions=True,
        )

    # =========================================================================
    # Warn Command
    # =========================================================================

    @app_commands.command(name="warn", description="Issue a warning to a user")
    @app_commands.describe(
        user="The user to warn",
        reason="Reason for the warning (required)",
        evidence="Screenshot or video evidence (image/video only)",
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.autocomplete(reason=reason_autocomplete)
    async def warn(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str,
        evidence: Optional[discord.Attachment] = None,
    ) -> None:
        """Issue a warning to a user (supports cross-server from mod server)."""
        # Validate attachment is image/video if provided
        evidence_url = None
        if evidence:
            valid_types = ('image/', 'video/')
            if not evidence.content_type or not evidence.content_type.startswith(valid_types):
                await interaction.response.send_message(
                    "Evidence must be an image or video file.",
                    ephemeral=True,
                )
                return
            evidence_url = evidence.url

        await interaction.response.defer(ephemeral=False)
        await self.execute_warn(interaction, user, reason, evidence_url)

    # =========================================================================
    # Context Menu Handlers
    # =========================================================================

    async def _warn_from_message(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> None:
        """Warn the author of a message (context menu handler)."""
        if message.author.bot:
            await interaction.response.send_message(
                "I cannot warn bots.",
                ephemeral=True,
            )
            return

        # Get evidence from message attachment if it's an image/video
        evidence = None
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith(('image/', 'video/')):
                evidence = attachment.url
                break

        user = interaction.guild.get_member(message.author.id)
        if not user:
            await interaction.response.send_message(
                "User is no longer in this server.",
                ephemeral=True,
            )
            return

        modal = WarnModal(self.bot, user, evidence, self)
        await interaction.response.send_modal(modal)

    async def _warn_from_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        """Warn a user directly (context menu handler)."""
        if user.bot:
            await interaction.response.send_message(
                "I cannot warn bots.",
                ephemeral=True,
            )
            return

        modal = WarnModal(self.bot, user, None, self)
        await interaction.response.send_modal(modal)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def _post_mod_log(
        self,
        action: str,
        user: discord.User,
        moderator: discord.Member,
        reason: Optional[str] = None,
        active_warns: int = 1,
        total_warns: int = 1,
        color: int = EmbedColors.INFO,
    ) -> None:
        """Post an action to the mod log channel."""
        log_channel = self.bot.get_channel(self.config.logs_channel_id)
        if not log_channel:
            return

        embed = discord.Embed(
            title=f"Moderation: {action}",
            color=color,
            timestamp=datetime.now(NY_TZ),
        )

        embed.add_field(name="User", value=f"{user.mention}\n`{user.name}`", inline=True)
        embed.add_field(name="Moderator", value=f"{moderator.mention}\n`{moderator.display_name}`", inline=True)

        if active_warns != total_warns:
            embed.add_field(name="Warnings", value=f"{active_warns} active ({total_warns} total)", inline=True)
        else:
            embed.add_field(name="Warning #", value=str(active_warns), inline=True)

        embed.add_field(
            name="Reason",
            value=reason or "No reason provided",
            inline=False,
        )

        embed.set_thumbnail(url=user.display_avatar.url)
        set_footer(embed)

        try:
            await log_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to post to mod log: {e}")


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the Warn cog."""
    await bot.add_cog(WarnCog(bot))
