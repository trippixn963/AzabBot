"""
AzabBot - Anti-Spam Punishment Handlers
=======================================

Handlers for spam detection results - warnings, mutes, and logging.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

import discord

from src.core.config import EmbedColors, NY_TZ
from src.core.constants import CASE_LOG_TIMEOUT
from src.core.logger import logger
from src.utils.footer import set_footer
from src.views import CASE_EMOJI

from .constants import (
    MUTE_DURATIONS,
    REP_LOSS_MUTE,
    REP_LOSS_WARNING,
    SPAM_DISPLAY_NAMES,
    STICKER_SPAM_TIME_WINDOW,
)

if TYPE_CHECKING:
    from src.bot import AzabBot
    from src.core.config import Config
    from src.core.database import Database


class SpamHandlerMixin:
    """Mixin class providing spam punishment handling."""

    async def handle_spam(
        self,
        message: discord.Message,
        spam_type: str,
    ) -> None:
        """Handle a detected spam message."""
        if not message.guild or not isinstance(message.author, discord.Member):
            return

        guild_id = message.guild.id
        user_id = message.author.id
        db: "Database" = self.db  # type: ignore

        # Special handling for sticker spam
        if spam_type == "sticker_spam":
            await self._handle_sticker_spam(message)
            return

        # Add violation to database
        violation_count = db.add_spam_violation(user_id, guild_id, spam_type)

        # Reduce reputation
        self.update_reputation(user_id, guild_id, -REP_LOSS_WARNING)  # type: ignore

        # Delete the spam message
        try:
            await message.delete()
        except discord.HTTPException:
            logger.tree("Spam Message Delete Failed", [
                ("User", str(message.author)),
                ("Channel", f"#{message.channel.name}" if hasattr(message.channel, 'name') else "Unknown"),
                ("Reason", "Message already deleted or no permission"),
            ], emoji="⚠️")

        # Determine punishment
        mute_level = min(violation_count, 5)
        mute_duration = MUTE_DURATIONS.get(mute_level, 86400)

        spam_display = SPAM_DISPLAY_NAMES.get(spam_type, spam_type)

        if mute_duration == 0:
            await self._send_warning(message.author, spam_display, message.channel)
            await self._log_spam(message, spam_type, "warning", violation_count)
        else:
            self.update_reputation(user_id, guild_id, -REP_LOSS_MUTE)  # type: ignore
            await self._apply_mute(
                message.author,
                mute_duration,
                spam_display,
                message.channel,
                violation_count,
            )
            await self._log_spam(message, spam_type, "mute", violation_count, mute_duration)

    async def _handle_sticker_spam(self, message: discord.Message) -> None:
        """
        Handle sticker spam with custom punishment:
        - First offense: Warning + delete messages
        - Second+ offense: Mute for 10 minutes
        """
        if not message.guild or not isinstance(message.author, discord.Member):
            return

        guild_id = message.guild.id
        user_id = message.author.id
        member = message.author
        now = datetime.now(NY_TZ)
        db: "Database" = self.db  # type: ignore
        config: "Config" = self.config  # type: ignore

        # Add violation (tracks separately as "sticker_spam")
        violation_count = db.add_spam_violation(user_id, guild_id, "sticker_spam")

        # Count recent sticker messages
        state = self._user_states[guild_id][user_id]  # type: ignore
        deleted_count = 0
        for record in state.messages:
            if record.has_stickers and (now - record.timestamp).total_seconds() < STICKER_SPAM_TIME_WINDOW:
                deleted_count += 1

        # Delete the current message
        try:
            await message.delete()
        except discord.HTTPException:
            logger.tree("Sticker Spam Message Delete Failed", [
                ("User", str(message.author)),
                ("Channel", f"#{message.channel.name}" if hasattr(message.channel, 'name') else "Unknown"),
                ("Reason", "Message already deleted or no permission"),
            ], emoji="⚠️")

        # Reduce reputation
        self.update_reputation(user_id, guild_id, -REP_LOSS_WARNING)  # type: ignore

        if violation_count == 1:
            # First offense: Warning only
            await self._send_warning(member, "Sticker Spam", message.channel)
            logger.tree("STICKER SPAM WARNING", [
                ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                ("User ID", str(member.id)),
                ("Action", "Warning issued"),
                ("Stickers Deleted", str(deleted_count)),
                ("Channel", f"#{message.channel.name}" if hasattr(message.channel, 'name') else "Unknown"),
            ], emoji="⚠️")

            # Log to server logs
            await self._log_sticker_spam_warning(member, deleted_count, message.channel, now)
        else:
            # Second+ offense: Mute for 10 minutes
            await self._apply_sticker_spam_mute(member, message, violation_count, now, config)

    async def _log_sticker_spam_warning(
        self,
        member: discord.Member,
        deleted_count: int,
        channel: discord.abc.Messageable,
        now: datetime,
    ) -> None:
        """Log sticker spam warning to server logs."""
        bot: "AzabBot" = self.bot  # type: ignore
        if bot.logging_service and bot.logging_service.enabled:
            try:
                embed = discord.Embed(
                    title="⚠️ Sticker Spam",
                    color=EmbedColors.WARNING,
                    timestamp=now,
                )
                embed.add_field(name="User", value=f"{member.mention}", inline=True)
                embed.add_field(name="Stickers Deleted", value=str(deleted_count), inline=True)
                embed.add_field(name="Channel", value=f"<#{channel.id}>", inline=True)

                await bot.logging_service._send_log(
                    bot.logging_service.LogCategory.MOD_ACTIONS,
                    embed,
                )
            except Exception as e:
                logger.debug(f"Failed to log sticker spam warning: {e}")

    async def _apply_sticker_spam_mute(
        self,
        member: discord.Member,
        message: discord.Message,
        violation_count: int,
        now: datetime,
        config: "Config",
    ) -> None:
        """Apply 10-minute mute for sticker spam."""
        mute_duration = 600  # 10 minutes
        bot: "AzabBot" = self.bot  # type: ignore
        db: "Database" = self.db  # type: ignore

        if not config.muted_role_id:
            logger.warning("Sticker Spam Mute Failed", [
                ("Reason", "Muted role not configured"),
            ])
            return

        mute_role = message.guild.get_role(config.muted_role_id)
        if not mute_role:
            logger.warning("Sticker Spam Mute Failed", [
                ("Reason", "Muted role not found"),
            ])
            return

        try:
            await member.add_roles(
                mute_role,
                reason=f"Sticker spam (violation #{violation_count})",
            )

            expires_at = now + timedelta(seconds=mute_duration)
            db.add_mute(
                user_id=member.id,
                guild_id=message.guild.id,
                expires_at=expires_at.timestamp(),
                reason="Auto-spam: Sticker Spam",
            )

            # Open case
            case_info = await self._open_spam_case(member, "Sticker Spam", mute_duration, violation_count)

            embed = discord.Embed(
                title="🔇 Sticker Spam",
                description=f"{member.mention} has been muted.",
                color=EmbedColors.WARNING,
            )
            embed.add_field(name="Duration", value="10 minutes", inline=True)
            embed.add_field(name="Violation", value=f"#{violation_count}", inline=True)
            set_footer(embed)

            view = None
            if case_info and case_info.get("thread_id"):
                case_url = f"https://discord.com/channels/{message.guild.id}/{case_info['thread_id']}"
                view = discord.ui.View(timeout=None)
                view.add_item(discord.ui.Button(
                    label="Case",
                    url=case_url,
                    style=discord.ButtonStyle.link,
                    emoji=CASE_EMOJI,
                ))

            await message.channel.send(embed=embed, view=view, delete_after=15)

            # DM the user about the mute
            dm_sent = False
            try:
                dm_embed = discord.Embed(
                    title=f"🔇 You've been muted in {member.guild.name}",
                    color=EmbedColors.WARNING,
                )
                dm_embed.add_field(name="Reason", value="Sticker Spam", inline=True)
                dm_embed.add_field(name="Duration", value="10 minutes", inline=True)
                dm_embed.add_field(name="Violation", value=f"#{violation_count}", inline=True)
                dm_embed.set_footer(text="This was an automatic action by the anti-spam system.")
                await member.send(embed=dm_embed)
                dm_sent = True
            except discord.Forbidden:
                logger.debug(f"Sticker spam mute DM failed for {member.id}: DMs disabled")
            except discord.HTTPException as e:
                logger.debug(f"Sticker spam mute DM failed for {member.id}: {e}")

            logger.tree("STICKER SPAM MUTE", [
                ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                ("User ID", str(member.id)),
                ("Duration", "10 minutes"),
                ("Violation", f"#{violation_count}"),
                ("Channel", f"#{message.channel.name}" if hasattr(message.channel, 'name') else "Unknown"),
                ("DM Sent", "Yes" if dm_sent else "No (DMs disabled)"),
            ], emoji="🔇")

            # Log to server logs
            if bot.logging_service and bot.logging_service.enabled:
                try:
                    log_embed = discord.Embed(
                        title="🔇 Auto-Spam Mute (Sticker Spam)",
                        color=EmbedColors.WARNING,
                        timestamp=now,
                    )
                    log_embed.add_field(name="User", value=f"{member.mention}", inline=True)
                    log_embed.add_field(name="Duration", value="10 minutes", inline=True)
                    log_embed.add_field(name="Violations", value=f"#{violation_count}", inline=True)

                    await bot.logging_service._send_log(
                        bot.logging_service.LogCategory.MOD_ACTIONS,
                        log_embed,
                    )
                except Exception as e:
                    logger.debug(f"Failed to log sticker spam mute: {e}")

        except discord.Forbidden:
            logger.warning("Sticker Spam Mute Permission Denied", [
                ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                ("User ID", str(member.id)),
            ])
        except discord.HTTPException as e:
            logger.warning("Sticker Spam Mute Failed", [
                ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                ("User ID", str(member.id)),
                ("Error", str(e)[:50]),
            ])

    async def handle_webhook_spam(self, message: discord.Message) -> None:
        """Handle spam from a webhook."""
        bot: "AzabBot" = self.bot  # type: ignore

        try:
            await message.delete()
        except discord.HTTPException:
            logger.tree("Webhook Spam Message Delete Failed", [
                ("Webhook ID", str(message.webhook_id)),
                ("Channel", f"#{message.channel.name}" if hasattr(message.channel, 'name') else "Unknown"),
                ("Reason", "Message already deleted or no permission"),
            ], emoji="⚠️")

        logger.tree("WEBHOOK SPAM DETECTED", [
            ("Webhook ID", str(message.webhook_id)),
            ("Channel", f"#{message.channel.name}" if hasattr(message.channel, 'name') else "Unknown"),
            ("Action", "Message deleted"),
        ], emoji="🛡️")

        if bot.logging_service and bot.logging_service.enabled:
            try:
                embed = discord.Embed(
                    title="🛡️ Webhook Spam Detected",
                    color=EmbedColors.WARNING,
                    timestamp=datetime.now(NY_TZ),
                )
                embed.add_field(name="Webhook ID", value=str(message.webhook_id), inline=True)
                embed.add_field(
                    name="Channel",
                    value=f"<#{message.channel.id}>",
                    inline=True
                )
                embed.add_field(name="Action", value="Message deleted", inline=True)

                await bot.logging_service._send_log(
                    bot.logging_service.LogCategory.ALERTS,
                    embed,
                )
            except Exception as e:
                logger.debug(f"Failed to log webhook spam: {e}")

    async def _send_warning(
        self,
        member: discord.Member,
        spam_type: str,
        channel: discord.abc.Messageable,
    ) -> None:
        """Send a warning embed to the user."""
        try:
            embed = discord.Embed(
                title=f"⚠️ {spam_type}",
                description=f"{member.mention}, your message was deleted.",
                color=EmbedColors.WARNING,
            )
            embed.add_field(name="Action", value="Warning", inline=True)
            set_footer(embed)

            await channel.send(embed=embed, delete_after=10)

            logger.tree("SPAM WARNING SENT", [
                ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                ("User ID", str(member.id)),
                ("Type", spam_type),
                ("Channel", f"#{channel.name}" if hasattr(channel, 'name') else "Unknown"),
            ], emoji="⚠️")
        except discord.HTTPException as e:
            logger.warning("Spam Warning Failed", [
                ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                ("User ID", str(member.id)),
                ("Type", spam_type),
                ("Error", str(e)[:50]),
            ])

    async def _apply_mute(
        self,
        member: discord.Member,
        duration: int,
        spam_type: str,
        channel: discord.abc.Messageable,
        violation_count: int,
    ) -> None:
        """Apply mute role to the user."""
        config: "Config" = self.config  # type: ignore
        db: "Database" = self.db  # type: ignore

        if not config.muted_role_id:
            return

        mute_role = member.guild.get_role(config.muted_role_id)
        if not mute_role:
            return

        try:
            await member.add_roles(
                mute_role,
                reason=f"Anti-spam: {spam_type} (violation #{violation_count})",
            )

            if duration >= 3600:
                duration_str = f"{duration // 3600}h"
            else:
                duration_str = f"{duration // 60}m"

            expires_at = datetime.now(NY_TZ) + timedelta(seconds=duration)
            db.add_mute(
                user_id=member.id,
                guild_id=member.guild.id,
                expires_at=expires_at.timestamp(),
                reason=f"Auto-spam: {spam_type}",
            )

            case_info = await self._open_spam_case(member, spam_type, duration, violation_count)

            embed = discord.Embed(
                title=f"🔇 {spam_type}",
                description=f"{member.mention} has been muted.",
                color=EmbedColors.WARNING,
            )
            embed.add_field(name="Duration", value=duration_str, inline=True)
            embed.add_field(name="Violation", value=f"#{violation_count}", inline=True)
            set_footer(embed)

            view = None
            if case_info and case_info.get("thread_id"):
                case_url = f"https://discord.com/channels/{member.guild.id}/{case_info['thread_id']}"
                view = discord.ui.View(timeout=None)
                view.add_item(discord.ui.Button(
                    label="Case",
                    url=case_url,
                    style=discord.ButtonStyle.link,
                    emoji=CASE_EMOJI,
                ))

            await channel.send(embed=embed, view=view, delete_after=15)

            # DM the user about the mute
            dm_sent = False
            try:
                dm_embed = discord.Embed(
                    title=f"🔇 You've been muted in {member.guild.name}",
                    color=EmbedColors.WARNING,
                )
                dm_embed.add_field(name="Reason", value=spam_type, inline=True)
                dm_embed.add_field(name="Duration", value=duration_str, inline=True)
                dm_embed.add_field(name="Violation", value=f"#{violation_count}", inline=True)
                dm_embed.set_footer(text="This was an automatic action by the anti-spam system.")
                await member.send(embed=dm_embed)
                dm_sent = True
            except discord.Forbidden:
                logger.debug(f"Auto-mute DM failed for {member.id}: DMs disabled")
            except discord.HTTPException as e:
                logger.debug(f"Auto-mute DM failed for {member.id}: {e}")

            logger.tree("AUTO-MUTE APPLIED", [
                ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                ("User ID", str(member.id)),
                ("Type", spam_type),
                ("Duration", duration_str),
                ("Violation", f"#{violation_count}"),
                ("DM Sent", "Yes" if dm_sent else "No (DMs disabled)"),
            ], emoji="🔇")

        except discord.Forbidden:
            logger.warning("Auto-Mute Permission Denied", [
                ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                ("User ID", str(member.id)),
                ("Type", spam_type),
            ])
        except discord.HTTPException as e:
            logger.warning("Auto-Mute Failed", [
                ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                ("User ID", str(member.id)),
                ("Type", spam_type),
                ("Error", str(e)[:50]),
            ])

    async def _open_spam_case(
        self,
        member: discord.Member,
        spam_type: str,
        duration: int,
        violation_count: int,
    ) -> Optional[dict]:
        """Open a case for the spam violation and return case info."""
        bot: "AzabBot" = self.bot  # type: ignore

        if not bot.case_log_service:
            return None

        if duration >= 3600:
            duration_str = f"{duration // 3600} hour(s)"
        else:
            duration_str = f"{duration // 60} minute(s)"

        try:
            case_info = await asyncio.wait_for(
                bot.case_log_service.log_mute(
                    user=member,
                    moderator=bot.user,
                    duration=duration_str,
                    reason=f"Auto-spam detection: {spam_type} (violation #{violation_count})",
                    is_extension=False,
                    evidence=None,
                ),
                timeout=CASE_LOG_TIMEOUT,
            )
            return case_info
        except asyncio.TimeoutError:
            logger.warning("Case Log Timeout", [
                ("Action", "Auto-Spam Mute"),
                ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                ("ID", str(member.id)),
            ])
            return None
        except Exception as e:
            logger.error("Case Log Failed", [
                ("Action", "Auto-Spam Mute"),
                ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                ("ID", str(member.id)),
                ("Error", str(e)[:100]),
            ])
            return None

    async def _log_spam(
        self,
        message: discord.Message,
        spam_type: str,
        action: str,
        violation_count: int,
        mute_duration: int = 0,
    ) -> None:
        """Log spam incident to server logs."""
        bot: "AzabBot" = self.bot  # type: ignore
        spam_display = SPAM_DISPLAY_NAMES.get(spam_type, spam_type)

        action_str = "warned" if action == "warning" else f"muted ({mute_duration}s)"
        author = message.author
        logger.tree("SPAM DETECTED", [
            ("User", f"{author.name} ({author.nick})" if hasattr(author, 'nick') and author.nick else author.name),
            ("ID", str(author.id)),
            ("Type", spam_display),
            ("Action", action_str),
            ("Violations", str(violation_count)),
            ("Channel", f"#{message.channel.name}" if hasattr(message.channel, 'name') else "DM"),
        ], emoji="🛡️")

        if bot.logging_service and bot.logging_service.enabled:
            try:
                if mute_duration > 0:
                    if mute_duration >= 3600:
                        duration_str = f"{mute_duration // 3600}h"
                    else:
                        duration_str = f"{mute_duration // 60}m"

                    embed = discord.Embed(
                        title="🛡️ Auto-Spam Mute",
                        color=EmbedColors.WARNING,
                        timestamp=datetime.now(NY_TZ),
                    )
                    embed.add_field(name="User", value=f"{message.author.mention}", inline=True)
                    embed.add_field(name="Type", value=spam_display, inline=True)
                    embed.add_field(name="Duration", value=duration_str, inline=True)
                    embed.add_field(name="Violations", value=f"#{violation_count}", inline=True)
                    if message.content:
                        content_preview = message.content[:100] + ("..." if len(message.content) > 100 else "")
                        embed.add_field(name="Content", value=f"```{content_preview}```", inline=False)

                    await bot.logging_service._send_log(
                        bot.logging_service.LogCategory.MOD_ACTIONS,
                        embed,
                    )
            except Exception as e:
                logger.warning("Server Log Failed", [
                    ("Action", "Spam Detection"),
                    ("Type", spam_display),
                    ("Error", str(e)[:50]),
                ])
