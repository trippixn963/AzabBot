"""
Azab Discord Bot - Channel & Misc Events
=========================================

Handles channel, thread, role, emoji, sticker, invite, voice,
reaction, stage, scheduled event, and automod events.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config

if TYPE_CHECKING:
    from src.bot import AzabBot


class ChannelEvents(commands.Cog):
    """Channel and miscellaneous event handlers."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()

    # =========================================================================
    # Channel Events
    # =========================================================================

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        """Log channel creations and auto-hide from muted role."""
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_channel_create(channel)

        await self.bot._auto_hide_from_muted(channel)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """Log channel deletions."""
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_channel_delete(channel.name, str(channel.type))

    # =========================================================================
    # Role Events
    # =========================================================================

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        """Log role creations."""
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_role_create(role)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        """Log role deletions."""
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_role_delete(role.name)

    # =========================================================================
    # Emoji & Sticker Events
    # =========================================================================

    @commands.Cog.listener()
    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before: tuple,
        after: tuple,
    ) -> None:
        """Log emoji changes."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        before_ids = {e.id for e in before}
        after_ids = {e.id for e in after}

        for emoji in after:
            if emoji.id not in before_ids:
                await self.bot.logging_service.log_emoji_create(emoji)

        for emoji in before:
            if emoji.id not in after_ids:
                await self.bot.logging_service.log_emoji_delete(emoji.name)

    @commands.Cog.listener()
    async def on_guild_stickers_update(
        self,
        guild: discord.Guild,
        before: tuple,
        after: tuple,
    ) -> None:
        """Log sticker changes."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        before_ids = {s.id for s in before}
        after_ids = {s.id for s in after}

        for sticker in after:
            if sticker.id not in before_ids:
                await self.bot.logging_service.log_sticker_create(sticker)

        for sticker in before:
            if sticker.id not in after_ids:
                await self.bot.logging_service.log_sticker_delete(sticker.name)

    # =========================================================================
    # Invite Events
    # =========================================================================

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        """Update invite cache and log when new invite is created."""
        self.bot._invite_cache[invite.code] = invite.uses or 0

        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_invite_create(invite)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        """Update invite cache and log when invite is deleted."""
        uses = self.bot._invite_cache.pop(invite.code, None)

        if self.bot.logging_service and self.bot.logging_service.enabled:
            channel_name = invite.channel.name if invite.channel else "Unknown"
            await self.bot.logging_service.log_invite_delete(
                invite_code=invite.code,
                channel_name=channel_name,
                uses=uses,
            )

    # =========================================================================
    # Thread Events
    # =========================================================================

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        """Log thread and forum post creations."""
        if self.bot.logging_service and self.bot.logging_service.enabled:
            creator = thread.owner

            if thread.parent and isinstance(thread.parent, discord.ForumChannel):
                await self.bot.logging_service.log_forum_post_create(thread, creator)
            else:
                await self.bot.logging_service.log_thread_create(thread, creator)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread) -> None:
        """Log thread deletions."""
        if self.bot.logging_service and self.bot.logging_service.enabled:
            parent_name = thread.parent.name if thread.parent else "Unknown"
            await self.bot.logging_service.log_thread_delete(thread.name, parent_name)

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread) -> None:
        """Log thread archive/unarchive and lock/unlock."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        if before.archived != after.archived:
            await self.bot.logging_service.log_thread_archive(after, after.archived)

        if before.locked != after.locked:
            await self.bot.logging_service.log_thread_lock(after, after.locked)

    @commands.Cog.listener()
    async def on_thread_member_join(self, member: discord.ThreadMember) -> None:
        """Log when members are added to private threads."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        thread = member.thread
        if not thread:
            return

        # Only track private threads (invitable threads that aren't public)
        if not thread.is_private():
            return

        # Get the user who was added
        user = self.bot.get_user(member.id)
        if not user:
            try:
                user = await self.bot.fetch_user(member.id)
            except discord.NotFound:
                return

        # Try to find who added them from audit log
        added_by = None
        if thread.guild:
            try:
                async for entry in thread.guild.audit_logs(
                    action=discord.AuditLogAction.thread_member_add,
                    limit=5,
                ):
                    if entry.target and entry.target.id == member.id:
                        added_by = entry.user
                        break
            except discord.Forbidden:
                logger.debug(f"Audit log access denied for thread member add lookup in {thread.guild.name}")
            except discord.HTTPException as e:
                logger.warning("Audit Log Fetch Failed", [
                    ("Action", "thread_member_add"),
                    ("Guild", thread.guild.name),
                    ("Error", str(e)[:50]),
                ])

        await self.bot.logging_service.log_thread_member_add(
            thread=thread,
            user=user,
            added_by=added_by,
        )

        # Also track in mod_tracker if a mod added someone to a private thread
        if added_by and self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(added_by.id):
            await self.bot.mod_tracker.log_thread_member_add(
                mod_id=added_by.id,
                thread=thread,
                user=user,
            )

    @commands.Cog.listener()
    async def on_thread_member_remove(self, member: discord.ThreadMember) -> None:
        """Log when members are removed from private threads."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        thread = member.thread
        if not thread:
            return

        # Only track private threads
        if not thread.is_private():
            return

        # Get the user who was removed
        user = self.bot.get_user(member.id)
        if not user:
            try:
                user = await self.bot.fetch_user(member.id)
            except discord.NotFound:
                return

        # Try to find who removed them from audit log
        removed_by = None
        if thread.guild:
            try:
                async for entry in thread.guild.audit_logs(
                    action=discord.AuditLogAction.thread_member_remove,
                    limit=5,
                ):
                    if entry.target and entry.target.id == member.id:
                        removed_by = entry.user
                        break
            except discord.Forbidden:
                logger.debug(f"Audit log access denied for thread member remove lookup in {thread.guild.name}")
            except discord.HTTPException as e:
                logger.warning("Audit Log Fetch Failed", [
                    ("Action", "thread_member_remove"),
                    ("Guild", thread.guild.name),
                    ("Error", str(e)[:50]),
                ])

        await self.bot.logging_service.log_thread_member_remove(
            thread=thread,
            user=user,
            removed_by=removed_by,
        )

    # =========================================================================
    # Voice Events
    # =========================================================================

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Delegate voice state changes to the voice handler."""
        if self.bot.voice_handler:
            await self.bot.voice_handler.handle_voice_state_update(member, before, after)

    # =========================================================================
    # Reaction Events
    # =========================================================================

    @commands.Cog.listener()
    async def on_reaction_add(
        self,
        reaction: discord.Reaction,
        user: discord.Member | discord.User,
    ) -> None:
        """Log reaction additions."""
        if user.bot or not isinstance(user, discord.Member):
            return

        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_reaction_add(reaction, user, reaction.message)

    @commands.Cog.listener()
    async def on_reaction_remove(
        self,
        reaction: discord.Reaction,
        user: discord.Member | discord.User,
    ) -> None:
        """Log reaction removals."""
        if user.bot or not isinstance(user, discord.Member):
            return

        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_reaction_remove(reaction, user, reaction.message)

    @commands.Cog.listener()
    async def on_reaction_clear(
        self,
        message: discord.Message,
        reactions: list,
    ) -> None:
        """Log all reactions being cleared."""
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_reaction_clear(message)

    # =========================================================================
    # Stage Events
    # =========================================================================

    @commands.Cog.listener()
    async def on_stage_instance_create(self, stage: discord.StageInstance) -> None:
        """Log stage instance starting."""
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_stage_start(stage)

    @commands.Cog.listener()
    async def on_stage_instance_delete(self, stage: discord.StageInstance) -> None:
        """Log stage instance ending."""
        if self.bot.logging_service and self.bot.logging_service.enabled:
            channel_name = stage.channel.name if stage.channel else "Unknown"
            await self.bot.logging_service.log_stage_end(channel_name, stage.topic)

    @commands.Cog.listener()
    async def on_stage_instance_update(
        self,
        before: discord.StageInstance,
        after: discord.StageInstance,
    ) -> None:
        """Log stage instance updates."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        changes = []
        if before.topic != after.topic:
            changes.append(f"Topic: {before.topic} → {after.topic}")
        if before.privacy_level != after.privacy_level:
            changes.append(f"Privacy: {after.privacy_level.name}")

        if changes:
            await self.bot.logging_service.log_stage_update(after, ", ".join(changes))

    # =========================================================================
    # Scheduled Event Events
    # =========================================================================

    @commands.Cog.listener()
    async def on_scheduled_event_create(self, event: discord.ScheduledEvent) -> None:
        """Log scheduled event creations."""
        if self.bot.logging_service and self.bot.logging_service.enabled:
            creator = event.creator
            await self.bot.logging_service.log_event_create(event, creator)

    @commands.Cog.listener()
    async def on_scheduled_event_delete(self, event: discord.ScheduledEvent) -> None:
        """Log scheduled event deletions."""
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_event_delete(event.name)

    @commands.Cog.listener()
    async def on_scheduled_event_update(
        self,
        before: discord.ScheduledEvent,
        after: discord.ScheduledEvent,
    ) -> None:
        """Log scheduled event updates and status changes."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        if before.status != after.status:
            if after.status == discord.EventStatus.active:
                await self.bot.logging_service.log_event_start(after)
            elif after.status in (discord.EventStatus.completed, discord.EventStatus.cancelled):
                await self.bot.logging_service.log_event_end(after)
            return

        changes = []
        if before.name != after.name:
            changes.append(f"Name: {before.name} → {after.name}")
        if before.description != after.description:
            changes.append("Description changed")
        if before.start_time != after.start_time:
            changes.append("Start time changed")
        if before.location != after.location:
            changes.append(f"Location: {before.location} → {after.location}")

        if changes:
            await self.bot.logging_service.log_event_update(after, ", ".join(changes))

    # =========================================================================
    # AutoMod Events
    # =========================================================================

    @commands.Cog.listener()
    async def on_automod_action(self, execution: discord.AutoModAction) -> None:
        """Log AutoMod actions."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            member = execution.member
            if not member and execution.user_id:
                guild = self.bot.get_guild(execution.guild_id)
                if guild:
                    member = guild.get_member(execution.user_id)

            if not member:
                return

            rule_name = "Unknown Rule"
            if execution.rule_id:
                try:
                    guild = self.bot.get_guild(execution.guild_id)
                    if guild:
                        rule = await guild.fetch_automod_rule(execution.rule_id)
                        rule_name = rule.name
                except Exception:
                    pass

            channel = None
            if execution.channel_id:
                channel = self.bot.get_channel(execution.channel_id)

            action_type = str(execution.action.type.name) if execution.action else "unknown"
            content = execution.content
            matched = execution.matched_keyword

            if execution.action and execution.action.type == discord.AutoModRuleActionType.block_message:
                await self.bot.logging_service.log_automod_block(
                    rule_name=rule_name,
                    user=member,
                    channel=channel,
                    content=content,
                    matched_keyword=matched,
                )
            else:
                await self.bot.logging_service.log_automod_action(
                    rule_name=rule_name,
                    action_type=action_type,
                    user=member,
                    channel=channel,
                    content=content,
                    matched_keyword=matched,
                )
        except Exception as e:
            logger.debug(f"AutoMod log failed: {e}")


async def setup(bot: "AzabBot") -> None:
    """Add the channel events cog to the bot."""
    await bot.add_cog(ChannelEvents(bot))
    logger.debug("Channel Events Loaded")
