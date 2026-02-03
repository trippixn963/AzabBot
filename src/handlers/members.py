"""
AzabBot - Member Events
=======================

Handles member join, leave, and update events.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config
from src.core.database import get_db
from src.core.constants import CASE_LOG_TIMEOUT, QUERY_LIMIT_TINY
from src.utils.async_utils import create_safe_task

# Verification role delay - another bot handles this, but we act as failsafe backup
VERIFICATION_DELAY = 5  # seconds to wait before checking

if TYPE_CHECKING:
    from src.bot import AzabBot


class MemberEvents(commands.Cog):
    """Member event handlers."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """
        Handle member role changes for mute detection and mod tracking.

        DESIGN: Watches for muted role being added/removed to trigger
        prison handler events. Also tracks mod avatar/name/role changes.
        """
        if self.bot.disabled:
            return

        # -----------------------------------------------------------------
        # Mute Role Detection (using set for O(1) lookup)
        # -----------------------------------------------------------------
        before_role_ids = {r.id for r in before.roles}
        after_role_ids = {r.id for r in after.roles}

        had_muted = self.config.muted_role_id in before_role_ids
        has_muted = self.config.muted_role_id in after_role_ids

        if not had_muted and has_muted:
            logger.tree("NEW PRISONER DETECTED", [
                ("User", str(after)),
                ("User ID", str(after.id)),
            ], emoji="⛓️")

            if self.bot.prison:
                await self.bot.prison.handle_new_prisoner(after)

        elif had_muted and not has_muted:
            logger.tree("PRISONER RELEASED", [
                ("User", str(after)),
                ("User ID", str(after.id)),
            ], emoji="🔓")

            if self.bot.prison:
                await self.bot.prison.handle_prisoner_release(after)

            # Clean up rate limiting state (with lock for thread safety)
            async with self.bot._prisoner_lock:
                self.bot.prisoner_cooldowns.pop(after.id, None)
                self.bot.prisoner_message_buffer.pop(after.id, None)
                self.bot.prisoner_pending_response.pop(after.id, None)

        # -----------------------------------------------------------------
        # Mod Tracker: Auto-track on role add/remove
        # -----------------------------------------------------------------
        if self.bot.mod_tracker and self.bot.mod_tracker.enabled and self.config.moderation_role_id:
            had_mod_role = self.config.moderation_role_id in before_role_ids
            has_mod_role = self.config.moderation_role_id in after_role_ids

            if not had_mod_role and has_mod_role:
                if not self.bot.mod_tracker.is_tracked(after.id):
                    await self.bot.mod_tracker.add_tracked_mod(after)

            elif had_mod_role and not has_mod_role:
                # Mod lost role - delete thread and remove from tracking
                if self.bot.mod_tracker.is_tracked(after.id):
                    await self.bot.mod_tracker.handle_mod_role_removed(after)

        # -----------------------------------------------------------------
        # Mod Tracker: Avatar, Name, Role Changes
        # -----------------------------------------------------------------
        if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(after.id):
            if before.avatar != after.avatar:
                await self.bot.mod_tracker.log_avatar_change(
                    after,
                    before.display_avatar if before.avatar else None,
                    after.display_avatar if after.avatar else None,
                )

            if before.name != after.name:
                await self.bot.mod_tracker.log_name_change(
                    after, "Username", before.name, after.name
                )

            if before.display_name != after.display_name:
                await self.bot.mod_tracker.log_name_change(
                    after, "Display Name", before.display_name, after.display_name
                )

            added_roles = [r for r in after.roles if r not in before.roles]
            removed_roles = [r for r in before.roles if r not in after.roles]
            if added_roles or removed_roles:
                # Try to find who made the change from audit log
                changed_by_id = None
                changed_by_member = None
                try:
                    async for entry in after.guild.audit_logs(
                        action=discord.AuditLogAction.member_role_update,
                        limit=QUERY_LIMIT_TINY,
                    ):
                        if entry.target and entry.target.id == after.id:
                            changed_by_id = entry.user.id if entry.user else None
                            if entry.user:
                                changed_by_member = after.guild.get_member(entry.user.id)
                            break
                except discord.Forbidden:
                    logger.debug(f"Audit log access denied for role change lookup in {after.guild.name}")
                except discord.HTTPException as e:
                    logger.warning("Audit Log Fetch Failed", [
                        ("Action", "member_role_update"),
                        ("Guild", after.guild.name),
                        ("Error", str(e)[:50]),
                    ])

                await self.bot.mod_tracker.log_role_change(
                    after, added_roles, removed_roles, changed_by_id=changed_by_id
                )

                # Log to logging service with moderator context
                if self.bot.logging_service and self.bot.logging_service.enabled:
                    for role in added_roles:
                        await self.bot.logging_service.log_role_add(after, role, moderator=changed_by_member)
                    for role in removed_roles:
                        await self.bot.logging_service.log_role_remove(after, role, moderator=changed_by_member)

        # -----------------------------------------------------------------
        # Logging Service: Role Changes (fallback for when mod_tracker is disabled)
        # -----------------------------------------------------------------
        if not (self.bot.mod_tracker and self.bot.mod_tracker.enabled):
            # Only log roles here if mod_tracker didn't already (to avoid duplicates)
            if self.bot.logging_service and self.bot.logging_service.enabled:
                added_roles = [r for r in after.roles if r not in before.roles]
                removed_roles = [r for r in before.roles if r not in after.roles]
                for role in added_roles:
                    await self.bot.logging_service.log_role_add(after, role)
                for role in removed_roles:
                    await self.bot.logging_service.log_role_remove(after, role)

        # -----------------------------------------------------------------
        # Logging Service: Other Member Updates (always run)
        # -----------------------------------------------------------------
        if self.bot.logging_service and self.bot.logging_service.enabled:
            if before.nick != after.nick:
                await self.bot.logging_service.log_nickname_change(after, before.nick, after.nick)
                self.bot.db.save_nickname_change(
                    user_id=after.id,
                    guild_id=after.guild.id,
                    old_nickname=before.nick,
                    new_nickname=after.nick,
                    changed_by=None,
                )

                # Save old nickname to username history (if it existed)
                if before.nick:
                    db = get_db()
                    db.save_username_change(
                        user_id=after.id,
                        display_name=before.nick,
                        guild_id=after.guild.id,
                    )

            if before.premium_since is None and after.premium_since is not None:
                await self.bot.logging_service.log_boost(after)
                logger.tree("Server Boosted", [
                    ("User", f"{after.name} ({after.id})"),
                    ("Guild", after.guild.name),
                    ("Boost Count", str(after.guild.premium_subscription_count)),
                ], emoji="💎")
            elif before.premium_since is not None and after.premium_since is None:
                await self.bot.logging_service.log_unboost(after, boosted_since=before.premium_since)
                # Calculate duration for tree logging
                duration_days = (datetime.now(before.premium_since.tzinfo) - before.premium_since).days if before.premium_since.tzinfo else (datetime.utcnow() - before.premium_since).days
                logger.tree("Boost Removed", [
                    ("User", f"{after.name} ({after.id})"),
                    ("Guild", after.guild.name),
                    ("Boosted For", f"{duration_days} days"),
                    ("Boost Count", str(after.guild.premium_subscription_count)),
                ], emoji="💔")

            if before.pending and not after.pending:
                await self.bot.logging_service.log_member_verification(after)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Log member joins with invite tracking, raid detection, and mute evasion."""
        invite_code = None
        inviter = None

        if self.bot.logging_service and self.bot.logging_service.enabled:
            invite_info = await self.bot._find_used_invite(member.guild)
            invite_code = invite_info[0] if invite_info else None
            inviter = invite_info[1] if invite_info else None
            await self.bot.logging_service.log_member_join(member, invite_code, inviter)

        # Tree logging for all joins
        account_age = "Unknown"
        if member.created_at:
            age_days = (discord.utils.utcnow() - member.created_at).days
            account_age = f"{age_days} days"

        logger.tree("MEMBER JOINED", [
            ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
            ("ID", str(member.id)),
            ("Account Age", account_age),
            ("Invite", invite_code or "Unknown"),
            ("Inviter", str(inviter) if inviter else "Unknown"),
        ], emoji="📥")

        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot._check_raid_detection(member)

        # Store join info for alt detection
        db = get_db()
        db.save_user_join_info(
            user_id=member.id,
            guild_id=member.guild.id,
            invite_code=invite_code,
            inviter_id=inviter.id if inviter else None,
            joined_at=member.joined_at.timestamp() if member.joined_at else None,
            avatar_hash=member.avatar.key if member.avatar else None,
        )

        await self._check_mute_evasion(member)

        # Check for potential ban evasion (username similarity with banned users)
        if self.bot.mod_tracker:
            await self.bot.mod_tracker.check_ban_evasion_on_join(member)

        # Failsafe: Check verification role after delay (backup for other bot)
        create_safe_task(self._check_verification_role(member), name="verification_check")

    async def _check_mute_evasion(self, member: discord.Member) -> None:
        """Check if rejoining member has an active mute and re-apply it."""
        db = get_db()

        active_mute = db.get_active_mute(member.id, member.guild.id)
        if not active_mute:
            return

        muted_role = member.guild.get_role(self.config.muted_role_id)
        if not muted_role:
            return

        try:
            await member.add_roles(muted_role, reason="Mute evasion: User rejoined with active mute")

            logger.tree("MUTE EVASION DETECTED", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
            ("ID", str(member.id)),
                ("Action", "Re-applied muted role"),
            ], emoji="⚠️")

            if self.bot.case_log_service:
                mod_id = active_mute["moderator_id"]
                try:
                    await asyncio.wait_for(
                        self.bot.case_log_service.log_mute_evasion_return(member, [mod_id]),
                        timeout=CASE_LOG_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Case Log Timeout", [
                        ("Action", "Mute Evasion Return"),
                        ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
            ("ID", str(member.id)),
                    ])
                except Exception as e:
                    logger.error("Case Log Failed", [
                        ("Action", "Mute Evasion Return"),
                        ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
            ("ID", str(member.id)),
                        ("Error", str(e)[:100]),
                    ])

        except Exception as e:
            logger.error("Mute Evasion Re-apply Failed", [
                ("User", str(member)),
                ("Error", str(e)[:50]),
            ])

    async def _check_verification_role(self, member: discord.Member) -> None:
        """
        Failsafe backup for verification role assignment.

        Another bot is primary for assigning this role, but sometimes misses.
        We wait a few seconds then check if the member has the role.
        """
        # Check if verification role is configured
        if not self.config.verification_role_id:
            return

        await asyncio.sleep(VERIFICATION_DELAY)

        # Re-fetch member in case they left or state changed
        try:
            member = await member.guild.fetch_member(member.id)
        except discord.NotFound:
            return  # Member left
        except discord.HTTPException:
            return

        # Check if they already have the role
        if any(r.id == self.config.verification_role_id for r in member.roles):
            return  # Already has it, other bot worked

        # Get the verification role
        role = member.guild.get_role(self.config.verification_role_id)
        if not role:
            return  # Role doesn't exist in this guild

        # Assign the role as backup
        try:
            await member.add_roles(role, reason="Verification role failsafe (backup)")
            logger.tree("VERIFICATION ROLE BACKUP", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
            ("ID", str(member.id)),
                ("Action", "Assigned verification role (other bot missed)"),
            ], emoji="✅")
        except discord.Forbidden:
            logger.debug(f"Cannot assign verification role to {member} - missing permissions")
        except discord.HTTPException as e:
            logger.debug(f"Failed to assign verification role to {member}: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Log member leaves, track muted users leaving, delete linked messages."""
        # Clean up prisoner buffers (with lock for thread safety)
        async with self.bot._prisoner_lock:
            self.bot.prisoner_cooldowns.pop(member.id, None)
            self.bot.prisoner_message_buffer.pop(member.id, None)
            self.bot.prisoner_pending_response.pop(member.id, None)

        # Delete linked messages (alliance channel posts)
        await self._delete_linked_messages(member)

        # Calculate membership duration
        membership_duration = "Unknown"
        if member.joined_at:
            duration_days = (discord.utils.utcnow() - member.joined_at).days
            if duration_days == 0:
                membership_duration = "< 1 day"
            elif duration_days == 1:
                membership_duration = "1 day"
            else:
                membership_duration = f"{duration_days} days"

        # Get role count (excluding @everyone)
        role_count = len([r for r in member.roles if r.name != "@everyone"])

        # Check if this was a ban (check recent audit log)
        was_banned = False
        try:
            async for entry in member.guild.audit_logs(action=discord.AuditLogAction.ban, limit=QUERY_LIMIT_TINY):
                if entry.target and entry.target.id == member.id:
                    # Ban happened within last 5 seconds = this removal was a ban
                    if (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                        was_banned = True
                    break
        except discord.Forbidden:
            logger.debug(f"Audit log access denied for ban check in {member.guild.name}")
        except discord.HTTPException as e:
            logger.warning("Audit Log Fetch Failed", [
                ("Action", "ban_check"),
                ("Guild", member.guild.name),
                ("Error", str(e)[:50]),
            ])

        leave_type = "BANNED" if was_banned else "MEMBER LEFT"
        logger.tree(leave_type, [
            ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
            ("ID", str(member.id)),
            ("Membership", membership_duration),
            ("Roles", str(role_count)),
        ], emoji="🔨" if was_banned else "📤")

        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_member_leave(member, was_banned=was_banned)

        await self._check_muted_member_left(member)

    async def _check_muted_member_left(self, member: discord.Member) -> None:
        """Check if leaving member has an active mute and log it."""
        db = get_db()

        active_mute = db.get_active_mute(member.id, member.guild.id)
        if not active_mute:
            return

        logger.tree("MUTED USER LEFT", [
            ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
            ("ID", str(member.id)),
            ("Status", "Left with active mute"),
        ], emoji="🚪")

        if self.bot.case_log_service:
            try:
                await asyncio.wait_for(
                    self.bot.case_log_service.log_member_left_muted(
                        user_id=member.id,
                        display_name=member.display_name,
                        muted_at=active_mute["muted_at"],
                        avatar_url=member.display_avatar.url,
                    ),
                    timeout=CASE_LOG_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("Case Log Timeout", [
                    ("Action", "Member Left Muted"),
                    ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
            ("ID", str(member.id)),
                ])
            except Exception as e:
                logger.error("Case Log Failed", [
                    ("Action", "Member Left Muted"),
                    ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
            ("ID", str(member.id)),
                    ("Error", str(e)[:100]),
                ])

    async def _delete_linked_messages(self, member: discord.Member) -> None:
        """Delete all messages linked to a leaving member."""
        from datetime import datetime
        from src.core.config import EmbedColors, NY_TZ
        from src.utils.footer import set_footer

        db = get_db()

        linked_messages = db.get_linked_messages_by_member(member.id, member.guild.id)
        if not linked_messages:
            return

        deleted_count = 0
        failed_count = 0
        deleted_message_ids = []

        for record in linked_messages:
            channel = self.bot.get_channel(record["channel_id"])
            if not channel:
                failed_count += 1
                continue

            try:
                message = await channel.fetch_message(record["message_id"])
                await message.delete(reason=f"Linked member left: {member} ({member.id})")
                deleted_count += 1
                deleted_message_ids.append(str(record["message_id"]))
            except discord.NotFound:
                # Message already deleted
                pass
            except discord.HTTPException:
                failed_count += 1

        # Clean up database records
        db.delete_linked_messages_by_member(member.id, member.guild.id)

        if deleted_count > 0 or failed_count > 0:
            logger.tree("LINKED MESSAGES DELETED", [
                ("Member", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("Deleted", str(deleted_count)),
                ("Failed", str(failed_count)),
            ], emoji="🗑️")

            # Log to server logs
            await self._log_linked_messages_deleted(
                member=member,
                deleted_count=deleted_count,
                failed_count=failed_count,
                message_ids=deleted_message_ids,
            )

    async def _log_linked_messages_deleted(
        self,
        member: discord.Member,
        deleted_count: int,
        failed_count: int,
        message_ids: list,
    ) -> None:
        """Log linked message deletion to server logs."""
        from datetime import datetime
        from src.core.config import EmbedColors, NY_TZ
        from src.utils.footer import set_footer

        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="🗑️ Linked Messages Deleted",
                description=f"Messages linked to {member.mention} were deleted because they left the server.",
                color=EmbedColors.RED,
                timestamp=datetime.now(NY_TZ),
            )

            embed.add_field(
                name="Member",
                value=f"{member}\n`{member.id}`",
                inline=True,
            )
            embed.add_field(
                name="Messages Deleted",
                value=f"`{deleted_count}`",
                inline=True,
            )
            if failed_count > 0:
                embed.add_field(
                    name="Failed",
                    value=f"`{failed_count}`",
                    inline=True,
                )

            if message_ids:
                ids_text = "\n".join(message_ids[:10])  # Show first 10
                if len(message_ids) > 10:
                    ids_text += f"\n... and {len(message_ids) - 10} more"
                embed.add_field(
                    name="Message IDs",
                    value=f"```{ids_text}```",
                    inline=False,
                )

            set_footer(embed)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.ALLIANCES,
                embed,
            )

        except Exception as e:
            logger.debug(f"Failed to log linked message deletion: {e}")

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User) -> None:
        """Log user avatar and username changes."""
        # Track username changes to history (always, even if logging disabled)
        if before.name != after.name:
            db = get_db()
            db.save_username_change(
                user_id=after.id,
                username=before.name,  # Save the OLD username
            )

        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        if before.avatar != after.avatar:
            before_url = before.display_avatar.url if before.avatar else None
            after_url = after.display_avatar.url if after.avatar else None
            await self.bot.logging_service.log_avatar_change(after, before_url, after_url)

        if before.name != after.name:
            await self.bot.logging_service.log_username_change(after, before.name, after.name)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        """
        Handle member ban for real-time detection.

        Faster than audit log polling for immediate ban logging.
        Fetches moderator from audit log for complete info.
        """
        if self.bot.disabled:
            return

        logger.tree("MEMBER BANNED", [
            ("User", user.name),
            ("ID", str(user.id)),
            ("Guild", guild.name),
        ], emoji="🔨")

        # Try to get moderator and reason from audit log
        moderator = None
        reason = None
        try:
            async for entry in guild.audit_logs(
                action=discord.AuditLogAction.ban,
                limit=QUERY_LIMIT_TINY,
            ):
                if entry.target and entry.target.id == user.id:
                    moderator = entry.user
                    reason = entry.reason
                    break
        except discord.Forbidden:
            logger.debug(f"Audit log access denied for ban moderator lookup in {guild.name}")
        except discord.HTTPException as e:
            logger.warning("Audit Log Fetch Failed", [
                ("Action", "ban_moderator_lookup"),
                ("Guild", guild.name),
                ("Error", str(e)[:50]),
            ])

        # Log to server logs
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_ban(user, moderator, reason)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        """
        Handle member unban for real-time detection.

        Faster than audit log polling for immediate unban logging.
        Fetches moderator from audit log for complete info.
        """
        if self.bot.disabled:
            return

        logger.tree("MEMBER UNBANNED", [
            ("User", user.name),
            ("ID", str(user.id)),
            ("Guild", guild.name),
        ], emoji="🔓")

        # Try to get moderator and reason from audit log
        moderator = None
        reason = None
        try:
            async for entry in guild.audit_logs(
                action=discord.AuditLogAction.unban,
                limit=QUERY_LIMIT_TINY,
            ):
                if entry.target and entry.target.id == user.id:
                    moderator = entry.user
                    reason = entry.reason
                    break
        except discord.Forbidden:
            logger.debug(f"Audit log access denied for unban moderator lookup in {guild.name}")
        except discord.HTTPException as e:
            logger.warning("Audit Log Fetch Failed", [
                ("Action", "unban_moderator_lookup"),
                ("Guild", guild.name),
                ("Error", str(e)[:50]),
            ])

        # Log to server logs
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_unban(user, moderator, reason)

        # Clear any mute records for this user
        db = get_db()
        moderator_id = moderator.id if moderator else self.bot.user.id
        db.remove_mute(user.id, guild.id, moderator_id, "User unbanned")

    @commands.Cog.listener()
    async def on_resumed(self) -> None:
        """Event handler for bot resuming connection after disconnect."""
        logger.info("Bot Connection Resumed")


async def setup(bot: "AzabBot") -> None:
    """Add the member events cog to the bot."""
    await bot.add_cog(MemberEvents(bot))
    logger.debug("Member Events Loaded")
