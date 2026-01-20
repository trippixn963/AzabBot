"""
Mute Command - Unmute Operations Mixin
======================================

Core unmute execution logic.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors
from src.core.moderation_validation import get_target_guild, is_cross_server
from src.utils.footer import set_footer
from src.utils.views import CaseButtonView
from src.utils.async_utils import gather_with_logging
from src.utils.duration import format_duration
from src.core.constants import CASE_LOG_TIMEOUT

if TYPE_CHECKING:
    from .cog import MuteCog


class UnmuteOpsMixin:
    """Mixin for unmute operation methods."""

    async def execute_unmute(
        self: "MuteCog",
        interaction: discord.Interaction,
        user: discord.User,
        reason: Optional[str] = None,
        skip_validation: bool = False,
    ) -> None:
        """
        Execute unmute logic (shared by /unmute command and context menu).

        Supports cross-server moderation: when run from mod server,
        the unmute is executed on the main server.

        Args:
            interaction: Discord interaction (must be deferred).
            user: User to unmute.
            reason: Optional reason for unmute.
            skip_validation: Skip validation if already done by caller.
        """
        # -----------------------------------------------------------------
        # Get Target Guild (for cross-server moderation)
        # -----------------------------------------------------------------

        target_guild = get_target_guild(interaction, self.bot)
        cross_server = is_cross_server(interaction)

        # Get member from target guild
        target_member = target_guild.get_member(user.id)
        if not target_member:
            if not skip_validation:
                guild_name = target_guild.name if cross_server else "this server"
                await interaction.followup.send(
                    f"User is not a member of {guild_name}.",
                    ephemeral=True,
                )
            return

        muted_role = target_guild.get_role(self.config.muted_role_id)
        if not muted_role:
            if not skip_validation:
                await interaction.followup.send(
                    f"Muted role not found (ID: {self.config.muted_role_id}).",
                    ephemeral=True,
                )
            return

        if not skip_validation:
            if muted_role not in target_member.roles:
                await interaction.followup.send(
                    f"**{target_member.display_name}** is not muted.",
                    ephemeral=True,
                )
                return

        # ---------------------------------------------------------------------
        # Get Mute Info (before removing)
        # ---------------------------------------------------------------------

        mute_info = self.db.get_active_mute(user.id, target_guild.id)
        muted_duration = None
        if mute_info and mute_info["muted_at"]:
            muted_seconds = int(time.time() - mute_info["muted_at"])
            muted_duration = format_duration(muted_seconds)

        # ---------------------------------------------------------------------
        # Remove Mute
        # ---------------------------------------------------------------------

        try:
            await target_member.remove_roles(muted_role, reason=f"Unmuted by {interaction.user}: {reason or 'No reason'}")

            self.db.remove_mute(
                user_id=user.id,
                guild_id=target_guild.id,
                moderator_id=interaction.user.id,
                reason=reason,
            )

            log_items = [
                ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                ("ID", str(user.id)),
                ("Moderator", str(interaction.user)),
                ("Was Muted For", muted_duration or "Unknown"),
                ("Reason", (reason or "None")[:50]),
            ]
            if cross_server:
                log_items.insert(1, ("Cross-Server", f"From {interaction.guild.name} → {target_guild.name}"))
            logger.tree("USER UNMUTED", log_items, emoji="🔊")

        except discord.Forbidden:
            logger.warning("Unmute Failed (Forbidden)", [
                ("User", f"{target_member.name} ({target_member.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Guild", target_guild.name),
            ])
            await interaction.followup.send("I don't have permission to unmute this user.", ephemeral=True)
            return
        except discord.HTTPException as e:
            logger.error("Unmute Failed (HTTP)", [
                ("User", f"{target_member.name} ({target_member.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error", str(e)[:100]),
            ])
            await interaction.followup.send(f"Failed to unmute user: {e}", ephemeral=True)
            return

        # ---------------------------------------------------------------------
        # Log to Case Forum (finds active mute case and resolves it)
        # ---------------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            try:
                case_info = await asyncio.wait_for(
                    self.bot.case_log_service.log_unmute(
                        user_id=user.id,
                        moderator=interaction.user,
                        display_name=target_member.display_name,
                        reason=reason,
                        user_avatar_url=target_member.display_avatar.url,
                    ),
                    timeout=CASE_LOG_TIMEOUT,
                )
                if case_info:
                    logger.tree("Case Resolved", [
                        ("Action", "Unmute"),
                        ("Case ID", case_info["case_id"]),
                        ("User", f"{target_member.name} ({target_member.id})"),
                    ], emoji="📋")
            except asyncio.TimeoutError:
                logger.warning("Case Log Timeout", [
                    ("Action", "Unmute"),
                    ("User", f"{target_member.name} ({target_member.nick})" if target_member.nick else target_member.name),
                    ("ID", str(target_member.id)),
                ])
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Log Timeout",
                        f"Unmute case logging timed out for {target_member} ({target_member.id})"
                    )
            except Exception as e:
                logger.error("Case Log Failed", [
                    ("Action", "Unmute"),
                    ("User", f"{target_member.name} ({target_member.nick})" if target_member.nick else target_member.name),
                    ("ID", str(target_member.id)),
                    ("Error", str(e)[:100]),
                ])
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Log Failed",
                        f"Unmute case logging failed for {target_member} ({target_member.id}): {str(e)[:200]}"
                    )

        # ---------------------------------------------------------------------
        # Build & Send Embed
        # ---------------------------------------------------------------------

        embed = discord.Embed(
            title="🔊 User Unmuted",
            color=EmbedColors.GREEN,
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Was Muted For", value=f"`{muted_duration or 'Unknown'}`", inline=True)

        if case_info:
            embed.add_field(name="Case", value=f"`#{case_info['case_id']}`", inline=True)

        # Note: Reason intentionally not shown in public embed
        # Only visible in DMs, case logs, and mod logs

        embed.set_thumbnail(url=target_member.display_avatar.url)
        set_footer(embed)

        try:
            if case_info:
                view = CaseButtonView(target_guild.id, case_info["thread_id"], user.id)
                await interaction.followup.send(embed=embed, view=view)
            else:
                await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error("Unmute Followup Failed", [
                ("User", f"{user.name} ({user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error", str(e)[:100]),
            ])

        # ---------------------------------------------------------------------
        # Concurrent Post-Response Operations
        # ---------------------------------------------------------------------

        await gather_with_logging(
            ("DM User", self._send_unmute_dm(
                target=target_member,
                guild=target_guild,
                moderator=interaction.user,
                reason=reason,
            )),
            ("Post Mod Logs", self._post_mod_log(
                action="Unmute",
                user=target_member,
                moderator=interaction.user,
                reason=reason,
                color=EmbedColors.SUCCESS,
            )),
            ("Mod Tracker", self._log_unmute_to_tracker(
                moderator=interaction.user,
                target=target_member,
                reason=reason,
                case_id=case_info["case_id"] if case_info else None,
            )),
            context="Unmute Command",
        )

    async def _unmute_from_message(
        self: "MuteCog",
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> None:
        """
        Unmute the author of a message (context menu handler).

        Args:
            interaction: Discord interaction context.
            message: The message whose author to unmute.
        """
        if message.author.bot:
            await interaction.response.send_message(
                "I cannot unmute bots.",
                ephemeral=True,
            )
            return

        # Get member from guild
        user = interaction.guild.get_member(message.author.id)
        if not user:
            await interaction.response.send_message(
                "User not found in this server.",
                ephemeral=True,
            )
            return

        # Check if user is muted
        muted_role = interaction.guild.get_role(self.config.muted_role_id)
        if not muted_role or muted_role not in user.roles:
            await interaction.response.send_message(
                f"**{user.display_name}** is not muted.",
                ephemeral=True,
            )
            return

        # Defer and execute unmute (validation already done)
        await interaction.response.defer(ephemeral=False)
        await self.execute_unmute(interaction, user, reason=None, skip_validation=True)


__all__ = ["UnmuteOpsMixin"]
