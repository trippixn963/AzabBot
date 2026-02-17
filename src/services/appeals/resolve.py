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
from src.utils.async_utils import create_safe_task

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
        logger.tree("Appeal Approval Started", [
            ("Appeal ID", appeal_id),
            ("Moderator", f"{moderator.name} ({moderator.id})"),
            ("Reason", reason or "No reason provided"),
        ], emoji="🔄")

        appeal = self.db.get_appeal(appeal_id)
        if not appeal:
            logger.warning("Appeal Approval Failed", [
                ("Appeal ID", appeal_id),
                ("Error", "Appeal not found in database"),
            ])
            return (False, "Appeal not found")

        if appeal["status"] != "pending":
            logger.warning("Appeal Approval Failed", [
                ("Appeal ID", appeal_id),
                ("Current Status", appeal["status"]),
                ("Error", "Appeal is no longer pending"),
            ])
            return (False, "Appeal is no longer pending")

        user_id = appeal["user_id"]
        case_id = appeal["case_id"]
        guild_id = appeal["guild_id"]

        logger.debug("Appeal Details", [
            ("User ID", str(user_id)),
            ("Case ID", case_id),
            ("Guild ID", str(guild_id)),
        ])

        # Atomically resolve the appeal first to prevent race conditions
        resolved = self.db.resolve_appeal(
            appeal_id=appeal_id,
            resolution="approved",
            resolved_by=moderator.id,
            resolution_reason=reason)
        if not resolved:
            logger.warning("Appeal Approval Failed", [
                ("Appeal ID", appeal_id),
                ("Error", "Race condition - already processed"),
            ])
            return (False, "Appeal was already processed by another moderator")

        logger.debug("Appeal DB Updated", [
            ("Appeal ID", appeal_id),
            ("New Status", "approved"),
        ])

        try:
            # Get the guild
            guild = self.bot.get_guild(guild_id)
            if not guild:
                logger.error("Appeal Approval Failed", [
                    ("Appeal ID", appeal_id),
                    ("Guild ID", str(guild_id)),
                    ("Error", "Guild not found - bot may not be in server"),
                ])
                return (False, "Guild not found")

            # Get the original case to determine action type
            case = self.db.get_case(case_id)
            action_type = case.get("action_type", "mute") if case else "mute"
            is_ban = action_type == "ban"

            logger.debug("Processing Appeal", [
                ("Type", action_type.upper()),
                ("Guild", guild.name),
            ])

            action_taken = "No action taken"
            action_success = False

            if is_ban:
                # Handle ban appeal - unban the user
                try:
                    await guild.unban(
                        discord.Object(id=user_id),
                        reason=f"Appeal {appeal_id} approved by {moderator}"
                    )
                    action_taken = "User has been unbanned"
                    action_success = True

                    # Log to ban_history
                    self.db.execute(
                        """INSERT INTO ban_history (user_id, guild_id, moderator_id, action, reason, timestamp)
                           VALUES (?, ?, ?, 'unban', ?, ?)""",
                        (user_id, guild_id, moderator.id, f"Appeal {appeal_id} approved", datetime.now(NY_TZ).timestamp())
                    )

                    logger.tree("User Unbanned", [
                        ("User ID", str(user_id)),
                        ("Appeal ID", appeal_id),
                        ("Guild", guild.name),
                        ("Moderator", moderator.name),
                    ], emoji="🔓")

                except discord.NotFound:
                    action_taken = "User was not banned (already unbanned)"
                    action_success = True  # Not an error, just already done
                    logger.warning("Unban Skipped", [
                        ("User ID", str(user_id)),
                        ("Reason", "User not in ban list"),
                    ])
                except discord.Forbidden as e:
                    action_taken = "Failed to unban - missing permissions"
                    logger.error("Unban Failed (Forbidden)", [
                        ("User ID", str(user_id)),
                        ("Appeal ID", appeal_id),
                        ("Error", str(e)[:100]),
                    ])
                except discord.HTTPException as e:
                    log_http_error(e, "Appeal Unban", [
                        ("User ID", str(user_id)),
                        ("Appeal ID", appeal_id),
                    ])
                    action_taken = f"Failed to unban user: {e.status}"

                # DM the user with approval notification
                dm_sent = await self._send_appeal_approved_dm(
                    user_id=user_id,
                    guild=guild,
                    moderator=moderator,
                    reason=reason,
                    is_ban=True)
            else:
                # Handle mute appeal - unmute the user
                member = guild.get_member(user_id)
                mute_removed = False
                timeout_removed = False

                if member:
                    muted_role = guild.get_role(self.config.muted_role_id)
                    if muted_role and muted_role in member.roles:
                        try:
                            await member.remove_roles(
                                muted_role,
                                reason=f"Appeal {appeal_id} approved by {moderator}"
                            )
                            mute_removed = True
                        except discord.HTTPException as e:
                            log_http_error(e, "Appeal Unmute", [
                                ("User ID", str(user_id)),
                                ("Appeal ID", appeal_id),
                            ])

                    # Remove timeout if any
                    if member.is_timed_out():
                        try:
                            await member.timeout(None, reason=f"Appeal {appeal_id} approved")
                            timeout_removed = True
                        except discord.HTTPException:
                            pass

                    action_success = True
                    logger.tree("User Unmuted", [
                        ("User ID", str(user_id)),
                        ("Appeal ID", appeal_id),
                        ("Mute Role Removed", "Yes" if mute_removed else "No"),
                        ("Timeout Removed", "Yes" if timeout_removed else "N/A"),
                    ], emoji="🔊")
                else:
                    logger.warning("Unmute Skipped", [
                        ("User ID", str(user_id)),
                        ("Reason", "Member not in server"),
                    ])

                # Clear mute from database
                self.db.remove_mute(user_id, guild.id, moderator.id, "Appeal approved")
                action_taken = "User has been unmuted"

                # DM the user
                dm_sent = await self._send_appeal_approved_dm(
                    user_id=user_id,
                    guild=guild,
                    moderator=moderator,
                    reason=reason,
                    is_ban=False)

            # Resolve the original case
            if case:
                self.db.resolve_case(
                    case_id=case_id,
                    resolved_by=moderator.id,
                    reason=f"Appeal approved: {reason}" if reason else "Appeal approved")
                logger.debug("Case Resolved", [
                    ("Case ID", case_id),
                ])

            # Update thread
            thread_updated = False
            thread = await self._get_appeal_thread(appeal["thread_id"])
            if thread:
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

                try:
                    await thread.edit(archived=True, locked=True)
                    thread_updated = True
                except discord.HTTPException:
                    pass

            # Log to server logs
            await self._log_appeal_resolved(
                appeal_id=appeal_id,
                case_id=case_id,
                user_id=user_id,
                moderator=moderator,
                resolution="approved",
                reason=reason)

            # Send email notification if user provided email
            email_sent = False
            appeal_email = appeal.get("email")
            if appeal_email:
                email_sent = await send_appeal_email(
                    to_email=appeal_email,
                    appeal_id=appeal_id,
                    resolution="approved",
                    resolution_reason=reason,
                    server_name=guild.name,
                    server_invite_url=self.config.server_invite_url)

            # Broadcast WebSocket event for real-time dashboard updates
            if hasattr(self.bot, 'api_service') and self.bot.api_service:
                async def broadcast_appeal_resolved_event():
                    await self.bot.api_service.broadcast_appeal_resolved({
                        'appeal_id': appeal_id,
                        'case_id': case_id,
                        'user_id': user_id,
                        'action_type': action_type,
                        'resolved_by': moderator.id,
                        'resolution_reason': reason,
                    }, approved=True)
                create_safe_task(broadcast_appeal_resolved_event(), "Appeal Approved WebSocket Broadcast")

            # Final summary log
            logger.tree("APPEAL APPROVED", [
                ("Appeal ID", appeal_id),
                ("Case ID", case_id),
                ("User ID", str(user_id)),
                ("Type", action_type.upper()),
                ("Action", action_taken),
                ("Action Success", "Yes" if action_success else "No"),
                ("Thread Updated", "Yes" if thread_updated else "No"),
                ("Email Sent", "Yes" if email_sent else "No" if appeal_email else "N/A"),
                ("Moderator", f"{moderator.name} ({moderator.id})"),
            ], emoji="✅")

            result_msg = "Appeal approved. User has been unbanned." if is_ban else "Appeal approved. User has been unmuted."
            return (True, result_msg)

        except Exception as e:
            logger.error("Appeal Approval Failed", [
                ("Appeal ID", appeal_id),
                ("User ID", str(user_id)),
                ("Error Type", type(e).__name__),
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
        logger.tree("Appeal Denial Started", [
            ("Appeal ID", appeal_id),
            ("Moderator", f"{moderator.name} ({moderator.id})"),
            ("Reason", reason or "No reason provided"),
        ], emoji="🔄")

        appeal = self.db.get_appeal(appeal_id)
        if not appeal:
            logger.warning("Appeal Denial Failed", [
                ("Appeal ID", appeal_id),
                ("Error", "Appeal not found in database"),
            ])
            return (False, "Appeal not found")

        if appeal["status"] != "pending":
            logger.warning("Appeal Denial Failed", [
                ("Appeal ID", appeal_id),
                ("Current Status", appeal["status"]),
                ("Error", "Appeal is no longer pending"),
            ])
            return (False, "Appeal is no longer pending")

        user_id = appeal["user_id"]
        case_id = appeal["case_id"]
        guild_id = appeal["guild_id"]

        logger.debug("Appeal Details", [
            ("User ID", str(user_id)),
            ("Case ID", case_id),
            ("Guild ID", str(guild_id)),
        ])

        # Atomically resolve the appeal first to prevent race conditions
        resolved = self.db.resolve_appeal(
            appeal_id=appeal_id,
            resolution="denied",
            resolved_by=moderator.id,
            resolution_reason=reason)
        if not resolved:
            logger.warning("Appeal Denial Failed", [
                ("Appeal ID", appeal_id),
                ("Error", "Race condition - already processed"),
            ])
            return (False, "Appeal was already processed by another moderator")

        logger.debug("Appeal DB Updated", [
            ("Appeal ID", appeal_id),
            ("New Status", "denied"),
        ])

        try:
            # Get the original case to determine action type
            case = self.db.get_case(case_id)
            action_type = case.get("action_type", "mute") if case else "mute"
            is_ban = action_type == "ban"

            # DM the user about the denial
            guild = self.bot.get_guild(guild_id)
            dm_sent = False
            if guild:
                dm_sent = await self._send_appeal_denied_dm(
                    user_id=user_id,
                    guild=guild,
                    moderator=moderator,
                    reason=reason,
                    is_ban=is_ban)
            else:
                logger.warning("Guild Not Found", [
                    ("Guild ID", str(guild_id)),
                    ("Impact", "Cannot send DM without guild context"),
                ])

            # Update thread
            thread_updated = False
            thread = await self._get_appeal_thread(appeal["thread_id"])
            if thread:
                embed = discord.Embed(
                    title="❌ Appeal Denied",
                    description=f"This appeal has been **denied** by {moderator.mention}.",
                    color=EmbedColors.ERROR
                )
                if reason:
                    embed.add_field(name="Reason", value=f"```{reason}```", inline=False)

                cooldown_hours = APPEAL_COOLDOWN_SECONDS // 3600
                embed.add_field(
                    name="⏰ Re-appeal Cooldown",
                    value=f"You may submit a new appeal in **{cooldown_hours} hours**.",
                    inline=False)

                if self.config.ticket_channel_id:
                    denied_view = AppealDeniedView(self.config.ticket_channel_id, guild_id)
                    await safe_send(thread, embed=embed, view=denied_view)
                else:
                    await safe_send(thread, embed=embed)

                try:
                    await thread.edit(archived=True, locked=True)
                    thread_updated = True
                except discord.HTTPException:
                    pass

            # Log to server logs
            await self._log_appeal_resolved(
                appeal_id=appeal_id,
                case_id=case_id,
                user_id=user_id,
                moderator=moderator,
                resolution="denied",
                reason=reason)

            # Send email notification if user provided email
            email_sent = False
            appeal_email = appeal.get("email")
            if appeal_email and guild:
                email_sent = await send_appeal_email(
                    to_email=appeal_email,
                    appeal_id=appeal_id,
                    resolution="denied",
                    resolution_reason=reason,
                    server_name=guild.name)

            # Broadcast WebSocket event for real-time dashboard updates
            if hasattr(self.bot, 'api_service') and self.bot.api_service:
                async def broadcast_appeal_denied_event():
                    await self.bot.api_service.broadcast_appeal_resolved({
                        'appeal_id': appeal_id,
                        'case_id': case_id,
                        'user_id': user_id,
                        'action_type': action_type,
                        'resolved_by': moderator.id,
                        'resolution_reason': reason,
                    }, approved=False)
                create_safe_task(broadcast_appeal_denied_event(), "Appeal Denied WebSocket Broadcast")

            # Final summary log
            logger.tree("APPEAL DENIED", [
                ("Appeal ID", appeal_id),
                ("Case ID", case_id),
                ("User ID", str(user_id)),
                ("Type", action_type.upper()),
                ("Punishment Remains", "Yes"),
                ("DM Sent", "Yes" if dm_sent else "No"),
                ("Thread Updated", "Yes" if thread_updated else "No"),
                ("Email Sent", "Yes" if email_sent else "No" if appeal_email else "N/A"),
                ("Moderator", f"{moderator.name} ({moderator.id})"),
            ], emoji="❌")

            return (True, "Appeal denied.")

        except Exception as e:
            logger.error("Appeal Denial Failed", [
                ("Appeal ID", appeal_id),
                ("User ID", str(user_id)),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:100]),
            ])
            return (False, f"Failed to deny appeal: {str(e)[:50]}")

    async def _send_appeal_approved_dm(
        self: "AppealService",
        user_id: int,
        guild: discord.Guild,
        moderator: discord.Member,
        reason: Optional[str],
        is_ban: bool) -> bool:
        """Send DM to user when their appeal is approved."""
        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            logger.warning("Appeal DM Failed", [
                ("User ID", str(user_id)),
                ("Reason", "User not found"),
            ])
            return False
        except discord.HTTPException:
            return False

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

        return sent

    async def _send_appeal_denied_dm(
        self: "AppealService",
        user_id: int,
        guild: discord.Guild,
        moderator: discord.Member,
        reason: Optional[str],
        is_ban: bool) -> bool:
        """Send DM to user when their appeal is denied."""
        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            logger.warning("Appeal DM Failed", [
                ("User ID", str(user_id)),
                ("Reason", "User not found"),
            ])
            return False
        except discord.HTTPException:
            return False

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

        return sent


__all__ = ["ResolveMixin"]
