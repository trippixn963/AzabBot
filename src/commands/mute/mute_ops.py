"""
AzabBot - Mute Operations Mixin
===============================

Core mute execution logic.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors
from src.core.moderation_validation import (
    validate_moderation_target,
    get_target_guild,
    is_cross_server,
    send_management_blocked_embed,
)
from src.utils.footer import set_footer
from src.views import CaseButtonView
from src.utils.async_utils import gather_with_logging
from src.utils.duration import parse_duration, format_duration
from src.utils.discord_rate_limit import log_http_error
from src.core.constants import CASE_LOG_TIMEOUT
from src.services.user_snapshots import save_member_snapshot

from .views import MuteModal

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

        # Get member from target guild (required for role-based mute)
        target_member = target_guild.get_member(user.id)
        if not target_member:
            guild_name = target_guild.name if cross_server else "this server"
            await interaction.followup.send(
                f"User is not a member of {guild_name}.",
                ephemeral=True,
            )
            return

        # ---------------------------------------------------------------------
        # Validation (using centralized validation module)
        # ---------------------------------------------------------------------

        result = await validate_moderation_target(
            interaction=interaction,
            target=user,
            bot=self.bot,
            action="mute",
            require_member=True,
            check_bot_hierarchy=False,  # We check muted role instead
        )

        if not result.is_valid:
            if result.should_log_attempt:
                await send_management_blocked_embed(interaction, "mute")
            else:
                await interaction.followup.send(result.error_message, ephemeral=True)
            return

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

        # ---------------------------------------------------------------------
        # Save User Snapshot (for dashboard lookups if they leave)
        # ---------------------------------------------------------------------

        save_member_snapshot(target_member, reason="mute")

        # ---------------------------------------------------------------------
        # Apply Mute
        # ---------------------------------------------------------------------

        is_extension = muted_role in target_member.roles
        duration_seconds = parse_duration(duration) if duration else None
        duration_display = format_duration(duration_seconds)

        # Check for concurrent mute operations (race condition)
        # If a DIFFERENT mod just muted this user within the last few seconds,
        # treat this as a duplicate operation, not an intentional extension
        if is_extension:
            import time
            existing_mute = self.db.get_active_mute(user.id, target_guild.id)
            if existing_mute and existing_mute["muted_at"]:
                mute_age = time.time() - existing_mute["muted_at"]
                original_mod_id = existing_mute["moderator_id"]

                # Only block if DIFFERENT moderator muted recently
                # Same mod re-running = intentional adjustment, let it through
                if mute_age < CONCURRENT_MUTE_THRESHOLD and original_mod_id != interaction.user.id:
                    # Try to get the original moderator's name
                    original_mod = target_guild.get_member(original_mod_id)
                    mod_display = original_mod.mention if original_mod else f"another moderator (ID: {original_mod_id})"

                    logger.debug("Concurrent Mute Blocked", [
                        ("User", f"{user.name} ({user.id})"),
                        ("Blocked Mod", f"{interaction.user.name} ({interaction.user.id})"),
                        ("Original Mod", f"{original_mod_id}"),
                        ("Mute Age", f"{mute_age:.1f}s"),
                    ])

                    await interaction.followup.send(
                        f"**{target_member.display_name}** was just muted by {mod_display} "
                        f"(`{mute_age:.0f}s` ago).\n"
                        f"If you intended to extend the mute, please wait a moment and try again.",
                        ephemeral=True,
                    )
                    return

        try:
            if not is_extension:
                await target_member.add_roles(muted_role, reason=f"Muted by {interaction.user}: {reason or 'No reason'}")

            expires_at = self.db.add_mute(
                user_id=user.id,
                guild_id=target_guild.id,
                moderator_id=interaction.user.id,
                reason=reason,
                duration_seconds=duration_seconds,
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
                details={"is_extension": is_extension, "cross_server": cross_server},
            )

            action = "EXTENDED" if is_extension else "MUTED"
            log_items = [
                ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                ("ID", str(user.id)),
                ("Moderator", str(interaction.user)),
                ("Duration", duration_display),
                ("Reason", (reason or "None")[:50]),
            ]
            if cross_server:
                log_items.insert(1, ("Cross-Server", f"From {interaction.guild.name} → {target_guild.name}"))
            logger.tree(f"USER {action}", log_items, emoji="🔇")

        except discord.Forbidden:
            logger.warning("Mute Failed (Forbidden)", [
                ("User", f"{target_member.name} ({target_member.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Guild", target_guild.name),
            ])
            await interaction.followup.send("I don't have permission to mute this user.", ephemeral=True)
            return
        except discord.HTTPException as e:
            log_http_error(e, "Mute", [
                ("User", f"{target_member.name} ({target_member.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ])
            await interaction.followup.send(f"Failed to mute user: {e}", ephemeral=True)
            return

        # ---------------------------------------------------------------------
        # Log to Case Forum (creates per-action case)
        # ---------------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            try:
                case_info = await asyncio.wait_for(
                    self.bot.case_log_service.log_mute(
                        user=target_member,
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
                        ("User", f"{target_member.name} ({target_member.id})"),
                    ], emoji="📋")
            except asyncio.TimeoutError:
                logger.warning("Case Log Timeout", [
                    ("Action", "Mute"),
                    ("User", f"{target_member.name} ({target_member.nick})" if target_member.nick else target_member.name),
                    ("ID", str(target_member.id)),
                ])
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Log Timeout",
                        f"Mute case logging timed out for {target_member} ({target_member.id})"
                    )
            except Exception as e:
                logger.error("Case Log Failed", [
                    ("Action", "Mute"),
                    ("User", f"{target_member.name} ({target_member.nick})" if target_member.nick else target_member.name),
                    ("ID", str(target_member.id)),
                    ("Error", str(e)[:100]),
                ])
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Log Failed",
                        f"Mute case logging failed for {target_member} ({target_member.id}): {str(e)[:200]}"
                    )

        # ---------------------------------------------------------------------
        # Build & Send Embed
        # ---------------------------------------------------------------------

        embed_title = "🔇 Mute Extended" if is_extension else "🔇 User Muted"
        embed = discord.Embed(
            title=embed_title,
            color=EmbedColors.GOLD,
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Duration", value=f"`{duration_display}`", inline=True)

        if case_info:
            embed.add_field(name="Case", value=f"`#{case_info['case_id']}`", inline=True)

        # Note: Reason/Evidence intentionally not shown in public embed
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
            logger.error("Mute Followup Failed", [
                ("User", f"{user.name} ({user.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
                ("Error", str(e)[:100]),
            ])

        # ---------------------------------------------------------------------
        # Concurrent Post-Response Operations
        # ---------------------------------------------------------------------

        await gather_with_logging(
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
            )),
            ("Post Mod Logs", self._post_mod_log(
                action="Mute Extended" if is_extension else "Mute",
                user=target_member,
                moderator=interaction.user,
                reason=reason,
                duration=duration_display,
                color=EmbedColors.ERROR,
            )),
            ("Mod Tracker", self._log_mute_to_tracker(
                moderator=interaction.user,
                target=target_member,
                duration=duration_display,
                reason=reason,
                case_id=case_info["case_id"] if case_info else None,
            )),
            context="Mute Command",
        )

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
