"""
AzabBot - Warn Command Cog
==========================

Server moderation warning command with case logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, has_mod_role, EmbedColors, NY_TZ
from src.core.database import get_db
from src.core.moderation_validation import (
    validate_moderation_target,
    validate_evidence,
    get_target_guild,
    is_cross_server,
)
from src.utils.footer import set_footer
from src.views import CaseButtonView
from src.utils.async_utils import gather_with_logging
from src.utils.dm_helpers import send_moderation_dm
from src.core.constants import CASE_LOG_TIMEOUT, MODERATION_REASONS, MODAL_FIELD_MEDIUM

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Warn Modal (for context menu)
# =============================================================================

class WarnModal(discord.ui.Modal, title="Warn User"):
    """Modal for warning a user from context menu."""

    reason_input = discord.ui.TextInput(
        label="Reason",
        placeholder="Reason for the warning",
        required=False,
        max_length=MODAL_FIELD_MEDIUM,
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
        logger.tree("Warn Modal Submitted", [
            ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ("Target", f"{self.target_user.name} ({self.target_user.id})"),
        ], emoji="📋")

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
        ], emoji="📋")

    # =========================================================================
    # Permission Check
    # =========================================================================

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has permission to use warn commands."""
        return has_mod_role(interaction.user)

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

        for reason in MODERATION_REASONS:
            if current_lower in reason.lower():
                choices.append(app_commands.Choice(name=reason, value=reason))

        if current and current not in MODERATION_REASONS:
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

        target_guild = get_target_guild(interaction, self.bot)
        if not target_guild:
            await interaction.followup.send(
                "❌ Could not find target guild.",
                ephemeral=True,
            )
            return

        cross_server = is_cross_server(interaction)

        # Try to get member from target guild for role checks
        target_member = target_guild.get_member(user.id)

        # ---------------------------------------------------------------------
        # Validation (using centralized validation module)
        # ---------------------------------------------------------------------

        result = await validate_moderation_target(
            interaction=interaction,
            target=user,
            bot=self.bot,
            action="warn",
            require_member=False,  # Can warn users not in server
            check_bot_hierarchy=False,  # No role assignment for warns
        )

        if not result.is_valid:
            await interaction.followup.send(result.error_message, ephemeral=True)
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
            ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                    ("ID", str(user.id)),
            ("Moderator", str(interaction.user)),
            ("Active Warnings", str(active_warns)),
            ("Total Warnings", str(total_warns)),
            ("Reason", (reason or "None")[:50]),
        ]
        if cross_server:
            log_items.insert(1, ("Cross-Server", f"From {interaction.guild.name} → {target_guild.name}"))
        logger.tree("USER WARNED", log_items, emoji="👮")

        # ---------------------------------------------------------------------
        # Log to Case Forum (creates per-action case)
        # ---------------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            try:
                case_info = await asyncio.wait_for(
                    self.bot.case_log_service.log_warn(
                        user=target_member or user,
                        moderator=interaction.user,
                        reason=reason,
                        evidence=evidence,
                        active_warns=active_warns,
                        total_warns=total_warns,
                    ),
                    timeout=CASE_LOG_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("Case Log Timeout", [
                    ("Action", "Warn"),
                    ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                    ("ID", str(user.id)),
                ])
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Log Timeout",
                        f"Warn case logging timed out for {user} ({user.id})"
                    )
            except Exception as e:
                logger.error("Case Log Failed", [
                    ("Action", "Warn"),
                    ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                    ("ID", str(user.id)),
                    ("Error", str(e)[:100]),
                ])
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Log Failed",
                        f"Warn case logging failed for {user} ({user.id}): {str(e)[:200]}"
                    )

        # ---------------------------------------------------------------------
        # Log to Permanent Audit Log
        # ---------------------------------------------------------------------

        self.db.log_moderation_action(
            user_id=user.id,
            guild_id=target_guild.id,
            moderator_id=interaction.user.id,
            action_type="warn",
            action_source="manual",
            reason=reason,
            details={"evidence": evidence, "cross_server": cross_server, "active_warns": active_warns, "total_warns": total_warns},
            case_id=case_info["case_id"] if case_info else None,
        )

        # ---------------------------------------------------------------------
        # Build & Send Embed
        # ---------------------------------------------------------------------

        display_name = target_member.display_name if target_member else user.name
        avatar_url = target_member.display_avatar.url if target_member else user.display_avatar.url

        embed = discord.Embed(
            title="⚠️ User Warned",
            color=EmbedColors.GOLD,
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)

        # Show active warnings with total in parentheses if different
        if active_warns != total_warns:
            embed.add_field(name="Warnings", value=f"`{active_warns}` active\n(`{total_warns}` total)", inline=True)
        else:
            embed.add_field(name="Warning #", value=f"`{active_warns}`", inline=True)

        if case_info:
            embed.add_field(name="Case", value=f"`#{case_info['case_id']}`", inline=True)

        # Note: Reason and evidence are intentionally not shown in public embed
        # They're only visible in DMs, case logs, and mod logs

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
            logger.error("Warn Followup Failed", [
                ("User", f"{user.name} ({user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error", str(e)[:100]),
            ])

        # ---------------------------------------------------------------------
        # Concurrent Post-Response Operations
        # ---------------------------------------------------------------------

        await gather_with_logging(
            ("DM User", self._send_warn_dm(
                user=user,
                guild=target_guild,
                moderator=interaction.user,
                reason=reason,
                evidence=evidence,
                active_warns=active_warns,
                total_warns=total_warns,
                avatar_url=avatar_url,
            )),
            ("Post Mod Logs", self._post_mod_log(
                action="Warn",
                user=target_member or user,
                moderator=interaction.user,
                reason=reason,
                active_warns=active_warns,
                total_warns=total_warns,
                color=EmbedColors.WARNING,
            )),
            ("Mod Tracker", self._log_warn_to_tracker(
                moderator=interaction.user,
                target=target_member or user,
                reason=reason,
            )),
            context="Warn Command",
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
    @app_commands.autocomplete(reason=reason_autocomplete)
    async def warn(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str,
        evidence: Optional[discord.Attachment] = None,
    ) -> None:
        """Issue a warning to a user (supports cross-server from mod server)."""
        # Validate evidence attachment (content type, file size, CDN expiry warning)
        evidence_result = validate_evidence(evidence, "warn")
        if not evidence_result.is_valid:
            await interaction.response.send_message(
                evidence_result.error_message,
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=False)
        await self.execute_warn(interaction, user, reason, evidence_result.url)

    # =========================================================================
    # Context Menu Handlers
    # =========================================================================

    async def _warn_from_message(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> None:
        """Warn the author of a message (context menu handler)."""
        if not has_mod_role(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True,
            )
            return

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
        if not has_mod_role(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True,
            )
            return

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

    async def _send_warn_dm(
        self,
        user: discord.User,
        guild: discord.Guild,
        moderator: discord.Member,
        reason: Optional[str],
        evidence: Optional[str],
        active_warns: int,
        total_warns: int,
        avatar_url: str,
    ) -> None:
        """Send DM notification to warned user."""
        # Build warning count field
        if active_warns != total_warns:
            warn_field = ("Active Warnings", f"`{active_warns}` (`{total_warns}` total)", True)
        else:
            warn_field = ("Warning #", f"`{active_warns}`", True)

        await send_moderation_dm(
            user=user,
            title="You have been warned",
            color=EmbedColors.WARNING,
            guild=guild,
            moderator=moderator,
            reason=reason,
            evidence=evidence,
            thumbnail_url=avatar_url,
            fields=[warn_field],
            context="Warn DM",
        )

    async def _log_warn_to_tracker(
        self,
        moderator: discord.Member,
        target: discord.User,
        reason: Optional[str],
    ) -> None:
        """Log warn action to mod tracker if moderator is tracked."""
        if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(moderator.id):
            await self.bot.mod_tracker.log_warn(
                mod=moderator,
                target=target,
                reason=reason,
            )

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
        """Post a warning action to the server logs forum via logging service."""
        if not self.bot.logging_service:
            return

        try:
            guild = moderator.guild

            if action.lower() == "warn":
                await self.bot.logging_service.log_warning_issued(
                    guild=guild,
                    target=user,
                    moderator=moderator,
                    reason=reason,
                    warning_count=active_warns,
                )
            elif action.lower() == "unwarn":
                await self.bot.logging_service.log_warning_removed(
                    guild=guild,
                    target=user,
                    moderator=moderator,
                    reason=reason,
                )
        except Exception as e:
            logger.error("Mod Log Post Failed", [("Error", str(e)[:50])])


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the Warn cog."""
    await bot.add_cog(WarnCog(bot))
