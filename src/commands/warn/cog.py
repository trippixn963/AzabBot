"""
AzabBot - Warn Cog
==================

Warning command implementation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, has_mod_role, EmbedColors
from src.api.services.event_logger import event_logger
from src.core.database import get_db
from src.utils.validation import (
    validate_moderation_target,
    validate_evidence,
    get_target_guild,
    is_cross_server,
)
from src.utils.discord_rate_limit import log_http_error
from src.views import CaseButtonView
from src.utils.async_utils import gather_with_logging
from src.core.constants import CASE_LOG_TIMEOUT, MODERATION_REASONS

from .modals import WarnModal
from .helpers import send_warn_dm, log_warn_to_tracker, broadcast_case_event, post_mod_log

if TYPE_CHECKING:
    from src.bot import AzabBot


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
        """
        try:
            # Get Target Guild (for cross-server moderation)
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

            # Validation (using centralized validation module)
            result = await validate_moderation_target(
                interaction=interaction,
                target=user,
                bot=self.bot,
                action="warn",
                require_member=False,
                check_bot_hierarchy=False,
            )

            if not result.is_valid:
                await interaction.followup.send(result.error_message, ephemeral=True)
                return

            # Record Warning
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

            # Log to dashboard events
            event_logger.log_warn(
                guild=target_guild,
                target=user,
                moderator=interaction.user,
                reason=reason,
                active_warns=active_warns,
                total_warns=total_warns,
            )

            # Log to Case Forum (creates per-action case)
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

            # Log to Permanent Audit Log
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

            # Build & Send Embed
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

            embed.set_thumbnail(url=avatar_url)

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

            # Concurrent Post-Response Operations
            await gather_with_logging(
                ("DM User", send_warn_dm(
                    user=user,
                    guild=target_guild,
                    moderator=interaction.user,
                    reason=reason,
                    evidence=evidence,
                    active_warns=active_warns,
                    total_warns=total_warns,
                    avatar_url=avatar_url,
                )),
                ("Post Mod Logs", post_mod_log(
                    bot=self.bot,
                    action="Warn",
                    user=target_member or user,
                    moderator=interaction.user,
                    reason=reason,
                    active_warns=active_warns,
                    total_warns=total_warns,
                )),
                ("Mod Tracker", log_warn_to_tracker(
                    bot=self.bot,
                    moderator=interaction.user,
                    target=target_member or user,
                    reason=reason,
                )),
                ("WebSocket Broadcast", broadcast_case_event(
                    bot=self.bot,
                    case_info=case_info,
                    user_id=user.id,
                    moderator_id=interaction.user.id,
                    reason=reason,
                    active_warns=active_warns,
                    total_warns=total_warns,
                )),
                context="Warn Command",
            )

        except discord.HTTPException as e:
            log_http_error(e, "Warn Command", [
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Target", f"{user.name} ({user.id})"),
            ])
            try:
                await interaction.followup.send(
                    "An error occurred while issuing the warning.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass

        except Exception as e:
            logger.error("Warn Command Failed", [
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Target", f"{user.name} ({user.id})"),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:100]),
            ])
            try:
                await interaction.followup.send(
                    "An unexpected error occurred.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass

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
        # Validate evidence attachment
        evidence_result = validate_evidence(evidence, "warn")
        if not evidence_result.is_valid:
            await interaction.response.send_message(
                evidence_result.error_message,
                ephemeral=True,
            )
            return

        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=False)
        except discord.HTTPException:
            pass  # Interaction already responded or expired
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


__all__ = ["WarnCog"]
