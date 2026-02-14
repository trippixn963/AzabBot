"""
AzabBot - Appeal Resolution Mixin
=================================

Methods for approving and denying appeals.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.utils.retry import safe_send
from src.utils.dm_helpers import safe_send_dm, build_moderation_dm
from src.utils.discord_rate_limit import log_http_error

from .constants import APPEAL_COOLDOWN_SECONDS
from .views import AppealApprovedView, AppealDeniedView
from .email import send_appeal_email

if TYPE_CHECKING:
    from .service import AppealService


class ResolveMixin:
    """Mixin for appeal resolution methods."""

    async def approve_appeal(
        self: "AppealService",
        appeal_id: str,
        moderator: discord.Member,
        reason: Optional[str] = None) -> tuple[bool, str]:
        """
        Approve an appeal (ban or mute) and reverse the punishment.

        Args:
            appeal_id: Appeal ID to approve.
            moderator: Moderator approving.
            reason: Optional approval reason.

        Returns:
            Tuple of (success, message).
        """
        appeal = self.db.get_appeal(appeal_id)
        if not appeal:
            return (False, "Appeal not found")

        if appeal["status"] != "pending":
            return (False, "Appeal is no longer pending")

        # Atomically resolve the appeal first to prevent race conditions
        # This only succeeds if status is still 'pending'
        resolved = self.db.resolve_appeal(
            appeal_id=appeal_id,
            resolution="approved",
            resolved_by=moderator.id,
            resolution_reason=reason)
        if not resolved:
            return (False, "Appeal was already processed by another moderator")

        try:
            # Get the guild
            guild = self.bot.get_guild(appeal["guild_id"])
            if not guild:
                return (False, "Guild not found")

            user_id = appeal["user_id"]
            case_id = appeal["case_id"]

            # Get the original case to determine action type
            case = self.db.get_case(case_id)
            action_type = case.get("action_type", "mute") if case else "mute"
            is_ban = action_type == "ban"

            if is_ban:
                # Handle ban appeal - unban the user
                try:
                    await guild.unban(
                        discord.Object(id=user_id),
                        reason=f"Appeal {appeal_id} approved by {moderator}"
                    )
                    action_taken = "User has been unbanned"
                except discord.NotFound:
                    action_taken = "User was not banned (already unbanned?)"
                except discord.HTTPException as e:
                    log_http_error(e, "Appeal Unban", [
                        ("User ID", str(user_id)),
                        ("Appeal ID", appeal_id),
                    ])
                    action_taken = "Failed to unban user"

                # DM the user with approval notification
                await self._send_appeal_approved_dm(
                    user_id=user_id,
                    guild=guild,
                    moderator=moderator,
                    reason=reason,
                    is_ban=True)
            else:
                # Handle mute appeal - unmute the user
                member = guild.get_member(user_id)
                if member:
                    muted_role = guild.get_role(self.config.muted_role_id)
                    if muted_role and muted_role in member.roles:
                        try:
                            await member.remove_roles(
                                muted_role,
                                reason=f"Appeal {appeal_id} approved by {moderator}"
                            )
                        except discord.HTTPException as e:
                            log_http_error(e, "Appeal Unmute", [
                                ("User ID", str(user_id)),
                                ("Appeal ID", appeal_id),
                            ])

                    # Remove timeout if any
                    if member.is_timed_out():
                        try:
                            await member.timeout(None, reason=f"Appeal {appeal_id} approved")
                        except discord.HTTPException:
                            pass

                # Clear mute from database
                self.db.remove_mute(user_id, guild.id, moderator.id, "Appeal approved")
                action_taken = "User has been unmuted"

            # Resolve the original case
            if case:
                self.db.resolve_case(
                    case_id=case_id,
                    resolved_by=moderator.id,
                    reason=f"Appeal approved: {reason}" if reason else "Appeal approved")

            # Update thread
            thread = await self._get_appeal_thread(appeal["thread_id"])
            if thread:
                # Send resolution message
                embed = discord.Embed(
                    title="✅ Appeal Approved",
                    description=f"This appeal has been **approved** by {moderator.mention}.",
                    color=EmbedColors.SUCCESS
                )
                if reason:
                    embed.add_field(name="Reason", value=f"```{reason}```", inline=False)

                embed.add_field(name="Action Taken", value=action_taken, inline=False)

                approved_view = AppealApprovedView(user_id, guild.id)
                await safe_send(thread, embed=embed, view=approved_view)

                # Archive thread
                try:
                    await thread.edit(archived=True, locked=True)
                except discord.HTTPException:
                    pass

            # Log
            logger.tree("APPEAL APPROVED", [
                ("Appeal ID", appeal_id),
                ("Case ID", case_id),
                ("Type", action_type.upper()),
                ("Moderator", f"{moderator.name} ({moderator.nick})" if hasattr(moderator, 'nick') and moderator.nick else moderator.name),
                ("Mod ID", str(moderator.id)),
            ], emoji="✅")

            # Log to server logs
            await self._log_appeal_resolved(
                appeal_id=appeal_id,
                case_id=case_id,
                user_id=user_id,
                moderator=moderator,
                resolution="approved",
                reason=reason)

            # Send email notification if user provided email
            appeal_email = appeal.get("email")
            if appeal_email:
                await send_appeal_email(
                    to_email=appeal_email,
                    appeal_id=appeal_id,
                    resolution="approved",
                    resolution_reason=reason,
                    server_name=guild.name,
                    server_invite_url=self.config.server_invite_url)

            result_msg = "Appeal approved. User has been unbanned." if is_ban else "Appeal approved. User has been unmuted."
            return (True, result_msg)

        except Exception as e:
            logger.error("Appeal Approval Failed", [
                ("Appeal ID", appeal_id),
                ("Error", str(e)[:100]),
            ])
            return (False, f"Failed to approve appeal: {str(e)[:50]}")

    async def deny_appeal(
        self: "AppealService",
        appeal_id: str,
        moderator: discord.Member,
        reason: Optional[str] = None) -> tuple[bool, str]:
        """
        Deny an appeal.

        Args:
            appeal_id: Appeal ID to deny.
            moderator: Moderator denying.
            reason: Optional denial reason.

        Returns:
            Tuple of (success, message).
        """
        appeal = self.db.get_appeal(appeal_id)
        if not appeal:
            return (False, "Appeal not found")

        if appeal["status"] != "pending":
            return (False, "Appeal is no longer pending")

        # Atomically resolve the appeal first to prevent race conditions
        # This only succeeds if status is still 'pending'
        resolved = self.db.resolve_appeal(
            appeal_id=appeal_id,
            resolution="denied",
            resolved_by=moderator.id,
            resolution_reason=reason)
        if not resolved:
            return (False, "Appeal was already processed by another moderator")

        try:
            user_id = appeal["user_id"]
            case_id = appeal["case_id"]
            guild_id = appeal["guild_id"]

            # Get the original case to determine action type
            case = self.db.get_case(case_id)
            action_type = case.get("action_type", "mute") if case else "mute"
            is_ban = action_type == "ban"

            # DM the user about the denial (especially important for bans)
            guild = self.bot.get_guild(guild_id)
            if guild:
                await self._send_appeal_denied_dm(
                    user_id=user_id,
                    guild=guild,
                    moderator=moderator,
                    reason=reason,
                    is_ban=is_ban)

            # Update thread
            thread = await self._get_appeal_thread(appeal["thread_id"])
            if thread:
                embed = discord.Embed(
                    title="❌ Appeal Denied",
                    description=f"This appeal has been **denied** by {moderator.mention}.",
                    color=EmbedColors.ERROR
                )
                if reason:
                    embed.add_field(name="Reason", value=f"```{reason}```", inline=False)

                # Add cooldown warning
                cooldown_hours = APPEAL_COOLDOWN_SECONDS // 3600
                embed.add_field(
                    name="⏰ Re-appeal Cooldown",
                    value=f"You may submit a new appeal in **{cooldown_hours} hours**.",
                    inline=False)

                # Add contact staff button if ticket channel is configured
                if self.config.ticket_channel_id:
                    denied_view = AppealDeniedView(self.config.ticket_channel_id, guild_id)
                    await safe_send(thread, embed=embed, view=denied_view)
                else:
                    await safe_send(thread, embed=embed)

                # Archive thread
                try:
                    await thread.edit(archived=True, locked=True)
                except discord.HTTPException:
                    pass

            # Log
            logger.tree("APPEAL DENIED", [
                ("Appeal ID", appeal_id),
                ("Case ID", case_id),
                ("Type", action_type.upper()),
                ("Moderator", f"{moderator.name} ({moderator.nick})" if hasattr(moderator, 'nick') and moderator.nick else moderator.name),
                ("Mod ID", str(moderator.id)),
            ], emoji="❌")

            # Log to server logs
            await self._log_appeal_resolved(
                appeal_id=appeal_id,
                case_id=case_id,
                user_id=user_id,
                moderator=moderator,
                resolution="denied",
                reason=reason)

            # Send email notification if user provided email
            appeal_email = appeal.get("email")
            if appeal_email and guild:
                await send_appeal_email(
                    to_email=appeal_email,
                    appeal_id=appeal_id,
                    resolution="denied",
                    resolution_reason=reason,
                    server_name=guild.name)

            return (True, "Appeal denied.")

        except Exception as e:
            logger.error("Appeal Denial Failed", [
                ("Appeal ID", appeal_id),
                ("Error", str(e)[:100]),
            ])
            return (False, f"Failed to deny appeal: {str(e)[:50]}")

    async def _send_appeal_approved_dm(
        self: "AppealService",
        user_id: int,
        guild: discord.Guild,
        moderator: discord.Member,
        reason: Optional[str],
        is_ban: bool) -> None:
        """Send DM to user when their appeal is approved."""
        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            logger.warning("Appeal DM Failed", [
                ("User ID", str(user_id)),
                ("Reason", "User not found"),
            ])
            return
        except discord.HTTPException:
            return

        # Build the embed
        embed = discord.Embed(
            title="✅ Your Appeal Has Been Approved",
            color=EmbedColors.SUCCESS
        )

        if is_ban:
            description = f"Your ban appeal for **{guild.name}** has been approved."
            if self.config.server_invite_url:
                description += f"\n\nYou may rejoin the server using this link:\n{self.config.server_invite_url}"
            embed.description = description
        else:
            embed.description = f"Your mute appeal for **{guild.name}** has been approved. You have been unmuted."

        if reason:
            embed.add_field(name="Reason", value=f"```{reason}```", inline=False)

        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

        # Send the DM
        sent = await safe_send_dm(user, embed=embed, context="Appeal Approved DM")

        logger.tree("Appeal Approved DM", [
            ("User", user.name),
            ("ID", str(user_id)),
            ("Type", "Ban" if is_ban else "Mute"),
            ("Delivered", "Yes" if sent else "No (DMs disabled)"),
        ], emoji="📨")

    async def _send_appeal_denied_dm(
        self: "AppealService",
        user_id: int,
        guild: discord.Guild,
        moderator: discord.Member,
        reason: Optional[str],
        is_ban: bool) -> None:
        """Send DM to user when their appeal is denied."""
        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            logger.warning("Appeal DM Failed", [
                ("User ID", str(user_id)),
                ("Reason", "User not found"),
            ])
            return
        except discord.HTTPException:
            return

        # Build the embed
        embed = discord.Embed(
            title="❌ Your Appeal Has Been Denied",
            color=EmbedColors.ERROR
        )

        action_type = "ban" if is_ban else "mute"
        embed.description = f"Your {action_type} appeal for **{guild.name}** has been denied."

        if reason:
            embed.add_field(name="Reason", value=f"```{reason}```", inline=False)

        # Add cooldown info
        cooldown_hours = APPEAL_COOLDOWN_SECONDS // 3600
        embed.add_field(
            name="⏰ Re-appeal",
            value=f"You may submit a new appeal in **{cooldown_hours} hours**.",
            inline=False)

        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

        # Send the DM
        sent = await safe_send_dm(user, embed=embed, context="Appeal Denied DM")

        logger.tree("Appeal Denied DM", [
            ("User", user.name),
            ("ID", str(user_id)),
            ("Type", "Ban" if is_ban else "Mute"),
            ("Delivered", "Yes" if sent else "No (DMs disabled)"),
        ], emoji="📨")


__all__ = ["ResolveMixin"]
