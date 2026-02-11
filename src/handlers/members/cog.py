"""
AzabBot - Member Events Cog
===========================

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
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.services.server_logs.categories import LogCategory
from src.core.constants import CASE_LOG_TIMEOUT, QUERY_LIMIT_TINY, LOG_TRUNCATE_SHORT
from src.utils.async_utils import create_safe_task
from src.utils.discord_rate_limit import log_http_error
from src.services.user_snapshots import save_member_snapshot, update_snapshot_reason
from src.api.services.event_logger import event_logger

from .constants import VERIFICATION_DELAY

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

            # Clean up prisoner tracking state
            if self.bot.prisoner_service:
                await self.bot.prisoner_service.cleanup_for_user(after.id)

        # -----------------------------------------------------------------
        # Gender Role Conflict Resolution
        # -----------------------------------------------------------------
        # If someone has a verified gender role and picks the non-verified one,
        # automatically remove the non-verified role to prevent duplicates.
        await self._resolve_gender_role_conflicts(before, after, before_role_ids, after_role_ids)

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
                    logger.debug("Audit Log Access Denied", [("Action", "role_change"), ("Guild", after.guild.name)])
                except discord.HTTPException as e:
                    log_http_error(e, "Audit Log Fetch", [
                        ("Action", "member_role_update"),
                        ("Guild", after.guild.name),
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

                # Log to dashboard events
                for role in added_roles:
                    event_logger.log_role_add(after.guild, after, role, moderator=changed_by_member)
                for role in removed_roles:
                    event_logger.log_role_remove(after.guild, after, role, moderator=changed_by_member)

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
                    # Log to dashboard events (fallback, no moderator info)
                    event_logger.log_role_add(after.guild, after, role)
                for role in removed_roles:
                    await self.bot.logging_service.log_role_remove(after, role)
                    # Log to dashboard events (fallback, no moderator info)
                    event_logger.log_role_remove(after.guild, after, role)

        # -----------------------------------------------------------------
        # Logging Service: Other Member Updates (always run)
        # -----------------------------------------------------------------
        if self.bot.logging_service and self.bot.logging_service.enabled:
            if before.nick != after.nick:
                await self.bot.logging_service.log_nickname_change(after, before.nick, after.nick)
                # Log to dashboard events (self-change, no moderator)
                event_logger.log_nick_change(
                    guild=after.guild,
                    target=after,
                    old_nick=before.nick,
                    new_nick=after.nick,
                )
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

        # Log to dashboard (handles console logging too)
        event_logger.log_join(member, invite_code=invite_code, inviter=inviter)

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
            logger.debug("Verification Role Assign Denied", [("Member", str(member))])
        except discord.HTTPException as e:
            logger.debug("Verification Role Assign Failed", [("Member", str(member)), ("Error", str(e)[:50])])

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Log member leaves, track muted users leaving, delete linked messages, save snapshot."""
        # Save user snapshot BEFORE anything else (while we still have member data)
        save_member_snapshot(member, reason="leave")

        # Clean up prisoner tracking state
        if self.bot.prisoner_service:
            await self.bot.prisoner_service.cleanup_for_user(member.id)

        # Auto-close any open tickets where this user is the OP
        await self._handle_ticket_op_left(member)

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
            logger.debug("Audit Log Access Denied", [("Action", "ban_check"), ("Guild", member.guild.name)])
        except discord.HTTPException as e:
            log_http_error(e, "Audit Log Fetch", [
                ("Action", "ban_check"),
                ("Guild", member.guild.name),
            ])

        # Log to dashboard (handles console logging too)
        # Ban is logged separately in on_member_ban
        if not was_banned:
            event_logger.log_leave(member, roles=member.roles, membership_duration=membership_duration)

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

    async def _handle_ticket_op_left(self, member: discord.Member) -> None:
        """Auto-close any open tickets where the leaving member is the opener."""
        if self.bot.ticket_service and self.bot.ticket_service.enabled:
            await self.bot.ticket_service.handle_op_left(member)

    async def _delete_linked_messages(self, member: discord.Member) -> None:
        """Delete all messages linked to a leaving member."""
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

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.ALLIANCES,
                embed,
            )

        except Exception as e:
            logger.debug("Linked Message Deletion Log Failed", [("Error", str(e)[:50])])

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

        # The on_member_remove handler should have already saved the snapshot,
        # but we update the reason to 'ban' to indicate this wasn't just a leave
        update_snapshot_reason(user.id, guild.id, "ban")

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
            logger.debug("Audit Log Access Denied", [("Action", "ban_moderator_lookup"), ("Guild", guild.name)])
        except discord.HTTPException as e:
            log_http_error(e, "Audit Log Fetch", [
                ("Action", "ban_moderator_lookup"),
                ("Guild", guild.name),
            ])

        # Log to dashboard (handles console logging too)
        event_logger.log_ban(guild=guild, target=user, moderator=moderator, reason=reason)

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
            logger.debug("Audit Log Access Denied", [("Action", "unban_moderator_lookup"), ("Guild", guild.name)])
        except discord.HTTPException as e:
            log_http_error(e, "Audit Log Fetch", [
                ("Action", "unban_moderator_lookup"),
                ("Guild", guild.name),
            ])

        # Log to dashboard (handles console logging too)
        event_logger.log_unban(guild=guild, target=user, moderator=moderator, reason=reason)

        # Log to server logs
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_unban(user, moderator, reason)

        # Clear any mute records for this user
        db = get_db()
        moderator_id = moderator.id if moderator else self.bot.user.id
        db.remove_mute(user.id, guild.id, moderator_id, "User unbanned")

    # =========================================================================
    # Gender Role Conflict Resolution
    # =========================================================================

    async def _resolve_gender_role_conflicts(
        self,
        before: discord.Member,
        after: discord.Member,
        before_role_ids: set,
        after_role_ids: set,
    ) -> None:
        """
        Resolve conflicts between verified and non-verified gender roles.

        If a member has a verified gender role and gains the non-verified version,
        automatically remove the non-verified role. Verified roles can only be
        removed manually by moderators.
        """
        # Skip if gender roles aren't configured
        if not all([
            self.config.male_role_id,
            self.config.male_verified_role_id,
            self.config.female_role_id,
            self.config.female_verified_role_id,
        ]):
            logger.debug("Gender role conflict resolution skipped: roles not configured")
            return

        # Define role conflict pairs: (verified_role_id, non_verified_role_id, name)
        conflict_pairs = [
            (self.config.male_verified_role_id, self.config.male_role_id, "Male"),
            (self.config.female_verified_role_id, self.config.female_role_id, "Female"),
        ]

        for verified_id, non_verified_id, gender_name in conflict_pairs:
            has_verified = verified_id in after_role_ids
            has_non_verified = non_verified_id in after_role_ids

            # Only act if both roles are present
            if not (has_verified and has_non_verified):
                continue

            # Determine what triggered this conflict
            just_gained_verified = verified_id not in before_role_ids
            just_gained_non_verified = non_verified_id not in before_role_ids

            # Get the role object to remove
            non_verified_role = after.guild.get_role(non_verified_id)
            verified_role = after.guild.get_role(verified_id)

            if not non_verified_role:
                logger.warning("Gender Role Not Found", [
                    ("Role ID", str(non_verified_id)),
                    ("Gender", gender_name),
                    ("Type", "Non-verified"),
                ])
                continue

            # Remove the non-verified role
            try:
                await after.remove_roles(
                    non_verified_role,
                    reason=f"Auto-removed: {gender_name} Verified role takes precedence"
                )

                # Determine action description for logging
                if just_gained_verified:
                    action = "Gained verified role, non-verified auto-removed"
                elif just_gained_non_verified:
                    action = "Tried to add non-verified while already verified"
                else:
                    action = "Conflict detected, non-verified removed"

                # Console tree logging
                logger.tree("GENDER ROLE CONFLICT RESOLVED", [
                    ("User", f"{after.name} ({after.id})"),
                    ("Gender", gender_name),
                    ("Action", action),
                    ("Removed", non_verified_role.name),
                    ("Kept", verified_role.name if verified_role else "Unknown"),
                ], emoji="🔄")

                # Log to server logs (if enabled)
                await self._log_gender_role_resolution(
                    after, gender_name, non_verified_role, verified_role, action
                )

            except discord.Forbidden:
                logger.warning("Cannot Remove Gender Role", [
                    ("User", f"{after.name} ({after.id})"),
                    ("Role", non_verified_role.name),
                    ("Reason", "Missing permissions or role hierarchy"),
                ])
            except discord.HTTPException as e:
                log_http_error(e, "Gender Role Removal", [
                    ("User", f"{after.name} ({after.id})"),
                    ("Role", non_verified_role.name),
                ])

    async def _log_gender_role_resolution(
        self,
        member: discord.Member,
        gender_name: str,
        removed_role: discord.Role,
        kept_role: discord.Role,
        action: str,
    ) -> None:
        """Log gender role conflict resolution to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="🔄 Gender Role Conflict Resolved",
                color=EmbedColors.LOG_INFO,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(
                name="Member",
                value=f"{member.mention}\n`{member.id}`",
                inline=True,
            )
            embed.add_field(
                name="Gender",
                value=gender_name,
                inline=True,
            )
            embed.add_field(
                name="Action",
                value=action,
                inline=False,
            )
            embed.add_field(
                name="Removed Role",
                value=f"{removed_role.mention} (non-verified)",
                inline=True,
            )
            embed.add_field(
                name="Kept Role",
                value=f"{kept_role.mention} (verified)" if kept_role else "Unknown",
                inline=True,
            )
            embed.set_thumbnail(url=member.display_avatar.url)

            await self.bot.logging_service._send_log(
                LogCategory.AUTOMOD,
                embed,
                user_id=member.id,
            )
            logger.debug("Gender Role Resolution Logged", [("User", str(member.id))])

        except discord.HTTPException as e:
            log_http_error(e, "Gender Role Resolution Log", [
                ("User", str(member.id)),
            ])
        except Exception as e:
            logger.error("Gender Role Log Failed", [
                ("User", str(member.id)),
                ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ("Type", type(e).__name__),
            ])

    @commands.Cog.listener()
    async def on_resumed(self) -> None:
        """Event handler for bot resuming connection after disconnect."""
        logger.info("Bot Connection Resumed")


__all__ = ["MemberEvents"]
