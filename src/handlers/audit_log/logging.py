"""
AzabBot - Logging Service Mixin
===============================

Routes audit log events to logging service.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from typing import TYPE_CHECKING

import discord

from src.core.logger import logger
from src.core.constants import CASE_LOG_TIMEOUT

if TYPE_CHECKING:
    from .cog import AuditLogEvents


class LoggingMixin:
    """Mixin for logging service routing."""

    async def _log_audit_event(self: "AuditLogEvents", entry: discord.AuditLogEntry) -> None:
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
                await self._log_member_update(entry, moderator)

            # Voice disconnect
            elif entry.action == discord.AuditLogAction.member_disconnect:
                if entry.extra and hasattr(entry.extra, 'count'):
                    channel_name = "Unknown"
                    channel_id = None
                    if hasattr(entry.extra, 'channel') and entry.extra.channel:
                        channel_name = entry.extra.channel.name
                        channel_id = entry.extra.channel.id

                    if entry.extra.count == 1 and entry.target:
                        if isinstance(entry.target, discord.Member):
                            await self.bot.logging_service.log_voice_disconnect(
                                target=entry.target, channel_name=channel_name,
                                moderator=moderator, channel_id=channel_id,
                            )

            # Mod message delete
            elif entry.action == discord.AuditLogAction.message_delete:
                await self._log_message_delete(entry, moderator)

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
                await self._log_channel_update(entry, moderator)

            # Role update
            elif entry.action == discord.AuditLogAction.role_update:
                await self._log_role_update(entry, moderator)

            # Server settings
            elif entry.action == discord.AuditLogAction.guild_update:
                await self._log_guild_update(entry, moderator)

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
                channel_id = None
                if hasattr(entry.before, 'channel') and entry.before.channel:
                    channel_name = entry.before.channel.name
                    channel_id = entry.before.channel.id
                await self.bot.logging_service.log_webhook_delete(
                    webhook_name=webhook_name, channel_name=channel_name,
                    moderator=moderator, channel_id=channel_id,
                )

            # Message pin/unpin
            elif entry.action == discord.AuditLogAction.message_pin:
                await self._log_message_pin(entry, moderator, pinned=True)

            elif entry.action == discord.AuditLogAction.message_unpin:
                await self._log_message_pin(entry, moderator, pinned=False)

        except Exception as e:
            logger.debug(f"Logging Service: Audit event failed: {e}")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def _log_member_update(
        self: "AuditLogEvents", entry: discord.AuditLogEntry, moderator: discord.Member | None
    ) -> None:
        """Log member update events to logging service."""
        if hasattr(entry.after, 'timed_out_until') and entry.after.timed_out_until:
            if entry.target and isinstance(entry.target, discord.Member):
                await self.bot.logging_service.log_timeout(
                    entry.target, until=entry.after.timed_out_until,
                    moderator=moderator, reason=entry.reason,
                )
                # Log to case log
                if self.bot.case_log_service:
                    try:
                        await asyncio.wait_for(
                            self.bot.case_log_service.log_timeout(
                                user=entry.target,
                                moderator_id=moderator.id if moderator else entry.user_id,
                                until=entry.after.timed_out_until,
                                reason=entry.reason,
                            ),
                            timeout=CASE_LOG_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Case Log Timeout", [
                            ("Action", "Timeout"),
                            ("User", entry.target.name if hasattr(entry.target, 'name') else str(entry.target)),
                            ("ID", str(entry.target.id)),
                        ])
                    except Exception as e:
                        logger.error("Case Log Failed", [
                            ("Action", "Timeout"),
                            ("User", entry.target.name if hasattr(entry.target, 'name') else str(entry.target)),
                            ("ID", str(entry.target.id)),
                            ("Error", str(e)[:100]),
                        ])

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

    async def _log_message_delete(
        self: "AuditLogEvents", entry: discord.AuditLogEntry, moderator: discord.Member | None
    ) -> None:
        """Log moderator message delete events."""
        if not entry.target or not entry.extra:
            return

        if not moderator or entry.target.id == moderator.id:
            return

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

    async def _log_channel_update(
        self: "AuditLogEvents", entry: discord.AuditLogEntry, moderator: discord.Member | None
    ) -> None:
        """Log channel update events to logging service."""
        if not entry.target:
            return

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

    async def _log_role_update(
        self: "AuditLogEvents", entry: discord.AuditLogEntry, moderator: discord.Member | None
    ) -> None:
        """Log role update events to logging service."""
        if not entry.target:
            return

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

    async def _log_guild_update(
        self: "AuditLogEvents", entry: discord.AuditLogEntry, moderator: discord.Member | None
    ) -> None:
        """Log guild update events to logging service."""
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

    async def _log_message_pin(
        self: "AuditLogEvents", entry: discord.AuditLogEntry, moderator: discord.Member | None, pinned: bool
    ) -> None:
        """Log message pin/unpin events to logging service."""
        if not entry.extra or not hasattr(entry.extra, 'channel'):
            return

        channel = entry.extra.channel
        message_id = entry.extra.message_id if hasattr(entry.extra, 'message_id') else None
        try:
            message = await channel.fetch_message(message_id)
            await self.bot.logging_service.log_message_pin(
                message=message, pinned=pinned, moderator=moderator,
            )
        except Exception:
            # Fallback when message can't be fetched
            await self.bot.logging_service.log_message_pin(
                pinned=pinned, moderator=moderator, channel=channel, message_id=message_id,
            )


__all__ = ["LoggingMixin"]
