"""
AzabBot - Unmute Operations Mixin
=================================

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
from src.api.services.event_logger import event_logger
from src.utils.validation import get_target_guild, is_cross_server, resolve_member
from src.views import CaseButtonView
from src.utils.async_utils import gather_with_logging, create_safe_task
from src.utils.duration import format_duration
from src.utils.discord_rate_limit import log_http_error
from src.core.constants import CASE_LOG_TIMEOUT
from src.utils.action_gifs import fetch_action_gif, await_gif_task

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

        # Get member from target guild (None if user left server)
        target_member = await resolve_member(target_guild, user.id)
        user_left_server = target_member is None
        display_target = target_member or user

        muted_role = target_guild.get_role(self.config.muted_role_id)
        if not muted_role:
            if not skip_validation:
                await interaction.followup.send(
                    f"Muted role not found (ID: {self.config.muted_role_id}).",
                    ephemeral=True,
                )
            return

        # If user is in server, check they actually have the muted role
        if not skip_validation and target_member:
            if muted_role not in target_member.roles:
                # Also check DB — they might have a pending mute
                if not self.db.get_active_mute(user.id, target_guild.id):
                    await interaction.followup.send(
                        f"**{target_member.display_name}** is not muted.",
                        ephemeral=True,
                    )
                    return

        # If user left server, check DB for active mute
        if user_left_server:
            if not self.db.get_active_mute(user.id, target_guild.id):
                await interaction.followup.send(
                    f"**{user.display_name}** has no active mute.",
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
            if target_member:
                await target_member.remove_roles(muted_role, reason=f"Unmuted by {interaction.user}: {reason or 'No reason'}")

            self.db.remove_mute(
                user_id=user.id,
                guild_id=target_guild.id,
                moderator_id=interaction.user.id,
                reason=reason,
            )

            # Log to permanent audit log
            self.db.log_moderation_action(
                user_id=user.id,
                guild_id=target_guild.id,
                moderator_id=interaction.user.id,
                action_type="unmute",
                action_source="manual",
                reason=reason,
                details={"muted_duration": muted_duration, "cross_server": cross_server, "user_left": user_left_server},
            )

            log_items = [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Moderator", str(interaction.user)),
                ("Reason", (reason or "None")[:50]),
            ]
            if muted_duration:
                log_items.insert(3, ("Was Muted For", muted_duration))
            if user_left_server:
                log_items.insert(1, ("Status", "User not in server — DB mute cleared"))
            if cross_server:
                log_items.insert(1, ("Cross-Server", f"From {interaction.guild.name} → {target_guild.name}"))
            logger.tree("USER UNMUTED", log_items, emoji="🔊")

            # Destroy anime clone
            if hasattr(self.bot, 'anime_clone') and self.bot.anime_clone:
                create_safe_task(
                    self.bot.anime_clone.destroy_clone(user.id, target_guild),
                    f"AnimeClone-Destroy-{user.id}",
                )

            # Log to dashboard events
            if target_member:
                event_logger.log_timeout_remove(
                    guild=target_guild,
                    target=target_member,
                    moderator=interaction.user,
                )

        except discord.Forbidden:
            logger.warning("Unmute Failed (Forbidden)", [
                ("User", f"{user.name} ({user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Guild", target_guild.name),
            ])
            await interaction.followup.send("I don't have permission to unmute this user.", ephemeral=True)
            return
        except discord.HTTPException as e:
            log_http_error(e, "Unmute", [
                ("User", f"{user.name} ({user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ])
            await interaction.followup.send(f"Failed to unmute user: {e}", ephemeral=True)
            return

        # Start gif fetch concurrently (runs in parallel with case logging)
        gif_task = create_safe_task(fetch_action_gif("unmute"), "unmute_gif_fetch")

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
                        display_name=display_target.display_name,
                        reason=reason,
                        user_avatar_url=display_target.display_avatar.url,
                    ),
                    timeout=CASE_LOG_TIMEOUT,
                )
                if case_info:
                    logger.tree("Case Resolved", [
                        ("Action", "Unmute"),
                        ("Case ID", case_info["case_id"]),
                        ("User", f"{user.name} ({user.id})"),
                    ], emoji="📋")
            except asyncio.TimeoutError:
                logger.warning("Case Log Timeout", [
                    ("Action", "Unmute"),
                    ("User", f"{user.name} ({user.id})"),
                ])
            except Exception as e:
                logger.error("Case Log Failed", [
                    ("Action", "Unmute"),
                    ("User", f"{user.name} ({user.id})"),
                    ("Error", str(e)[:100]),
                ])

        # ---------------------------------------------------------------------
        # Build & Send Embed
        # ---------------------------------------------------------------------

        gif_url = await await_gif_task(gif_task)

        title = "🔊 User Unmuted (Not In Server)" if user_left_server else "🔊 User Unmuted"
        embed = discord.Embed(
            title=title,
            description=f"{display_target.mention} unmuted by {interaction.user.mention}",
            color=EmbedColors.GREEN,
        )

        if user_left_server:
            embed.set_footer(text="Pending mute cleared — user won't be re-muted on rejoin")

        embed.set_thumbnail(url=display_target.display_avatar.url)
        if gif_url:
            embed.set_image(url=gif_url)

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

        post_tasks = [
            ("Post Mod Logs", self._post_mod_log(
                action="Unmute (Not In Server)" if user_left_server else "Unmute",
                user=display_target,
                moderator=interaction.user,
                reason=reason,
                color=EmbedColors.SUCCESS,
            )),
        ]

        if target_member:
            post_tasks.extend([
                ("DM User", self._send_unmute_dm(
                    target=target_member,
                    guild=target_guild,
                    moderator=interaction.user,
                    reason=reason,
                )),
                ("Mod Tracker", self._log_unmute_to_tracker(
                    moderator=interaction.user,
                    target=target_member,
                    reason=reason,
                    case_id=case_info["case_id"] if case_info else None,
                )),
                ("Release Announcement", self._send_release_announcement(
                    member=target_member,
                    moderator=interaction.user,
                )),
            ])

        await gather_with_logging(*post_tasks, context="Unmute Command")

    async def _send_release_announcement(
        self: "MuteCog",
        member: discord.Member,
        moderator: discord.Member,
    ) -> None:
        """Send release announcement to general chat for manual unmute."""
        try:
            # Import here to avoid circular import (prison handler imports services)
            from src.handlers.prison import send_release_announcement, ReleaseType

            await send_release_announcement(
                bot=self.bot,
                member=member,
                release_type=ReleaseType.MANUAL_UNMUTE,
                moderator=moderator,
            )
            # Note: send_release_announcement handles its own logging
        except Exception as e:
            logger.warning("Release Announcement Failed", [
                ("User", f"{member.name} ({member.id})"),
                ("Error", str(e)[:50]),
            ])

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

        # Use message.author as User — execute_unmute handles absent members
        user = message.author

        # Defer and execute unmute (execute_unmute handles all validation)
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=False)
        except discord.HTTPException:
            pass
        await self.execute_unmute(interaction, user, reason=None)


__all__ = ["UnmuteOpsMixin"]
