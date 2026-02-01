"""
AzabBot - Ban Operations Mixin
==============================

Execute ban method and context menu handlers.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import is_owner, has_mod_role, EmbedColors
from src.core.database import get_db
from src.core.moderation_validation import (
    validate_moderation_target,
    get_target_guild,
    is_cross_server,
    send_management_blocked_embed,
)
from src.utils.footer import set_footer
from src.views import CaseButtonView
from src.utils.async_utils import create_safe_task
from src.utils.dm_helpers import safe_send_dm, build_moderation_dm
from src.core.constants import CASE_LOG_TIMEOUT, GUILD_FETCH_TIMEOUT

from .views import BanModal

if TYPE_CHECKING:
    from .cog import BanCog


class BanOpsMixin:
    """Mixin for ban execution and context menu handlers."""

    async def execute_ban(
        self: "BanCog",
        interaction: discord.Interaction,
        user: discord.User,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
        is_softban: bool = False,
    ) -> bool:
        """
        Execute a ban with all validation and logging.

        Supports cross-server moderation: when run from mod server,
        the ban is executed on the main server.

        Returns True if successful, False otherwise.
        """
        # Defer if not already responded (with error handling for expired/failed interactions)
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except discord.HTTPException:
            pass  # Interaction already responded or expired

        # -----------------------------------------------------------------
        # Get Target Guild (for cross-server moderation)
        # -----------------------------------------------------------------

        target_guild = get_target_guild(interaction, self.bot)
        cross_server = is_cross_server(interaction)

        # Try to get member from target guild for role checks
        target_member = target_guild.get_member(user.id)

        # -----------------------------------------------------------------
        # Validation (using centralized validation module)
        # -----------------------------------------------------------------

        result = await validate_moderation_target(
            interaction=interaction,
            target=user,
            bot=self.bot,
            action="ban",
            require_member=False,  # Can ban users not in server
            check_bot_hierarchy=True,
        )

        if not result.is_valid:
            if result.should_log_attempt:
                await send_management_blocked_embed(interaction, "ban")
            else:
                await interaction.followup.send(result.error_message, ephemeral=True)
            return False

        # -----------------------------------------------------------------
        # Log to Case Forum FIRST (to get case_id for appeal button)
        # -----------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service and not is_softban:
            try:
                case_info = await asyncio.wait_for(
                    self.bot.case_log_service.log_ban(
                        user=user,
                        moderator=interaction.user,
                        reason=reason,
                        evidence=evidence,
                    ),
                    timeout=CASE_LOG_TIMEOUT,
                )
                if case_info:
                    logger.tree("Case Created", [
                        ("Action", "Ban"),
                        ("Case ID", case_info["case_id"]),
                        ("User", f"{user.name} ({user.id})"),
                    ], emoji="📋")
            except asyncio.TimeoutError:
                logger.warning("Case Log Timeout", [
                    ("Action", "Ban"),
                    ("User", user.name),
                    ("ID", str(user.id)),
                ])
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Log Timeout",
                        f"Ban case logging timed out for {user} ({user.id})"
                    )
            except Exception as e:
                logger.error("Case Log Failed", [
                    ("Action", "Ban"),
                    ("User", user.name),
                    ("ID", str(user.id)),
                    ("Error", str(e)[:100]),
                ])
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Log Failed",
                        f"Ban case logging failed for {user} ({user.id}): {str(e)[:200]}"
                    )

        # -----------------------------------------------------------------
        # DM User Before Ban (with appeal button if case was logged)
        # -----------------------------------------------------------------

        dm_sent = False
        if not is_softban:
            dm_embed = build_moderation_dm(
                title="You have been banned",
                color=EmbedColors.ERROR,
                guild=target_guild,
                moderator=interaction.user,
                reason=reason,
                thumbnail_url=user.display_avatar.url,
            )

            # Include appeal button in same DM if case was logged
            dm_view = None
            if case_info:
                from src.services.appeals import SubmitAppealButton
                dm_view = discord.ui.View(timeout=None)
                appeal_btn = SubmitAppealButton(case_info["case_id"], user.id)
                dm_view.add_item(appeal_btn)

            dm_sent = await safe_send_dm(user, embed=dm_embed, view=dm_view, context="Ban DM")

            logger.tree("Ban DM Sent", [
                ("User", user.name),
                ("ID", str(user.id)),
                ("Case", case_info["case_id"] if case_info else "N/A"),
                ("Appeal Button", "Yes" if dm_view else "No"),
                ("Delivered", "Yes" if dm_sent else "No (DMs disabled)"),
            ], emoji="📨")

        # -----------------------------------------------------------------
        # Execute Ban (on target guild)
        # -----------------------------------------------------------------

        action = "Softbanned" if is_softban else "Banned"
        ban_reason = f"{action} by {interaction.user}: {reason or 'No reason'}"

        try:
            await target_guild.ban(
                user,
                reason=ban_reason,
                delete_message_seconds=604800,  # 7 days
            )
        except discord.Forbidden:
            logger.warning("Ban Failed (Forbidden)", [
                ("User", f"{user.name} ({user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Guild", target_guild.name),
            ])
            await interaction.followup.send("I don't have permission to ban this user.", ephemeral=True)
            return False
        except discord.HTTPException as e:
            logger.error("Ban Failed (HTTP)", [
                ("User", f"{user.name} ({user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error", str(e)[:100]),
            ])
            await interaction.followup.send(f"Failed to ban: {e}", ephemeral=True)
            return False

        # -----------------------------------------------------------------
        # Softban: Immediate Unban
        # -----------------------------------------------------------------

        if is_softban:
            try:
                await target_guild.unban(user, reason=f"Softban by {interaction.user}")
            except Exception as e:
                logger.error("Softban Unban Failed", [("Error", str(e)[:50])])

            # Log softban to case forum (after execution, no appeal button)
            if self.bot.case_log_service:
                try:
                    case_info = await asyncio.wait_for(
                        self.bot.case_log_service.log_ban(
                            user=user,
                            moderator=interaction.user,
                            reason=f"[SOFTBAN] {reason}" if reason else "[SOFTBAN]",
                            evidence=evidence,
                        ),
                        timeout=CASE_LOG_TIMEOUT,
                    )
                    if case_info:
                        logger.tree("Case Created", [
                            ("Action", "Softban"),
                            ("Case ID", case_info["case_id"]),
                            ("User", f"{user.name} ({user.id})"),
                        ], emoji="📋")
                except asyncio.TimeoutError:
                    logger.warning("Case Log Timeout", [
                        ("Action", "Softban"),
                        ("User", user.name),
                        ("ID", str(user.id)),
                    ])
                except Exception as e:
                    logger.error("Case Log Failed", [
                        ("Action", "Softban"),
                        ("User", user.name),
                        ("ID", str(user.id)),
                        ("Error", str(e)[:100]),
                    ])

        # -----------------------------------------------------------------
        # Increment Ban Count (store moderator and reason for unban context)
        # -----------------------------------------------------------------

        db = get_db()
        ban_count = db.increment_ban_count(user.id, interaction.user.id, reason)

        # Record to ban history for History button
        db.add_ban(
            user_id=user.id,
            guild_id=target_guild.id,
            moderator_id=interaction.user.id,
            reason=reason,
        )

        # -----------------------------------------------------------------
        # Logging
        # -----------------------------------------------------------------

        log_type = "USER SOFTBANNED" if is_softban else "USER BANNED"
        log_items = [
            ("User", user.name),
                    ("ID", str(user.id)),
            ("Moderator", str(interaction.user)),
            ("Reason", (reason or "None")[:50]),
            ("Evidence", (evidence or "None")[:50]),
            ("Ban Count", str(ban_count)),
            ("DM Sent", "Yes" if dm_sent else "No"),
        ]
        if cross_server:
            log_items.insert(1, ("Cross-Server", f"From {interaction.guild.name} → {target_guild.name}"))
        logger.tree(log_type, log_items, emoji="🔨")

        # Server logs (uses case_id from earlier logging)
        if self.bot.logging_service and self.bot.logging_service.enabled:
            try:
                await asyncio.wait_for(
                    self.bot.logging_service.log_ban(
                        user=user,
                        reason=reason,
                        moderator=interaction.user,
                        case_id=case_info["case_id"] if case_info else None,
                    ),
                    timeout=GUILD_FETCH_TIMEOUT,
                )
            except Exception as e:
                logger.debug(f"Server log failed (ban): {e}")

        # -----------------------------------------------------------------
        # Build & Send Embed
        # -----------------------------------------------------------------

        title = "🧹 User Softbanned" if is_softban else "🔨 User Banned"
        embed = discord.Embed(
            title=title,
            color=EmbedColors.GOLD,
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)

        if case_info:
            embed.add_field(name="Case", value=f"`#{case_info['case_id']}`", inline=True)
        if ban_count > 1:
            embed.add_field(name="Ban Count", value=f"`{ban_count}`", inline=True)

        # Note: Reason/Evidence intentionally not shown in public embed
        # Only visible in DMs, case logs, and mod logs

        embed.set_thumbnail(url=user.display_avatar.url)
        set_footer(embed)

        sent_message = None
        try:
            if case_info:
                view = CaseButtonView(target_guild.id, case_info["thread_id"], user.id)
                sent_message = await interaction.followup.send(embed=embed, view=view)
            else:
                sent_message = await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error("Ban Followup Failed", [
                ("User", f"{user.name} ({user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error", str(e)[:100]),
            ])

        return True

    # =========================================================================
    # Context Menu Handlers
    # =========================================================================

    async def _ban_from_user(
        self: "BanCog",
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        """Ban a user directly (context menu handler)."""
        if not has_mod_role(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        if user.bot and not is_owner(interaction.user.id):
            await interaction.response.send_message(
                "You cannot ban bots.",
                ephemeral=True,
            )
            return

        modal = BanModal(target=user, cog=self, evidence=None)
        await interaction.response.send_modal(modal)

    async def _ban_from_message(
        self: "BanCog",
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> None:
        """Ban the author of a message (context menu handler)."""
        if not has_mod_role(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True,
            )
            return

        if message.author.bot and not is_owner(interaction.user.id):
            await interaction.response.send_message(
                "You cannot ban bots.",
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

        modal = BanModal(target=user, cog=self, evidence=evidence)
        await interaction.response.send_modal(modal)


__all__ = ["BanOpsMixin"]
