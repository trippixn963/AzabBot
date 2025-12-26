"""
Azab Discord Bot - Member Events
================================

Handles member join, leave, and update events.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config
from src.core.database import get_db

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
        # Mute Role Detection
        # -----------------------------------------------------------------
        had_muted = any(r.id == self.config.muted_role_id for r in before.roles)
        has_muted = any(r.id == self.config.muted_role_id for r in after.roles)

        if not had_muted and has_muted:
            logger.tree("NEW PRISONER DETECTED", [
                ("User", str(after)),
                ("User ID", str(after.id)),
            ], emoji="⛓️")

            if self.bot.prison_handler:
                await self.bot.prison_handler.handle_new_prisoner(after)

        elif had_muted and not has_muted:
            logger.tree("PRISONER RELEASED", [
                ("User", str(after)),
                ("User ID", str(after.id)),
            ], emoji="🔓")

            if self.bot.prison_handler:
                await self.bot.prison_handler.handle_prisoner_release(after)

            # Clean up rate limiting state
            self.bot.prisoner_cooldowns.pop(after.id, None)
            self.bot.prisoner_message_buffer.pop(after.id, None)
            self.bot.prisoner_pending_response.pop(after.id, None)

        # -----------------------------------------------------------------
        # Mod Tracker: Auto-track on role add/remove
        # -----------------------------------------------------------------
        if self.bot.mod_tracker and self.bot.mod_tracker.enabled and self.config.moderation_role_id:
            had_mod_role = any(r.id == self.config.moderation_role_id for r in before.roles)
            has_mod_role = any(r.id == self.config.moderation_role_id for r in after.roles)

            if not had_mod_role and has_mod_role:
                if not self.bot.mod_tracker.is_tracked(after.id):
                    await self.bot.mod_tracker.add_tracked_mod(after)

            elif had_mod_role and not has_mod_role:
                if self.bot.mod_tracker.is_tracked(after.id):
                    await self.bot.mod_tracker.remove_tracked_mod(after.id)

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
                await self.bot.mod_tracker.log_role_change(after, added_roles, removed_roles)

        # -----------------------------------------------------------------
        # Logging Service: Role Changes
        # -----------------------------------------------------------------
        if self.bot.logging_service and self.bot.logging_service.enabled:
            added_roles = [r for r in after.roles if r not in before.roles]
            removed_roles = [r for r in before.roles if r not in after.roles]
            for role in added_roles:
                await self.bot.logging_service.log_role_add(after, role)
            for role in removed_roles:
                await self.bot.logging_service.log_role_remove(after, role)

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
            elif before.premium_since is not None and after.premium_since is None:
                await self.bot.logging_service.log_unboost(after)

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
            ("User", f"{member} ({member.id})"),
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

    async def _check_mute_evasion(self, member: discord.Member) -> None:
        """Check if rejoining member has an active mute and re-apply it."""
        db = get_db()
        config = get_config()

        active_mute = db.get_active_mute(member.id, member.guild.id)
        if not active_mute:
            return

        muted_role = member.guild.get_role(config.muted_role_id)
        if not muted_role:
            return

        try:
            await member.add_roles(muted_role, reason="Mute evasion: User rejoined with active mute")

            logger.tree("MUTE EVASION DETECTED", [
                ("User", f"{member} ({member.id})"),
                ("Action", "Re-applied muted role"),
            ], emoji="⚠️")

            if self.bot.case_log_service:
                mod_id = active_mute["moderator_id"]
                await self.bot.case_log_service.log_mute_evasion_return(member, [mod_id])

        except Exception as e:
            logger.error("Mute Evasion Re-apply Failed", [
                ("User", str(member)),
                ("Error", str(e)[:50]),
            ])

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Log member leaves and track muted users leaving."""
        # Clean up prisoner buffers
        self.bot.prisoner_cooldowns.pop(member.id, None)
        self.bot.prisoner_message_buffer.pop(member.id, None)
        self.bot.prisoner_pending_response.pop(member.id, None)

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

        logger.tree("MEMBER LEFT", [
            ("User", f"{member} ({member.id})"),
            ("Membership", membership_duration),
            ("Roles", str(role_count)),
        ], emoji="📤")

        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_member_leave(member)

        await self._check_muted_member_left(member)

    async def _check_muted_member_left(self, member: discord.Member) -> None:
        """Check if leaving member has an active mute and log it."""
        db = get_db()

        active_mute = db.get_active_mute(member.id, member.guild.id)
        if not active_mute:
            return

        logger.tree("MUTED USER LEFT", [
            ("User", f"{member} ({member.id})"),
            ("Status", "Left with active mute"),
        ], emoji="🚪")

        if self.bot.case_log_service:
            await self.bot.case_log_service.log_member_left_muted(
                user_id=member.id,
                display_name=member.display_name,
                muted_at=active_mute["muted_at"],
                avatar_url=member.display_avatar.url,
            )

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
    async def on_resumed(self) -> None:
        """Event handler for bot resuming connection after disconnect."""
        logger.info("Bot Connection Resumed")


async def setup(bot: "AzabBot") -> None:
    """Add the member events cog to the bot."""
    await bot.add_cog(MemberEvents(bot))
    logger.debug("Member Events Loaded")
