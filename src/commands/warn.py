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
        evidence: str,
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
    """Cog for warning users."""

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
        user: discord.Member,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
    ) -> None:
        """
        Execute warn logic (shared by /warn command and context menu).

        Args:
            interaction: Discord interaction context.
            user: The user to warn.
            reason: Optional reason for warning.
            evidence: Optional evidence link/description.
        """
        # ---------------------------------------------------------------------
        # Validation
        # ---------------------------------------------------------------------

        if user.id == interaction.user.id:
            await interaction.followup.send("You cannot warn yourself.", ephemeral=True)
            return

        if user.id == self.bot.user.id:
            await interaction.followup.send("I cannot warn myself.", ephemeral=True)
            return

        if user.bot:
            await interaction.followup.send("I cannot warn bots.", ephemeral=True)
            return

        if isinstance(interaction.user, discord.Member):
            if user.top_role >= interaction.user.top_role and not is_developer(interaction.user.id):
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
            guild_id=interaction.guild.id,
            moderator_id=interaction.user.id,
            reason=reason,
            evidence=evidence,
        )

        active_warns, total_warns = self.db.get_warn_counts(user.id, interaction.guild.id)

        logger.tree("USER WARNED", [
            ("User", f"{user} ({user.id})"),
            ("Moderator", str(interaction.user)),
            ("Active Warnings", str(active_warns)),
            ("Total Warnings", str(total_warns)),
            ("Reason", (reason or "None")[:50]),
        ], emoji="⚠️")

        # ---------------------------------------------------------------------
        # Prepare Case
        # ---------------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            case_info = await self.bot.case_log_service.prepare_case(user)

        # ---------------------------------------------------------------------
        # Build & Send Embed
        # ---------------------------------------------------------------------

        embed = discord.Embed(title="⚠️ User Warned", color=EmbedColors.WARNING)
        embed.add_field(name="User", value=f"`{user.name}` ({user.mention})", inline=False)
        embed.add_field(name="Moderator", value=f"{interaction.user.mention}\n`{interaction.user.display_name}`", inline=True)

        # Show active warnings with total in parentheses if different
        if active_warns != total_warns:
            embed.add_field(name="Warnings", value=f"`{active_warns}` active (`{total_warns}` total)", inline=True)
        else:
            embed.add_field(name="Warning #", value=f"`{active_warns}`", inline=True)

        if case_info:
            embed.add_field(name="Case ID", value=f"`{case_info['case_id']}`", inline=True)

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        if evidence:
            embed.add_field(name="Evidence", value=evidence, inline=False)

        embed.set_thumbnail(url=user.display_avatar.url)
        set_footer(embed)

        sent_message = None
        try:
            if case_info:
                view = CaseButtonView(interaction.guild.id, case_info["thread_id"], user.id)
                sent_message = await interaction.followup.send(embed=embed, view=view)
            else:
                sent_message = await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Warn followup failed: {e}")

        # ---------------------------------------------------------------------
        # Concurrent Post-Response Operations
        # ---------------------------------------------------------------------

        async def _log_to_case_forum():
            if self.bot.case_log_service and case_info and sent_message:
                await self.bot.case_log_service.log_warn(
                    user=user,
                    moderator=interaction.user,
                    reason=reason,
                    evidence=evidence,
                    active_warns=active_warns,
                    total_warns=total_warns,
                    source_message_url=sent_message.jump_url,
                )

        async def _dm_user():
            try:
                dm_embed = discord.Embed(title="You have been warned", color=EmbedColors.WARNING)
                dm_embed.add_field(name="Server", value=f"`{interaction.guild.name}`", inline=False)
                if active_warns != total_warns:
                    dm_embed.add_field(name="Active Warnings", value=f"`{active_warns}` (`{total_warns}` total)", inline=True)
                else:
                    dm_embed.add_field(name="Warning #", value=f"`{active_warns}`", inline=True)
                dm_embed.add_field(name="Moderator", value=f"`{interaction.user.display_name}`", inline=True)
                dm_embed.add_field(name="Reason", value=f"`{reason or 'No reason provided'}`", inline=False)
                if evidence:
                    dm_embed.add_field(name="Evidence", value=evidence, inline=False)
                dm_embed.set_thumbnail(url=user.display_avatar.url)
                set_footer(dm_embed)
                await user.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

        async def _post_logs():
            await self._post_mod_log(
                action="Warn",
                user=user,
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
                    target=user,
                    reason=reason,
                )

        # Run all post-response operations concurrently
        await asyncio.gather(
            _log_to_case_forum(),
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
        evidence="Message link or description of evidence",
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.autocomplete(reason=reason_autocomplete)
    async def warn(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str,
        evidence: Optional[str] = None,
    ) -> None:
        """Issue a warning to a user."""
        await interaction.response.defer(ephemeral=False)
        await self.execute_warn(interaction, user, reason, evidence)

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

        evidence = f"[Message]({message.jump_url})"
        if message.content:
            content_preview = message.content[:100] + ("..." if len(message.content) > 100 else "")
            evidence += f"\n> {content_preview}"

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

        modal = WarnModal(self.bot, user, "", self)
        await interaction.response.send_modal(modal)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def _post_mod_log(
        self,
        action: str,
        user: discord.Member,
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
