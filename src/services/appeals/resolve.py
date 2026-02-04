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
from src.utils.footer import set_footer
from src.utils.retry import safe_send

from .constants import APPEAL_COOLDOWN_SECONDS
from .views import AppealApprovedView, AppealDeniedView

if TYPE_CHECKING:
    from .service import AppealService


class ResolveMixin:
    """Mixin for appeal resolution methods."""

    async def approve_appeal(
        self: "AppealService",
        appeal_id: str,
        moderator: discord.Member,
        reason: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Approve an appeal and take action.

        For bans: Unban the user.
        For mutes: Unmute the user.

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
            resolution_reason=reason,
        )
        if not resolved:
            return (False, "Appeal was already processed by another moderator")

        try:
            # Get the guild
            guild = self.bot.get_guild(appeal["guild_id"])
            if not guild:
                return (False, "Guild not found")

            user_id = appeal["user_id"]
            action_type = appeal["action_type"]
            case_id = appeal["case_id"]

            # Fetch user ONCE (reused throughout)
            appeal_user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)

            # Take action based on type
            if action_type == "ban":
                # Unban user
                try:
                    await guild.unban(appeal_user, reason=f"Appeal {appeal_id} approved by {moderator}")
                except discord.NotFound:
                    pass  # User not banned or doesn't exist
                except discord.HTTPException as e:
                    logger.warning("Appeal Unban Failed", [
                        ("User ID", str(user_id)),
                        ("Appeal ID", appeal_id),
                        ("Error", str(e)[:50]),
                    ])

            elif action_type == "mute":
                # Remove muted role
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
                            logger.warning("Appeal Unmute Failed", [
                                ("User ID", str(user_id)),
                                ("Appeal ID", appeal_id),
                                ("Error", str(e)[:50]),
                            ])

                    # Remove timeout if any
                    if member.is_timed_out():
                        try:
                            await member.timeout(None, reason=f"Appeal {appeal_id} approved")
                        except discord.HTTPException:
                            pass

                # Clear mute from database
                self.db.remove_mute(user_id, guild.id, moderator.id, "Appeal approved")

            # Resolve the original case
            case = self.db.get_case(case_id)
            if case:
                self.db.resolve_case(
                    case_id=case_id,
                    resolved_by=moderator.id,
                    reason=f"Appeal approved: {reason}" if reason else "Appeal approved",
                )

            # Update thread
            thread = await self._get_appeal_thread(appeal["thread_id"])
            if thread:
                # Send resolution message
                embed = discord.Embed(
                    title="✅ Appeal Approved",
                    description=f"This appeal has been **approved** by {moderator.mention}.",
                    color=EmbedColors.SUCCESS,
                    timestamp=datetime.now(NY_TZ),
                )
                if reason:
                    embed.add_field(name="Reason", value=f"```{reason}```", inline=False)

                action_taken = "User has been unbanned" if action_type == "ban" else "User has been unmuted"
                embed.add_field(name="Action Taken", value=action_taken, inline=False)

                set_footer(embed)
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
                ("Moderator", f"{moderator.name} ({moderator.nick})" if hasattr(moderator, 'nick') and moderator.nick else moderator.name),
                ("Mod ID", str(moderator.id)),
                ("Action", action_type.title()),
            ], emoji="✅")

            # Log to server logs
            await self._log_appeal_resolved(
                appeal_id=appeal_id,
                case_id=case_id,
                user_id=user_id,
                moderator=moderator,
                resolution="approved",
                reason=reason,
            )

            return (True, f"Appeal approved. User has been {'unbanned' if action_type == 'ban' else 'unmuted'}.")

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
        reason: Optional[str] = None,
    ) -> tuple[bool, str]:
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
            resolution_reason=reason,
        )
        if not resolved:
            return (False, "Appeal was already processed by another moderator")

        try:
            user_id = appeal["user_id"]
            case_id = appeal["case_id"]

            # Update thread
            thread = await self._get_appeal_thread(appeal["thread_id"])
            if thread:
                embed = discord.Embed(
                    title="❌ Appeal Denied",
                    description=f"This appeal has been **denied** by {moderator.mention}.",
                    color=EmbedColors.ERROR,
                    timestamp=datetime.now(NY_TZ),
                )
                if reason:
                    embed.add_field(name="Reason", value=f"```{reason}```", inline=False)

                # Add cooldown warning
                cooldown_hours = APPEAL_COOLDOWN_SECONDS // 3600
                embed.add_field(
                    name="⏰ Re-appeal Cooldown",
                    value=f"You may submit a new appeal in **{cooldown_hours} hours**.",
                    inline=False,
                )

                set_footer(embed)

                # Add contact staff button if ticket channel is configured
                guild_id = appeal["guild_id"]
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
                reason=reason,
            )

            return (True, "Appeal denied.")

        except Exception as e:
            logger.error("Appeal Denial Failed", [
                ("Appeal ID", appeal_id),
                ("Error", str(e)[:100]),
            ])
            return (False, f"Failed to deny appeal: {str(e)[:50]}")


__all__ = ["ResolveMixin"]
