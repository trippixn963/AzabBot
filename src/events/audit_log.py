"""
Azab Discord Bot - Audit Log Events
====================================

Handles audit log entries and routes them to mod_tracker and logging_service.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ

if TYPE_CHECKING:
    from src.bot import AzabBot


class AuditLogEvents(commands.Cog):
    """Audit log event handlers."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry) -> None:
        """
        Track mod actions via audit log entries.

        DESIGN: Uses audit log to identify which mod performed actions.
        Routes events to both mod_tracker and logging_service.
        """
        # Route to anti-nuke service
        await self._check_antinuke(entry)

        # Route to logging service
        await self._log_audit_event(entry)

        # Route to mod tracker
        await self._track_mod_action(entry)

    # =========================================================================
    # Anti-Nuke Detection
    # =========================================================================

    async def _check_antinuke(self, entry: discord.AuditLogEntry) -> None:
        """Route audit log events to anti-nuke service for detection."""
        if not self.bot.antinuke_service:
            return

        if not entry.user_id or not entry.guild:
            return

        try:
            # Track bans
            if entry.action == discord.AuditLogAction.ban:
                await self.bot.antinuke_service.track_ban(entry.guild, entry.user_id)

            # Track kicks
            elif entry.action == discord.AuditLogAction.kick:
                await self.bot.antinuke_service.track_kick(entry.guild, entry.user_id)

            # Track channel deletions
            elif entry.action == discord.AuditLogAction.channel_delete:
                await self.bot.antinuke_service.track_channel_delete(entry.guild, entry.user_id)

            # Track role deletions
            elif entry.action == discord.AuditLogAction.role_delete:
                await self.bot.antinuke_service.track_role_delete(entry.guild, entry.user_id)

        except Exception as e:
            from src.core.logger import logger
            logger.debug(f"Anti-nuke check failed: {e}")

    # =========================================================================
    # Mod Tracker Routing
    # =========================================================================

    async def _track_mod_action(self, entry: discord.AuditLogEntry) -> None:
        """Route audit log events to mod tracker."""
        if not self.bot.mod_tracker or not self.bot.mod_tracker.enabled:
            return

        mod_id = entry.user_id
        if not mod_id or not self.bot.mod_tracker.is_tracked(mod_id):
            return

        try:
            # Timeout
            if entry.action == discord.AuditLogAction.member_update:
                if hasattr(entry.after, 'timed_out_until') and entry.after.timed_out_until:
                    await self.bot.mod_tracker.log_timeout(
                        mod_id=mod_id,
                        target=entry.target,
                        until=entry.after.timed_out_until,
                        reason=entry.reason,
                    )

                old_timeout = getattr(entry.before, 'timed_out_until', None)
                new_timeout = getattr(entry.after, 'timed_out_until', None)
                if old_timeout and not new_timeout:
                    await self.bot.mod_tracker.log_timeout_remove(
                        mod_id=mod_id,
                        target=entry.target,
                        original_until=old_timeout,
                    )

                # Voice mute/deafen
                if entry.target:
                    if hasattr(entry.before, 'mute') and hasattr(entry.after, 'mute'):
                        if entry.before.mute != entry.after.mute:
                            action = "muted" if entry.after.mute else "unmuted"
                            await self.bot.mod_tracker.log_voice_mute_deafen(
                                mod_id=mod_id,
                                target=entry.target,
                                action=action,
                            )
                    if hasattr(entry.before, 'deaf') and hasattr(entry.after, 'deaf'):
                        if entry.before.deaf != entry.after.deaf:
                            action = "deafened" if entry.after.deaf else "undeafened"
                            await self.bot.mod_tracker.log_voice_mute_deafen(
                                mod_id=mod_id,
                                target=entry.target,
                                action=action,
                            )

                # Nickname change by mod
                if entry.target and entry.target.id != mod_id:
                    if hasattr(entry.before, 'nick') and hasattr(entry.after, 'nick'):
                        if entry.before.nick != entry.after.nick:
                            await self.bot.mod_tracker.log_nickname_change(
                                mod_id=mod_id,
                                target=entry.target,
                                old_nick=entry.before.nick,
                                new_nick=entry.after.nick,
                            )

            # Kick
            elif entry.action == discord.AuditLogAction.kick:
                if entry.target and entry.target.bot:
                    await self.bot.mod_tracker.log_bot_remove(
                        mod_id=mod_id,
                        bot_name=entry.target.name,
                        bot_id=entry.target.id,
                    )
                else:
                    await self.bot.mod_tracker.log_kick(
                        mod_id=mod_id,
                        target=entry.target,
                        reason=entry.reason,
                    )

            # Ban
            elif entry.action == discord.AuditLogAction.ban:
                await self.bot.mod_tracker.log_ban(
                    mod_id=mod_id,
                    target=entry.target,
                    reason=entry.reason,
                )
                # Check if repeat offender
                if entry.target and entry.guild:
                    await self.bot.mod_tracker.check_repeat_offender_on_ban(
                        user_id=entry.target.id,
                        guild_id=entry.guild.id,
                    )

            # Unban
            elif entry.action == discord.AuditLogAction.unban:
                await self.bot.mod_tracker.log_unban(
                    mod_id=mod_id,
                    target=entry.target,
                    reason=entry.reason,
                )
                # Check for quick unban pattern
                if entry.target and entry.guild:
                    await self.bot.mod_tracker.check_quick_unban_pattern(
                        user_id=entry.target.id,
                        guild_id=entry.guild.id,
                        unban_mod_id=mod_id,
                    )

            # Channel create
            elif entry.action == discord.AuditLogAction.channel_create:
                if entry.target:
                    await self.bot.mod_tracker.log_channel_create(
                        mod_id=mod_id,
                        channel=entry.target,
                    )

            # Channel delete
            elif entry.action == discord.AuditLogAction.channel_delete:
                channel_name = getattr(entry.before, 'name', 'Unknown')
                channel_type = str(getattr(entry.target, 'type', 'Unknown'))
                await self.bot.mod_tracker.log_channel_delete(
                    mod_id=mod_id,
                    channel_name=channel_name,
                    channel_type=channel_type,
                )

            # Channel update
            elif entry.action == discord.AuditLogAction.channel_update:
                if entry.target:
                    if hasattr(entry.before, 'slowmode_delay') and hasattr(entry.after, 'slowmode_delay'):
                        if entry.before.slowmode_delay != entry.after.slowmode_delay:
                            await self.bot.mod_tracker.log_slowmode_change(
                                mod_id=mod_id,
                                channel=entry.target,
                                old_delay=entry.before.slowmode_delay or 0,
                                new_delay=entry.after.slowmode_delay or 0,
                            )

                    if isinstance(entry.target, discord.ForumChannel):
                        old_tags = getattr(entry.before, 'available_tags', []) or []
                        new_tags = getattr(entry.after, 'available_tags', []) or []
                        old_tag_names = {t.name for t in old_tags}
                        new_tag_names = {t.name for t in new_tags}

                        for tag_name in new_tag_names - old_tag_names:
                            await self.bot.mod_tracker.log_forum_tag_create(
                                mod_id=mod_id,
                                forum=entry.target,
                                tag_name=tag_name,
                            )

                        for tag_name in old_tag_names - new_tag_names:
                            await self.bot.mod_tracker.log_forum_tag_delete(
                                mod_id=mod_id,
                                forum=entry.target,
                                tag_name=tag_name,
                            )

                        if len(old_tags) == len(new_tags):
                            for old_tag, new_tag in zip(
                                sorted(old_tags, key=lambda t: t.id),
                                sorted(new_tags, key=lambda t: t.id)
                            ):
                                if old_tag.id == new_tag.id and old_tag.name != new_tag.name:
                                    await self.bot.mod_tracker.log_forum_tag_update(
                                        mod_id=mod_id,
                                        forum=entry.target,
                                        old_name=old_tag.name,
                                        new_name=new_tag.name,
                                    )

                    changes = []
                    if hasattr(entry.before, 'name') and hasattr(entry.after, 'name'):
                        if entry.before.name != entry.after.name:
                            changes.append(f"Name: {entry.before.name} → {entry.after.name}")
                    if hasattr(entry.before, 'topic') and hasattr(entry.after, 'topic'):
                        if entry.before.topic != entry.after.topic:
                            changes.append("Topic changed")
                    if changes:
                        await self.bot.mod_tracker.log_channel_update(
                            mod_id=mod_id,
                            channel=entry.target,
                            changes=", ".join(changes) if changes else "Settings updated",
                        )

            # Role create
            elif entry.action == discord.AuditLogAction.role_create:
                if entry.target:
                    await self.bot.mod_tracker.log_role_create(
                        mod_id=mod_id,
                        role=entry.target,
                    )

            # Role delete
            elif entry.action == discord.AuditLogAction.role_delete:
                role_name = getattr(entry.before, 'name', 'Unknown')
                await self.bot.mod_tracker.log_role_delete(
                    mod_id=mod_id,
                    role_name=role_name,
                )

            # Role update
            elif entry.action == discord.AuditLogAction.role_update:
                if entry.target:
                    changes = []
                    if hasattr(entry.before, 'name') and hasattr(entry.after, 'name'):
                        if entry.before.name != entry.after.name:
                            changes.append(f"Name: {entry.before.name} → {entry.after.name}")
                    if hasattr(entry.before, 'permissions') and hasattr(entry.after, 'permissions'):
                        if entry.before.permissions != entry.after.permissions:
                            changes.append("Permissions changed")
                    if hasattr(entry.before, 'color') and hasattr(entry.after, 'color'):
                        if entry.before.color != entry.after.color:
                            changes.append("Color changed")

                    old_icon = getattr(entry.before, 'icon', None)
                    new_icon = getattr(entry.after, 'icon', None)
                    if old_icon != new_icon:
                        if old_icon is None and new_icon is not None:
                            await self.bot.mod_tracker.log_role_icon_change(
                                mod_id=mod_id, role=entry.target, action="added",
                            )
                        elif old_icon is not None and new_icon is None:
                            await self.bot.mod_tracker.log_role_icon_change(
                                mod_id=mod_id, role=entry.target, action="removed",
                            )
                        else:
                            await self.bot.mod_tracker.log_role_icon_change(
                                mod_id=mod_id, role=entry.target, action="changed",
                            )

                    if changes:
                        await self.bot.mod_tracker.log_role_update(
                            mod_id=mod_id,
                            role=entry.target,
                            changes=", ".join(changes) if changes else "Settings updated",
                        )

            # Message pin/unpin
            elif entry.action == discord.AuditLogAction.message_pin:
                if hasattr(entry.extra, 'channel'):
                    channel = entry.extra.channel
                    message_id = entry.extra.message_id if hasattr(entry.extra, 'message_id') else None
                    try:
                        message = await channel.fetch_message(message_id)
                        await self.bot.mod_tracker.log_message_pin(
                            mod_id=mod_id, channel=channel, message=message, pinned=True,
                        )
                    except Exception:
                        # Fallback when message can't be fetched
                        await self.bot.mod_tracker.log_message_pin(
                            mod_id=mod_id, channel=channel, pinned=True, message_id=message_id,
                        )

            elif entry.action == discord.AuditLogAction.message_unpin:
                if hasattr(entry.extra, 'channel'):
                    channel = entry.extra.channel
                    message_id = entry.extra.message_id if hasattr(entry.extra, 'message_id') else None
                    try:
                        message = await channel.fetch_message(message_id)
                        await self.bot.mod_tracker.log_message_pin(
                            mod_id=mod_id, channel=channel, message=message, pinned=False,
                        )
                    except Exception:
                        # Fallback when message can't be fetched (deleted message)
                        await self.bot.mod_tracker.log_message_pin(
                            mod_id=mod_id, channel=channel, pinned=False, message_id=message_id,
                        )

            # Emoji create/delete
            elif entry.action == discord.AuditLogAction.emoji_create:
                if entry.target:
                    await self.bot.mod_tracker.log_emoji_create(mod_id=mod_id, emoji=entry.target)

            elif entry.action == discord.AuditLogAction.emoji_delete:
                emoji_name = getattr(entry.before, 'name', 'Unknown')
                await self.bot.mod_tracker.log_emoji_delete(mod_id=mod_id, emoji_name=emoji_name)

            # Webhook create/delete
            elif entry.action == discord.AuditLogAction.webhook_create:
                webhook_name = getattr(entry.target, 'name', 'Unknown')
                channel_name = getattr(entry.extra, 'channel', None)
                channel_name = channel_name.name if channel_name else "Unknown"
                await self.bot.mod_tracker.log_webhook_create(
                    mod_id=mod_id, webhook_name=webhook_name, channel_name=channel_name,
                )

            elif entry.action == discord.AuditLogAction.webhook_delete:
                webhook_name = getattr(entry.before, 'name', 'Unknown')
                await self.bot.mod_tracker.log_webhook_delete(
                    mod_id=mod_id, webhook_name=webhook_name, channel_name="Unknown",
                )

            # Guild update
            elif entry.action == discord.AuditLogAction.guild_update:
                changes = []
                if hasattr(entry.before, 'name') and hasattr(entry.after, 'name'):
                    if entry.before.name != entry.after.name:
                        changes.append(f"Name: {entry.before.name} → {entry.after.name}")
                if hasattr(entry.before, 'icon') and hasattr(entry.after, 'icon'):
                    if entry.before.icon != entry.after.icon:
                        changes.append("Icon changed")

                if hasattr(entry.before, 'verification_level') and hasattr(entry.after, 'verification_level'):
                    if entry.before.verification_level != entry.after.verification_level:
                        await self.bot.mod_tracker.log_verification_level_change(
                            mod_id=mod_id,
                            old_level=str(entry.before.verification_level).replace('_', ' ').title(),
                            new_level=str(entry.after.verification_level).replace('_', ' ').title(),
                        )

                if hasattr(entry.before, 'explicit_content_filter') and hasattr(entry.after, 'explicit_content_filter'):
                    if entry.before.explicit_content_filter != entry.after.explicit_content_filter:
                        await self.bot.mod_tracker.log_explicit_filter_change(
                            mod_id=mod_id,
                            old_filter=str(entry.before.explicit_content_filter).replace('_', ' ').title(),
                            new_filter=str(entry.after.explicit_content_filter).replace('_', ' ').title(),
                        )

                if hasattr(entry.before, 'mfa_level') and hasattr(entry.after, 'mfa_level'):
                    if entry.before.mfa_level != entry.after.mfa_level:
                        await self.bot.mod_tracker.log_2fa_requirement_change(
                            mod_id=mod_id, enabled=entry.after.mfa_level == 1,
                        )

                if changes:
                    await self.bot.mod_tracker.log_guild_update(
                        mod_id=mod_id,
                        changes=", ".join(changes) if changes else "Server settings updated",
                    )

            # Thread create/delete
            elif entry.action == discord.AuditLogAction.thread_create:
                if entry.target:
                    await self.bot.mod_tracker.log_thread_create(mod_id=mod_id, thread=entry.target)

            elif entry.action == discord.AuditLogAction.thread_delete:
                thread_name = getattr(entry.before, 'name', 'Unknown')
                parent_name = "Unknown"
                if hasattr(entry.target, 'parent') and entry.target.parent:
                    parent_name = entry.target.parent.name
                await self.bot.mod_tracker.log_thread_delete(
                    mod_id=mod_id, thread_name=thread_name, parent_name=parent_name,
                )

            # Invite create/delete
            elif entry.action == discord.AuditLogAction.invite_create:
                if entry.target:
                    await self.bot.mod_tracker.log_invite_create(mod_id=mod_id, invite=entry.target)

            elif entry.action == discord.AuditLogAction.invite_delete:
                invite_code = getattr(entry.target, 'code', 'Unknown')
                channel_name = "Unknown"
                if hasattr(entry.target, 'channel') and entry.target.channel:
                    channel_name = entry.target.channel.name
                await self.bot.mod_tracker.log_invite_delete(
                    mod_id=mod_id, invite_code=invite_code, channel_name=channel_name,
                )

            # AutoMod rules
            elif hasattr(discord.AuditLogAction, 'auto_moderation_rule_create') and \
                    entry.action == discord.AuditLogAction.auto_moderation_rule_create:
                rule_name = getattr(entry.target, 'name', 'Unknown')
                trigger_type = str(getattr(entry.target, 'trigger_type', 'Unknown'))
                await self.bot.mod_tracker.log_automod_rule_create(
                    mod_id=mod_id, rule_name=rule_name, trigger_type=trigger_type,
                )

            elif hasattr(discord.AuditLogAction, 'auto_moderation_rule_update') and \
                    entry.action == discord.AuditLogAction.auto_moderation_rule_update:
                rule_name = getattr(entry.target, 'name', 'Unknown')
                await self.bot.mod_tracker.log_automod_rule_update(
                    mod_id=mod_id, rule_name=rule_name, changes="Settings updated",
                )

            elif hasattr(discord.AuditLogAction, 'auto_moderation_rule_delete') and \
                    entry.action == discord.AuditLogAction.auto_moderation_rule_delete:
                rule_name = getattr(entry.before, 'name', 'Unknown')
                await self.bot.mod_tracker.log_automod_rule_delete(mod_id=mod_id, rule_name=rule_name)

            # Member voice move
            elif entry.action == discord.AuditLogAction.member_move:
                if entry.extra and hasattr(entry.extra, 'channel'):
                    to_channel = entry.extra.channel
                    count = getattr(entry.extra, 'count', 1)
                    embed = discord.Embed(
                        title="🔀 Voice Move",
                        color=EmbedColors.GOLD,
                        timestamp=datetime.now(NY_TZ),
                    )
                    embed.add_field(name="To Channel", value=f"`{to_channel.name}`", inline=True)
                    embed.add_field(name="Count", value=f"`{count}`", inline=True)
                    embed.set_footer(text="Voice • Bulk Move")
                    await self.bot.mod_tracker._send_log(mod_id, embed, "Voice Move")

            # Bulk message delete
            elif entry.action == discord.AuditLogAction.message_bulk_delete:
                if entry.target:
                    count = getattr(entry.extra, 'count', 0) if entry.extra else 0
                    await self.bot.mod_tracker.log_message_purge(
                        mod_id=mod_id, channel=entry.target, count=count,
                    )

            # Member role update
            elif entry.action == discord.AuditLogAction.member_role_update:
                if hasattr(entry.before, 'roles') and hasattr(entry.after, 'roles'):
                    before_roles = set(entry.before.roles) if entry.before.roles else set()
                    after_roles = set(entry.after.roles) if entry.after.roles else set()

                    # Self-role changes are handled by members.py via log_role_change
                    # which now detects self-changes and uses alert styling with ping
                    if entry.target and entry.target.id != mod_id:
                        # Only log when mod assigns roles to OTHERS (not self)
                        for role in after_roles - before_roles:
                            await self.bot.mod_tracker.log_role_assign(
                                mod_id=mod_id, target=entry.target, role=role, action="added",
                            )
                        for role in before_roles - after_roles:
                            await self.bot.mod_tracker.log_role_assign(
                                mod_id=mod_id, target=entry.target, role=role, action="removed",
                            )

            # Voice disconnect
            elif entry.action == discord.AuditLogAction.member_disconnect:
                if entry.target:
                    channel_name = "Unknown"
                    if entry.extra and hasattr(entry.extra, 'channel'):
                        channel_name = entry.extra.channel.name
                    await self.bot.mod_tracker.log_voice_disconnect(
                        mod_id=mod_id, target=entry.target, channel_name=channel_name,
                    )

            # Permission overwrites
            elif entry.action == discord.AuditLogAction.overwrite_create:
                if entry.target and entry.extra:
                    target_name = getattr(entry.extra, 'name', 'Unknown')
                    target_type = "role" if hasattr(entry.extra, 'type') and entry.extra.type == discord.Role else "member"
                    await self.bot.mod_tracker.log_permission_overwrite(
                        mod_id=mod_id, channel=entry.target, target=target_name,
                        target_type=target_type, action="added",
                    )

            elif entry.action == discord.AuditLogAction.overwrite_update:
                if entry.target and entry.extra:
                    target_name = getattr(entry.extra, 'name', 'Unknown')
                    target_type = "role" if hasattr(entry.extra, 'type') and entry.extra.type == discord.Role else "member"
                    await self.bot.mod_tracker.log_permission_overwrite(
                        mod_id=mod_id, channel=entry.target, target=target_name,
                        target_type=target_type, action="updated",
                    )

            elif entry.action == discord.AuditLogAction.overwrite_delete:
                if entry.target and entry.extra:
                    target_name = getattr(entry.extra, 'name', 'Unknown')
                    target_type = "role" if hasattr(entry.extra, 'type') and entry.extra.type == discord.Role else "member"
                    await self.bot.mod_tracker.log_permission_overwrite(
                        mod_id=mod_id, channel=entry.target, target=target_name,
                        target_type=target_type, action="removed",
                    )

            # Sticker create/delete
            elif entry.action == discord.AuditLogAction.sticker_create:
                sticker_name = getattr(entry.target, 'name', 'Unknown')
                await self.bot.mod_tracker.log_sticker_create(mod_id=mod_id, sticker_name=sticker_name)

            elif entry.action == discord.AuditLogAction.sticker_delete:
                sticker_name = getattr(entry.before, 'name', 'Unknown')
                await self.bot.mod_tracker.log_sticker_delete(mod_id=mod_id, sticker_name=sticker_name)

            # Scheduled events
            elif entry.action == discord.AuditLogAction.scheduled_event_create:
                event_name = getattr(entry.target, 'name', 'Unknown')
                event_type = str(getattr(entry.target, 'entity_type', 'Unknown'))
                await self.bot.mod_tracker.log_event_create(
                    mod_id=mod_id, event_name=event_name, event_type=event_type,
                )

            elif entry.action == discord.AuditLogAction.scheduled_event_update:
                event_name = getattr(entry.target, 'name', 'Unknown')
                await self.bot.mod_tracker.log_event_update(mod_id=mod_id, event_name=event_name)

            elif entry.action == discord.AuditLogAction.scheduled_event_delete:
                event_name = getattr(entry.before, 'name', 'Unknown')
                await self.bot.mod_tracker.log_event_delete(mod_id=mod_id, event_name=event_name)

            # Stage instance
            elif entry.action == discord.AuditLogAction.stage_instance_create:
                if entry.target and hasattr(entry.target, 'channel'):
                    topic = getattr(entry.target, 'topic', None)
                    await self.bot.mod_tracker.log_stage_topic_change(
                        mod_id=mod_id, stage_channel=entry.target.channel,
                        old_topic=None, new_topic=topic,
                    )

            elif entry.action == discord.AuditLogAction.stage_instance_update:
                if entry.target and hasattr(entry.target, 'channel'):
                    old_topic = getattr(entry.before, 'topic', None) if entry.before else None
                    new_topic = getattr(entry.after, 'topic', None) if entry.after else None
                    if old_topic != new_topic:
                        await self.bot.mod_tracker.log_stage_topic_change(
                            mod_id=mod_id, stage_channel=entry.target.channel,
                            old_topic=old_topic, new_topic=new_topic,
                        )

            # Integration create/delete
            elif entry.action == discord.AuditLogAction.integration_create:
                integration_name = getattr(entry.target, 'name', 'Unknown')
                integration_type = getattr(entry.target, 'type', 'Unknown')
                await self.bot.mod_tracker.log_integration_create(
                    mod_id=mod_id, integration_name=integration_name,
                    integration_type=str(integration_type),
                )

            elif entry.action == discord.AuditLogAction.integration_delete:
                integration_name = getattr(entry.before, 'name', 'Unknown')
                await self.bot.mod_tracker.log_integration_delete(
                    mod_id=mod_id, integration_name=integration_name,
                )

            # Bot add
            elif entry.action == discord.AuditLogAction.bot_add:
                if entry.target and entry.target.bot:
                    await self.bot.mod_tracker.log_bot_add(mod_id=mod_id, bot=entry.target)

            # Member prune
            elif entry.action == discord.AuditLogAction.member_prune:
                days = getattr(entry.extra, 'delete_member_days', 0)
                members_removed = getattr(entry.extra, 'members_removed', 0)
                await self.bot.mod_tracker.log_member_prune(
                    mod_id=mod_id, days=days, members_removed=members_removed,
                )

            # Soundboard
            elif entry.action == discord.AuditLogAction.soundboard_sound_create:
                sound_name = getattr(entry.target, 'name', 'Unknown')
                await self.bot.mod_tracker.log_soundboard_create(mod_id=mod_id, sound_name=sound_name)

            elif entry.action == discord.AuditLogAction.soundboard_sound_delete:
                sound_name = getattr(entry.before, 'name', 'Unknown')
                await self.bot.mod_tracker.log_soundboard_delete(mod_id=mod_id, sound_name=sound_name)

            elif entry.action == discord.AuditLogAction.soundboard_sound_update:
                sound_name = getattr(entry.target, 'name', 'Unknown')
                changes = []
                if hasattr(entry.before, 'name') and hasattr(entry.after, 'name'):
                    if entry.before.name != entry.after.name:
                        changes.append(f"Name: {entry.before.name} → {entry.after.name}")
                if hasattr(entry.before, 'volume') and hasattr(entry.after, 'volume'):
                    if entry.before.volume != entry.after.volume:
                        changes.append(f"Volume: {entry.before.volume} → {entry.after.volume}")
                await self.bot.mod_tracker.log_soundboard_update(
                    mod_id=mod_id, sound_name=sound_name,
                    changes=", ".join(changes) if changes else "Settings changed",
                )

            # Onboarding
            elif entry.action == discord.AuditLogAction.onboarding_create:
                await self.bot.mod_tracker.log_onboarding_create(mod_id=mod_id)

            elif entry.action == discord.AuditLogAction.onboarding_update:
                changes = []
                if hasattr(entry.before, 'enabled') and hasattr(entry.after, 'enabled'):
                    if entry.before.enabled != entry.after.enabled:
                        changes.append(f"Enabled: {entry.after.enabled}")
                if hasattr(entry.before, 'prompts') and hasattr(entry.after, 'prompts'):
                    old_count = len(entry.before.prompts) if entry.before.prompts else 0
                    new_count = len(entry.after.prompts) if entry.after.prompts else 0
                    if old_count != new_count:
                        changes.append(f"Prompts: {old_count} → {new_count}")
                await self.bot.mod_tracker.log_onboarding_update(
                    mod_id=mod_id,
                    changes=", ".join(changes) if changes else "Settings changed",
                )

        except Exception as e:
            logger.warning("Mod Tracker: Audit Log Event Failed", [
                ("Action", str(entry.action)),
                ("Error", str(e)[:50]),
            ])

    # =========================================================================
    # Logging Service Routing
    # =========================================================================

    async def _log_audit_event(self, entry: discord.AuditLogEntry) -> None:
        """Route audit log events to the logging service."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        # Skip actions taken by ignored bots (from config)
        if self.config.ignored_bot_ids and entry.user_id in self.config.ignored_bot_ids:
            return

        try:
            moderator = None
            if entry.user_id:
                guild = entry.guild
                if guild:
                    moderator = guild.get_member(entry.user_id)

            # Bans & Kicks
            # Note: log_ban and log_unban are now handled by on_member_ban/on_member_unban
            # in members.py for faster real-time detection (direct events vs audit polling)

            if entry.action == discord.AuditLogAction.kick:
                if entry.target and not entry.target.bot:
                    await self.bot.logging_service.log_kick(
                        entry.target, moderator=moderator, reason=entry.reason,
                    )

            # Mutes & Timeouts
            elif entry.action == discord.AuditLogAction.member_update:
                if hasattr(entry.after, 'timed_out_until') and entry.after.timed_out_until:
                    if entry.target and isinstance(entry.target, discord.Member):
                        await self.bot.logging_service.log_timeout(
                            entry.target, until=entry.after.timed_out_until,
                            moderator=moderator, reason=entry.reason,
                        )
                        # Log to case log
                        if self.bot.case_log_service:
                            await self.bot.case_log_service.log_timeout(
                                user=entry.target,
                                moderator_id=moderator.id if moderator else entry.user_id,
                                until=entry.after.timed_out_until,
                                reason=entry.reason,
                            )

                old_timeout = getattr(entry.before, 'timed_out_until', None)
                new_timeout = getattr(entry.after, 'timed_out_until', None)
                if old_timeout and not new_timeout:
                    if entry.target and isinstance(entry.target, discord.Member):
                        await self.bot.logging_service.log_timeout_remove(
                            entry.target, moderator=moderator,
                        )

                if entry.target and isinstance(entry.target, discord.Member):
                    if hasattr(entry.before, 'mute') and hasattr(entry.after, 'mute'):
                        if entry.before.mute != entry.after.mute:
                            await self.bot.logging_service.log_server_voice_mute(
                                member=entry.target, muted=entry.after.mute, moderator=moderator,
                            )

                    if hasattr(entry.before, 'deaf') and hasattr(entry.after, 'deaf'):
                        if entry.before.deaf != entry.after.deaf:
                            await self.bot.logging_service.log_server_voice_deafen(
                                member=entry.target, deafened=entry.after.deaf, moderator=moderator,
                            )

                    if hasattr(entry.before, 'nick') and hasattr(entry.after, 'nick'):
                        if entry.before.nick != entry.after.nick:
                            if moderator and entry.target and moderator.id != entry.target.id:
                                await self.bot.logging_service.log_nickname_force_change(
                                    target=entry.target, old_nick=entry.before.nick,
                                    new_nick=entry.after.nick, moderator=moderator,
                                )
                                self.bot.db.save_nickname_change(
                                    user_id=entry.target.id, guild_id=entry.guild.id,
                                    old_nickname=entry.before.nick, new_nickname=entry.after.nick,
                                    changed_by=moderator.id,
                                )

            # Voice disconnect
            elif entry.action == discord.AuditLogAction.member_disconnect:
                if entry.extra and hasattr(entry.extra, 'count'):
                    channel_name = "Unknown"
                    if hasattr(entry.extra, 'channel') and entry.extra.channel:
                        channel_name = entry.extra.channel.name

                    if entry.extra.count == 1 and entry.target:
                        if isinstance(entry.target, discord.Member):
                            await self.bot.logging_service.log_voice_disconnect(
                                target=entry.target, channel_name=channel_name, moderator=moderator,
                            )

            # Mod message delete
            elif entry.action == discord.AuditLogAction.message_delete:
                if entry.target and entry.extra:
                    if moderator and entry.target.id != moderator.id:
                        channel_id = getattr(entry.extra, 'channel', None)
                        if channel_id:
                            channel = entry.guild.get_channel(channel_id.id) if hasattr(channel_id, 'id') else entry.guild.get_channel(channel_id)
                        else:
                            channel = None

                        message_data = None
                        if hasattr(entry.extra, 'message_id'):
                            message_data = self.bot._message_cache.pop(entry.extra.message_id, None)

                        attachments = None
                        if hasattr(entry.extra, 'message_id'):
                            attachments = self.bot._attachment_cache.pop(entry.extra.message_id, None)

                        if channel:
                            await self.bot.logging_service.log_mod_message_delete(
                                author=entry.target, channel=channel,
                                content=message_data.get('content') if message_data else None,
                                moderator=moderator, attachments=attachments,
                                attachment_names=message_data.get('attachment_names') if message_data else None,
                                sticker_names=message_data.get('sticker_names') if message_data else None,
                                has_embeds=message_data.get('has_embeds') if message_data else False,
                                embed_titles=message_data.get('embed_titles') if message_data else None,
                            )

            # Bulk delete
            elif entry.action == discord.AuditLogAction.message_bulk_delete:
                if entry.target:
                    count = getattr(entry.extra, 'count', 0) if entry.extra else 0
                    await self.bot.logging_service.log_bulk_delete(
                        entry.target, count=count, moderator=moderator,
                    )

            # Permission overwrites
            elif entry.action == discord.AuditLogAction.overwrite_create:
                if entry.target and entry.extra:
                    target_name = getattr(entry.extra, 'name', 'Unknown')
                    await self.bot.logging_service.log_permission_update(
                        entry.target, target=target_name, action="added", moderator=moderator,
                    )

            elif entry.action == discord.AuditLogAction.overwrite_update:
                if entry.target and entry.extra:
                    target_name = getattr(entry.extra, 'name', 'Unknown')
                    await self.bot.logging_service.log_permission_update(
                        entry.target, target=target_name, action="updated", moderator=moderator,
                    )

            elif entry.action == discord.AuditLogAction.overwrite_delete:
                if entry.target and entry.extra:
                    target_name = getattr(entry.extra, 'name', 'Unknown')
                    await self.bot.logging_service.log_permission_update(
                        entry.target, target=target_name, action="removed", moderator=moderator,
                    )

            # Channel update
            elif entry.action == discord.AuditLogAction.channel_update:
                if entry.target:
                    changes = []
                    if hasattr(entry.before, 'name') and hasattr(entry.after, 'name'):
                        if entry.before.name != entry.after.name:
                            changes.append(f"Name: {entry.before.name} → {entry.after.name}")
                    if hasattr(entry.before, 'topic') and hasattr(entry.after, 'topic'):
                        if entry.before.topic != entry.after.topic:
                            changes.append("Topic changed")

                    if hasattr(entry.before, 'slowmode_delay') and hasattr(entry.after, 'slowmode_delay'):
                        if entry.before.slowmode_delay != entry.after.slowmode_delay:
                            changes.append(f"Slowmode: {entry.before.slowmode_delay}s → {entry.after.slowmode_delay}s")
                            await self.bot.logging_service.log_slowmode_change(
                                channel=entry.target, old_delay=entry.before.slowmode_delay,
                                new_delay=entry.after.slowmode_delay, moderator=moderator,
                            )

                    if hasattr(entry.before, 'category') and hasattr(entry.after, 'category'):
                        old_cat = entry.before.category
                        new_cat = entry.after.category
                        if old_cat != new_cat:
                            old_name = old_cat.name if old_cat else None
                            new_name = new_cat.name if new_cat else None
                            await self.bot.logging_service.log_channel_category_move(
                                channel=entry.target, old_category=old_name,
                                new_category=new_name, moderator=moderator,
                            )

                    if isinstance(entry.target, discord.ForumChannel):
                        if hasattr(entry.before, 'available_tags') and hasattr(entry.after, 'available_tags'):
                            old_tags = {t.name: t for t in (entry.before.available_tags or [])}
                            new_tags = {t.name: t for t in (entry.after.available_tags or [])}

                            for tag_name in new_tags:
                                if tag_name not in old_tags:
                                    await self.bot.logging_service.log_forum_tag_create(
                                        forum=entry.target, tag_name=tag_name, moderator=moderator,
                                    )

                            for tag_name in old_tags:
                                if tag_name not in new_tags:
                                    await self.bot.logging_service.log_forum_tag_delete(
                                        forum=entry.target, tag_name=tag_name, moderator=moderator,
                                    )

                    if changes:
                        await self.bot.logging_service.log_channel_update(
                            entry.target, changes=", ".join(changes), moderator=moderator,
                        )

            # Role update
            elif entry.action == discord.AuditLogAction.role_update:
                if entry.target:
                    changes = []
                    if hasattr(entry.before, 'name') and hasattr(entry.after, 'name'):
                        if entry.before.name != entry.after.name:
                            changes.append(f"Name: {entry.before.name} → {entry.after.name}")
                    if hasattr(entry.before, 'permissions') and hasattr(entry.after, 'permissions'):
                        if entry.before.permissions != entry.after.permissions:
                            changes.append("Permissions changed")
                    if hasattr(entry.before, 'color') and hasattr(entry.after, 'color'):
                        if entry.before.color != entry.after.color:
                            changes.append("Color changed")

                    if hasattr(entry.before, 'position') and hasattr(entry.after, 'position'):
                        if entry.before.position != entry.after.position:
                            await self.bot.logging_service.log_role_position_change(
                                role=entry.target, old_position=entry.before.position,
                                new_position=entry.after.position, moderator=moderator,
                            )

                    if changes:
                        await self.bot.logging_service.log_role_update(
                            entry.target, changes=", ".join(changes), moderator=moderator,
                        )

            # Server settings
            elif entry.action == discord.AuditLogAction.guild_update:
                changes = []
                if hasattr(entry.before, 'name') and hasattr(entry.after, 'name'):
                    if entry.before.name != entry.after.name:
                        changes.append(f"Name: {entry.before.name} → {entry.after.name}")

                if hasattr(entry.before, 'icon') and hasattr(entry.after, 'icon'):
                    if entry.before.icon != entry.after.icon:
                        old_icon = None
                        new_icon = None
                        if entry.before.icon:
                            old_icon = f"https://cdn.discordapp.com/icons/{entry.guild.id}/{entry.before.icon}.png?size=256"
                        if entry.after.icon:
                            new_icon = f"https://cdn.discordapp.com/icons/{entry.guild.id}/{entry.after.icon}.png?size=256"
                        await self.bot.logging_service.log_server_icon_change(
                            guild=entry.guild, old_icon_url=old_icon,
                            new_icon_url=new_icon, moderator=moderator,
                        )

                if hasattr(entry.before, 'banner') and hasattr(entry.after, 'banner'):
                    if entry.before.banner != entry.after.banner:
                        old_banner = None
                        new_banner = None
                        if entry.before.banner:
                            old_banner = f"https://cdn.discordapp.com/banners/{entry.guild.id}/{entry.before.banner}.png?size=512"
                        if entry.after.banner:
                            new_banner = f"https://cdn.discordapp.com/banners/{entry.guild.id}/{entry.after.banner}.png?size=512"
                        await self.bot.logging_service.log_server_banner_change(
                            guild=entry.guild, old_banner_url=old_banner,
                            new_banner_url=new_banner, moderator=moderator,
                        )

                if hasattr(entry.before, 'verification_level') and hasattr(entry.after, 'verification_level'):
                    if entry.before.verification_level != entry.after.verification_level:
                        changes.append(f"Verification: {entry.after.verification_level}")
                if hasattr(entry.before, 'explicit_content_filter') and hasattr(entry.after, 'explicit_content_filter'):
                    if entry.before.explicit_content_filter != entry.after.explicit_content_filter:
                        changes.append(f"Content Filter: {entry.after.explicit_content_filter}")
                if changes:
                    await self.bot.logging_service.log_server_update(
                        changes=", ".join(changes), moderator=moderator,
                    )

            # Bots & Integrations
            elif entry.action == discord.AuditLogAction.bot_add:
                if entry.target and entry.target.bot:
                    await self.bot.logging_service.log_bot_add(entry.target, moderator=moderator)

            elif entry.action == discord.AuditLogAction.integration_create:
                name = getattr(entry.target, 'name', 'Unknown')
                int_type = str(getattr(entry.target, 'type', 'Unknown'))
                await self.bot.logging_service.log_integration_add(
                    name=name, int_type=int_type, moderator=moderator,
                )

            elif entry.action == discord.AuditLogAction.integration_delete:
                name = getattr(entry.before, 'name', 'Unknown')
                await self.bot.logging_service.log_integration_remove(name=name, moderator=moderator)

            # Webhooks
            elif entry.action == discord.AuditLogAction.webhook_create:
                webhook_name = getattr(entry.target, 'name', 'Unknown')
                channel = entry.target.channel if hasattr(entry.target, 'channel') else None
                if channel:
                    await self.bot.logging_service.log_webhook_create(
                        webhook_name=webhook_name, channel=channel, moderator=moderator,
                    )

            elif entry.action == discord.AuditLogAction.webhook_delete:
                webhook_name = getattr(entry.before, 'name', 'Unknown')
                channel_name = "Unknown"
                if hasattr(entry.before, 'channel') and entry.before.channel:
                    channel_name = entry.before.channel.name
                await self.bot.logging_service.log_webhook_delete(
                    webhook_name=webhook_name, channel_name=channel_name, moderator=moderator,
                )

            # Message pin/unpin
            elif entry.action == discord.AuditLogAction.message_pin:
                if entry.extra and hasattr(entry.extra, 'channel'):
                    channel = entry.extra.channel
                    message_id = entry.extra.message_id if hasattr(entry.extra, 'message_id') else None
                    try:
                        message = await channel.fetch_message(message_id)
                        await self.bot.logging_service.log_message_pin(
                            message=message, pinned=True, moderator=moderator,
                        )
                    except Exception:
                        # Fallback when message can't be fetched
                        await self.bot.logging_service.log_message_pin(
                            pinned=True, moderator=moderator, channel=channel, message_id=message_id,
                        )

            elif entry.action == discord.AuditLogAction.message_unpin:
                if entry.extra and hasattr(entry.extra, 'channel'):
                    channel = entry.extra.channel
                    message_id = entry.extra.message_id if hasattr(entry.extra, 'message_id') else None
                    try:
                        message = await channel.fetch_message(message_id)
                        await self.bot.logging_service.log_message_pin(
                            message=message, pinned=False, moderator=moderator,
                        )
                    except Exception:
                        # Fallback when message can't be fetched (deleted message)
                        await self.bot.logging_service.log_message_pin(
                            pinned=False, moderator=moderator, channel=channel, message_id=message_id,
                        )

        except Exception as e:
            logger.debug(f"Logging Service: Audit event failed: {e}")


async def setup(bot: "AzabBot") -> None:
    """Add the audit log events cog to the bot."""
    await bot.add_cog(AuditLogEvents(bot))
    logger.debug("Audit Log Events Loaded")
