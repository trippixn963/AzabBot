"""
AzabBot - Mute Operations Mixin
===============================

Core mute execution logic.

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
from src.utils.validation import (
    validate_moderation_target,
    get_target_guild,
    is_cross_server,
    send_management_blocked_embed,
    resolve_member,
)
from src.views import CaseButtonView
from src.utils.async_utils import gather_with_logging, create_safe_task
from src.utils.duration import parse_duration, format_duration
from src.utils.discord_rate_limit import log_http_error
from src.core.constants import CASE_LOG_TIMEOUT
from src.services.user_snapshots import save_member_snapshot

from .views import MuteModal
from src.services.xp_drain import process_mute_xp_drain, get_drain_amount, is_drain_exempt
from src.utils.action_gifs import fetch_action_gif, await_gif_task

# Threshold for detecting concurrent mute operations (seconds)
# If an existing mute was created within this window, treat as duplicate, not extension
CONCURRENT_MUTE_THRESHOLD: float = 5.0

if TYPE_CHECKING:
    from .cog import MuteCog


class MuteOpsMixin:
    """Mixin for mute operation methods."""

    async def execute_mute(
        self: "MuteCog",
        interaction: discord.Interaction,
        user: discord.User,
        duration: Optional[str] = None,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
        buyout_allowed: bool = True,
    ) -> None:
        """
        Execute mute logic (shared by /mute command and context menu).

        Supports cross-server moderation: when run from mod server,
        the mute is executed on the main server.

        Args:
            interaction: Discord interaction (must be deferred).
            user: User to mute.
            duration: Optional duration string.
            reason: Optional reason for mute.
            evidence: Optional evidence link/description.
        """
        # -----------------------------------------------------------------
        # Get Target Guild (for cross-server moderation)
        # -----------------------------------------------------------------

        target_guild = get_target_guild(interaction, self.bot)
        cross_server = is_cross_server(interaction)

        # Muted role specific checks
        muted_role = target_guild.get_role(self.config.muted_role_id)
        if not muted_role:
            logger.tree("MUTE BLOCKED", [
                ("Reason", "Muted role not found"),
                ("Role ID", str(self.config.muted_role_id)),
            ], emoji="🚫")
            await interaction.followup.send(
                f"Muted role not found (ID: {self.config.muted_role_id}).",
                ephemeral=True,
            )
            return

        if muted_role >= target_guild.me.top_role:
            logger.tree("MUTE BLOCKED", [
                ("Reason", "Bot role too low"),
                ("Muted Role", muted_role.name),
                ("Bot Top Role", target_guild.me.top_role.name),
            ], emoji="🚫")
            await interaction.followup.send(
                "I cannot assign the muted role because it's higher than my highest role.",
                ephemeral=True,
            )
            return

        # Get member from target guild (None if user left server)
        target_member = await resolve_member(target_guild, user.id)
        user_left_server = target_member is None

        # Block muting bot accounts
        if user.bot:
            await interaction.followup.send("Cannot mute bot accounts.", ephemeral=True)
            return

        # If user left, check if they already have an active mute (extend instead of duplicate)
        if user_left_server:
            existing_mute = self.db.get_active_mute(user.id, target_guild.id)
            if existing_mute:
                # Update the existing mute instead of creating a duplicate
                duration_seconds = parse_duration(duration) if duration else None
                duration_display = format_duration(duration_seconds)
                expires_at = self.db.add_mute(
                    user_id=user.id,
                    guild_id=target_guild.id,
                    moderator_id=interaction.user.id,
                    reason=reason,
                    duration_seconds=duration_seconds,
                    buyout_allowed=buyout_allowed,
                )
                embed = discord.Embed(
                    title="🔇 Mute Extended (Pending)",
                    description=f"{user.mention} mute extended by {interaction.user.mention}",
                    color=EmbedColors.GOLD,
                )
                embed.set_footer(text="User is not in server — mute will apply when they rejoin")
                embed.set_thumbnail(url=user.display_avatar.url)
                await interaction.followup.send(embed=embed)
                logger.tree("USER MUTE EXTENDED (pending rejoin)", [
                    ("User", f"{user.name} ({user.display_name})"),
                    ("ID", str(user.id)),
                    ("Moderator", str(interaction.user)),
                    ("Duration", duration_display),
                ], emoji="🔇")
                return

        # If user is in server, validate target
        if target_member:
            result = await validate_moderation_target(
                interaction=interaction,
                target=user,
                bot=self.bot,
                action="mute",
                require_member=True,
                check_bot_hierarchy=False,
            )

            if not result.is_valid:
                if result.should_log_attempt:
                    await send_management_blocked_embed(interaction, "mute")
                else:
                    await interaction.followup.send(result.error_message, ephemeral=True)
                return

            # Save User Snapshot (for dashboard lookups if they leave)
            save_member_snapshot(target_member, reason="mute")

        # ---------------------------------------------------------------------
        # Apply Mute
        # ---------------------------------------------------------------------

        is_extension = target_member and muted_role in target_member.roles
        duration_seconds = parse_duration(duration) if duration else None
        duration_display = format_duration(duration_seconds)

        # Check for concurrent mute operations (race condition)
        if is_extension:
            existing_mute = self.db.get_active_mute(user.id, target_guild.id)

            if existing_mute:
                buyout_allowed = bool(existing_mute.get("buyout_allowed", 1))

            if existing_mute and existing_mute["muted_at"]:
                mute_age = time.time() - existing_mute["muted_at"]
                original_mod_id = existing_mute["moderator_id"]

                if mute_age < CONCURRENT_MUTE_THRESHOLD and original_mod_id != interaction.user.id:
                    original_mod = target_guild.get_member(original_mod_id)
                    mod_display = original_mod.mention if original_mod else f"another moderator (ID: {original_mod_id})"

                    logger.debug("Concurrent Mute Blocked", [
                        ("User", f"{user.name} ({user.id})"),
                        ("Blocked Mod", f"{interaction.user.name} ({interaction.user.id})"),
                        ("Original Mod", f"{original_mod_id}"),
                        ("Mute Age", f"{mute_age:.1f}s"),
                    ])

                    await interaction.followup.send(
                        f"**{user.display_name}** was just muted by {mod_display} "
                        f"(`{mute_age:.0f}s` ago).\n"
                        f"If you intended to extend the mute, please wait a moment and try again.",
                        ephemeral=True,
                    )
                    return

        try:
            if target_member and not is_extension:
                await target_member.add_roles(muted_role, reason=f"Muted by {interaction.user}: {reason or 'No reason'}")

            expires_at = self.db.add_mute(
                user_id=user.id,
                guild_id=target_guild.id,
                moderator_id=interaction.user.id,
                reason=reason,
                duration_seconds=duration_seconds,
                buyout_allowed=buyout_allowed,
            )

            # Log to permanent audit log
            self.db.log_moderation_action(
                user_id=user.id,
                guild_id=target_guild.id,
                moderator_id=interaction.user.id,
                action_type="mute",
                action_source="manual",
                reason=reason,
                duration_seconds=duration_seconds,
                details={"is_extension": is_extension, "cross_server": cross_server, "buyout_allowed": buyout_allowed},
            )

            action = "EXTENDED" if is_extension else ("MUTED (pending rejoin)" if user_left_server else "MUTED")
            log_items = [
                ("User", f"{user.name} ({user.display_name})"),
                ("ID", str(user.id)),
                ("Moderator", str(interaction.user)),
                ("Duration", duration_display),
                ("Reason", (reason or "None")[:50]),
            ]
            if user_left_server:
                log_items.insert(1, ("Status", "Left server — mute will apply on rejoin"))
            if cross_server:
                log_items.insert(1, ("Cross-Server", f"From {interaction.guild.name} → {target_guild.name}"))
            logger.tree(f"USER {action}", log_items, emoji="🔇")

            # Spawn anime clone in general chat (non-blocking, only for new mutes, only if in server)
            if not is_extension and not user_left_server and hasattr(self.bot, 'anime_clone') and self.bot.anime_clone:
                create_safe_task(
                    self.bot.anime_clone.create_clone(user, target_guild),
                    f"AnimeClone-Create-{user.id}",
                )

            # Log to dashboard events
            if target_member:
                event_logger.log_timeout(
                    guild=target_guild,
                    target=target_member,
                    moderator=interaction.user,
                    reason=reason,
                    duration_seconds=duration_seconds,
                )

        except discord.Forbidden:
            logger.warning("Mute Failed (Forbidden)", [
                ("User", f"{user.name} ({user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Guild", target_guild.name),
            ])
            await interaction.followup.send("I don't have permission to mute this user.", ephemeral=True)
            return
        except discord.HTTPException as e:
            log_http_error(e, "Mute", [
                ("User", f"{user.name} ({user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ])
            await interaction.followup.send(f"Failed to mute user: {e}", ephemeral=True)
            return

        # Start gif fetch concurrently (runs in parallel with case logging)
        gif_task = create_safe_task(fetch_action_gif("mute"), "mute_gif_fetch")
        display_target = target_member or user

        # ---------------------------------------------------------------------
        # Log to Case Forum (creates per-action case)
        # ---------------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            try:
                case_info = await asyncio.wait_for(
                    self.bot.case_log_service.log_mute(
                        user=display_target,
                        moderator=interaction.user,
                        duration=duration_display,
                        reason=reason,
                        is_extension=is_extension,
                        evidence=evidence,
                    ),
                    timeout=CASE_LOG_TIMEOUT,
                )
                if case_info:
                    logger.tree("Case Created", [
                        ("Action", "Mute"),
                        ("Case ID", case_info["case_id"]),
                        ("User", f"{user.name} ({user.id})"),
                    ], emoji="📋")
            except asyncio.TimeoutError:
                logger.warning("Case Log Timeout", [
                    ("Action", "Mute"),
                    ("User", f"{user.name} ({user.id})"),
                ])
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Log Timeout",
                        f"Mute case logging timed out for {user} ({user.id})"
                    )
            except Exception as e:
                logger.error("Case Log Failed", [
                    ("Action", "Mute"),
                    ("User", f"{user.name} ({user.id})"),
                    ("Error", str(e)[:100]),
                ])
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Log Failed",
                        f"Mute case logging failed for {user} ({user.id}): {str(e)[:200]}"
                    )

        # ---------------------------------------------------------------------
        # Calculate XP Drain & Offense Counts (for display in embed)
        # ---------------------------------------------------------------------

        # Get total mute count (all-time) for mod visibility
        total_mutes = self.db.get_user_mute_count(user.id, target_guild.id)

        xp_lost: Optional[int] = None
        offense_count_week = 0
        if not is_extension and target_member and not is_drain_exempt(target_member):
            offense_count_week = self.db.get_user_mute_count_week(user.id, target_guild.id)
            xp_lost = get_drain_amount(offense_count_week)

        # ---------------------------------------------------------------------
        # Build & Send Embed
        # ---------------------------------------------------------------------

        gif_url = await await_gif_task(gif_task)

        display_target = target_member or user
        if is_extension:
            action_text = "mute extended"
            title = "🔇 Mute Extended"
        elif user_left_server:
            action_text = "muted (pending rejoin)"
            title = "🔇 User Muted (Pending)"
        else:
            action_text = "muted"
            title = "🔇 User Muted"

        embed = discord.Embed(
            title=title,
            description=f"{display_target.mention} {action_text} by {interaction.user.mention}",
            color=EmbedColors.GOLD,
        )

        if user_left_server:
            embed.set_footer(text="User is not in server — mute will apply when they rejoin")

        embed.set_thumbnail(url=display_target.display_avatar.url)
        if gif_url:
            embed.set_image(url=gif_url)

        try:
            if case_info:
                view = CaseButtonView(target_guild.id, case_info["thread_id"], user.id)
                await interaction.followup.send(embed=embed, view=view)
            else:
                await interaction.followup.send(embed=embed)
        except discord.NotFound:
            # Interaction token expired or webhook deleted - expected for slow operations
            logger.warning("Mute Followup Expired", [
                ("User", f"{user.name} ({user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ])
        except Exception as e:
            logger.warning("Mute Followup Failed", [
                ("User", f"{user.name} ({user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error", str(e)[:100]),
            ])

        # ---------------------------------------------------------------------
        # Concurrent Post-Response Operations
        # ---------------------------------------------------------------------

        # Build post-response tasks — skip user-dependent ones if they left
        post_tasks = [
            ("Post Mod Logs", self._post_mod_log(
                action="Mute Extended" if is_extension else ("Mute (Pending)" if user_left_server else "Mute"),
                user=display_target,
                moderator=interaction.user,
                reason=reason,
                duration=duration_display,
                color=EmbedColors.ERROR,
            )),
            ("WebSocket Broadcast", self._broadcast_case_event(
                case_info=case_info,
                user_id=user.id,
                moderator_id=interaction.user.id,
                action_type="mute",
                reason=reason,
                duration=duration_display,
                is_extension=is_extension,
            )),
        ]

        if target_member:
            post_tasks.extend([
                ("DM User", self._send_mute_dm(
                    target=target_member,
                    guild=target_guild,
                    moderator=interaction.user,
                    duration_display=duration_display,
                    expires_at=expires_at,
                    reason=reason,
                    evidence=evidence,
                    case_info=case_info,
                    is_extension=is_extension,
                    xp_lost=xp_lost,
                    offense_count=offense_count_week,
                    buyout_allowed=buyout_allowed,
                )),
                ("Mod Tracker", self._log_mute_to_tracker(
                    moderator=interaction.user,
                    target=target_member,
                    duration=duration_display,
                    reason=reason,
                    case_id=case_info["case_id"] if case_info else None,
                )),
                ("XP Drain", process_mute_xp_drain(
                    member=target_member,
                    guild_id=target_guild.id,
                    offense_count=offense_count_week,
                    is_extension=is_extension,
                )),
            ])

        await gather_with_logging(*post_tasks, context="Mute Command")

    async def _mute_from_message(
        self: "MuteCog",
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> None:
        """
        Mute the author of a message (context menu handler).

        DESIGN:
            Opens a modal for duration/reason input.
            Evidence is auto-filled from message attachment if image/video.

        Args:
            interaction: Discord interaction context.
            message: The message whose author to mute.
        """
        # Can't mute bots
        if message.author.bot:
            await interaction.response.send_message(
                "I cannot mute bots.",
                ephemeral=True,
            )
            return

        # Get evidence from message attachment if it's an image/video
        evidence = None
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith(('image/', 'video/')):
                evidence = attachment.url
                break

        # Show modal for duration and reason
        modal = MuteModal(
            bot=self.bot,
            target_user=message.author,
            evidence=evidence,
            cog=self,
        )
        await interaction.response.send_modal(modal)




__all__ = ["MuteOpsMixin"]
