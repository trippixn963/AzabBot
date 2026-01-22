"""
AzabBot - Helpers Mixin
=======================

Helper methods for message event handling.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.core.constants import CASE_LOG_TIMEOUT
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from .cog import MessageEvents


# Discord invite link patterns
INVITE_PATTERN = re.compile(
    r'(?:https?://)?(?:www\.)?'
    r'(?:discord\.gg|discord(?:app)?\.com/invite|dsc\.gg)'
    r'/([a-zA-Z0-9-]+)',
    re.IGNORECASE
)

# =============================================================================
# Prisoner Ping Rate Limiting Constants
# =============================================================================

PRISONER_PING_WINDOW = 60  # Time window in seconds for tracking pings
PRISONER_PING_MAX = 3  # Max pings allowed in the window before timeout
PRISONER_PING_TIMEOUT = timedelta(hours=1)  # Discord timeout duration
PRISONER_WARNING_COOLDOWN = 30  # Seconds between warning messages per user


class HelpersMixin:
    """Mixin for message event helper methods."""

    async def _handle_prisoner_ping_violation(self: "MessageEvents", message: discord.Message) -> None:
        """
        Handle a prisoner attempting to ping.

        Progressive response:
        1. Delete the message
        2. Track violations in sliding window
        3. After 3 violations in 60 seconds: Apply 1 hour Discord timeout
        4. Rate-limit warning messages to prevent spam
        """
        user_id = message.author.id
        now = time.time()

        # Always try to delete the message first
        try:
            await message.delete()
        except discord.Forbidden:
            logger.warning("Prisoner Ping Delete Failed", [
                ("User", f"{message.author.name} ({message.author.nick})" if hasattr(message.author, 'nick') and message.author.nick else message.author.name),
                ("ID", str(message.author.id)),
                ("Reason", "Missing permissions"),
            ])
            return
        except discord.HTTPException as e:
            logger.warning("Prisoner Ping Delete Failed", [
                ("User", f"{message.author.name} ({message.author.nick})" if hasattr(message.author, 'nick') and message.author.nick else message.author.name),
                ("ID", str(message.author.id)),
                ("Error", str(e)[:50]),
            ])
            return

        # Track violations with lock for thread safety
        async with self._ping_lock:
            if user_id not in self._prisoner_ping_violations:
                self._prisoner_ping_violations[user_id] = []

            # Clean old violations outside the window
            cutoff = now - PRISONER_PING_WINDOW
            self._prisoner_ping_violations[user_id] = [
                ts for ts in self._prisoner_ping_violations[user_id]
                if ts > cutoff
            ]

            # Add this violation
            self._prisoner_ping_violations[user_id].append(now)
            violation_count = len(self._prisoner_ping_violations[user_id])

        # Check if exceeded limit -> apply timeout
        if violation_count >= PRISONER_PING_MAX:
            try:
                if isinstance(message.author, discord.Member):
                    await message.author.timeout(
                        PRISONER_PING_TIMEOUT,
                        reason=f"Ping spam in prison ({violation_count} pings in {PRISONER_PING_WINDOW}s)"
                    )

                    logger.tree("PRISONER PING SPAM - TIMEOUT", [
                        ("User", f"{message.author.name} ({message.author.nick})" if hasattr(message.author, 'nick') and message.author.nick else message.author.name),
                        ("ID", str(message.author.id)),
                        ("Violations", f"{violation_count} in {PRISONER_PING_WINDOW}s"),
                        ("Timeout", "1 hour"),
                    ], emoji="⏰")

                    # Send timeout notification
                    try:
                        await message.channel.send(
                            f"🔇 {message.author.mention} has been timed out for 1 hour for ping spam.",
                            delete_after=10.0,
                        )
                    except discord.HTTPException:
                        pass

                    # Clear violations after timeout
                    async with self._ping_lock:
                        self._prisoner_ping_violations[user_id] = []

            except discord.Forbidden:
                logger.warning("Prisoner Timeout Failed", [
                    ("User", f"{message.author.name} ({message.author.nick})" if hasattr(message.author, 'nick') and message.author.nick else message.author.name),
                    ("ID", str(message.author.id)),
                    ("Reason", "Missing permissions"),
                ])
            except discord.HTTPException as e:
                logger.warning("Prisoner Timeout Failed", [
                    ("User", f"{message.author.name} ({message.author.nick})" if hasattr(message.author, 'nick') and message.author.nick else message.author.name),
                    ("ID", str(message.author.id)),
                    ("Error", str(e)[:50]),
                ])
            return

        # Rate-limit warning messages
        should_warn = False
        async with self._ping_lock:
            last_warning = self._prisoner_warning_times.get(user_id, 0)
            if now - last_warning >= PRISONER_WARNING_COOLDOWN:
                self._prisoner_warning_times[user_id] = now
                should_warn = True

        if should_warn:
            try:
                remaining = PRISONER_PING_MAX - violation_count
                await message.channel.send(
                    f"{message.author.mention} Prisoners cannot ping others. "
                    f"({remaining} more = 1h timeout)",
                    delete_after=5.0,
                )
            except discord.HTTPException:
                pass

        logger.tree("PRISONER PING BLOCKED", [
            ("User", f"{message.author.name} ({message.author.nick})" if hasattr(message.author, 'nick') and message.author.nick else message.author.name),
            ("ID", str(message.author.id)),
            ("Violations", f"{violation_count}/{PRISONER_PING_MAX}"),
            ("Warning", "Yes" if should_warn else "No (cooldown)"),
        ], emoji="🚫")

    # =========================================================================
    # Partnership Auto-Response
    # =========================================================================

    async def _handle_partnership_mention(self: "MessageEvents", message: discord.Message) -> None:
        """
        Auto-respond when someone mentions "partnership" outside ticket channels.
        Directs them to create a partnership ticket.
        """
        # Skip if no ticket channel configured
        if not self.config.ticket_channel_id:
            return

        # Skip if in the ticket channel itself
        if message.channel.id == self.config.ticket_channel_id:
            return

        # Skip if in a ticket thread (parent is the ticket channel)
        if isinstance(message.channel, discord.Thread):
            if message.channel.parent_id == self.config.ticket_channel_id:
                return

        # Skip if user is developer
        if message.author.id == self.config.developer_id:
            return

        # Skip if user is a mod (they know how the system works)
        if isinstance(message.author, discord.Member):
            if self.config.moderation_role_id and message.author.get_role(self.config.moderation_role_id):
                return
            # Also skip if they have admin/mod permissions
            if message.author.guild_permissions.administrator or message.author.guild_permissions.moderate_members:
                return

        # Rate limit: Don't spam the same channel (use simple cooldown)
        cooldown_key = f"partnership_response:{message.channel.id}"
        if hasattr(self, '_partnership_cooldowns'):
            last_response = self._partnership_cooldowns.get(cooldown_key, 0)
            if datetime.now(NY_TZ).timestamp() - last_response < 300:  # 5 min cooldown per channel
                return
        else:
            self._partnership_cooldowns = {}

        # Send the response
        try:
            ticket_channel = self.bot.get_channel(self.config.ticket_channel_id)
            if not ticket_channel:
                return

            await message.reply(
                f"👋 Looking for a partnership? Head over to {ticket_channel.mention} and select the **Partnership** ticket option to get started!",
                mention_author=False,
            )

            # Update cooldown
            self._partnership_cooldowns[cooldown_key] = datetime.now(NY_TZ).timestamp()

            logger.tree("PARTNERSHIP AUTO-RESPONSE", [
                ("User", f"{message.author.name} ({message.author.nick})" if hasattr(message.author, 'nick') and message.author.nick else message.author.name),
                ("ID", str(message.author.id)),
                ("Channel", f"#{message.channel.name}"),
            ], emoji="🤝")

        except discord.HTTPException:
            pass

    # =========================================================================
    # Invite Link Detection
    # =========================================================================

    def _check_external_invite(self: "MessageEvents", message: discord.Message) -> Optional[str]:
        """
        Check if message contains an external Discord invite link.

        Only discord.gg/syria is allowed. Everything else is external.

        Args:
            message: The message to check.

        Returns:
            The invite code if external, None if allowed or no invite.
        """
        if not message.guild:
            return None

        # Find all invite codes in the message
        matches = INVITE_PATTERN.findall(message.content)
        if not matches:
            return None

        # Only allow "syria" (case-insensitive)
        for invite_code in matches:
            if invite_code.lower() != "syria":
                return invite_code  # External invite found

        return None

    async def _handle_external_invite(self: "MessageEvents", message: discord.Message, invite_code: str) -> None:
        """
        Handle an external Discord invite link.

        Actions:
        1. Delete the message
        2. Apply permanent mute role
        3. Send notification to prison channel
        4. Create case log entry

        Args:
            message: The message containing the invite.
            invite_code: The external invite code.
        """
        member = message.author
        if not isinstance(member, discord.Member):
            return

        guild = message.guild
        if not guild:
            return

        # -----------------------------------------------------------------
        # 1. Delete the message
        # -----------------------------------------------------------------
        message_deleted = False
        try:
            await message.delete()
            message_deleted = True
        except discord.Forbidden:
            logger.tree("INVITE DELETE FAILED", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("Channel", f"#{message.channel.name}"),
                ("Reason", "Missing permissions"),
            ], emoji="❌")
        except discord.HTTPException as e:
            logger.tree("INVITE DELETE FAILED", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("Channel", f"#{message.channel.name}"),
                ("Error", str(e)[:50]),
            ], emoji="❌")

        # -----------------------------------------------------------------
        # 2. Apply permanent mute role
        # -----------------------------------------------------------------
        muted_role = guild.get_role(self.config.muted_role_id)
        if not muted_role:
            logger.tree("INVITE MUTE FAILED", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("Reason", "Muted role not found"),
                ("Role ID", str(self.config.muted_role_id)),
            ], emoji="❌")
            return

        mute_applied = False
        try:
            await member.add_roles(muted_role, reason="Auto-mute: External Discord invite link")
            mute_applied = True
        except discord.Forbidden:
            logger.tree("INVITE MUTE FAILED", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("Reason", "Missing permissions"),
            ], emoji="❌")
            return
        except discord.HTTPException as e:
            logger.tree("INVITE MUTE FAILED", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("Error", str(e)[:50]),
            ], emoji="❌")
            return

        # Comprehensive success log
        logger.tree("AUTO-MUTE: EXTERNAL INVITE", [
            ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
            ("ID", str(member.id)),
            ("Display Name", member.display_name),
            ("Channel", f"#{message.channel.name}"),
            ("Invite Code", f"discord.gg/{invite_code}"),
            ("Message Deleted", "Yes" if message_deleted else "No"),
            ("Mute Applied", "Yes" if mute_applied else "No"),
            ("Duration", "Permanent"),
        ], emoji="🔗")

        # -----------------------------------------------------------------
        # 3. Record mute in database
        # -----------------------------------------------------------------
        self.bot.db.record_mute(
            user_id=member.id,
            moderator_id=self.bot.user.id,
            duration="permanent",
            reason="Auto-mute: Advertising external Discord server",
        )
        logger.tree("DATABASE RECORD", [
            ("Action", "Mute recorded"),
            ("User ID", str(member.id)),
            ("Duration", "Permanent"),
        ], emoji="💾")

        # -----------------------------------------------------------------
        # 4. Send notification to prison channel
        # -----------------------------------------------------------------
        prison_channel = None
        if self.config.prison_channel_ids:
            # Use the first prison channel
            for channel_id in self.config.prison_channel_ids:
                prison_channel = guild.get_channel(channel_id)
                if prison_channel:
                    break

        notification_sent = False
        if prison_channel:
            embed = discord.Embed(
                title="🔗 Auto-Muted: External Invite Link",
                color=EmbedColors.ERROR,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(
                name="User",
                value=f"{member.mention}\n`{member.name}`",
                inline=True,
            )
            embed.add_field(
                name="Violation",
                value="`Advertising`",
                inline=True,
            )
            embed.add_field(
                name="Duration",
                value="`Permanent`",
                inline=True,
            )
            embed.add_field(
                name="Reason",
                value=(
                    "You have been **permanently muted** for posting an external Discord server invite link.\n\n"
                    "This is a serious rule violation. The server owner will review your case and decide "
                    "whether to remove the mute.\n\n"
                    "⚠️ **Do not attempt to evade this mute.**"
                ),
                inline=False,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            set_footer(embed)

            try:
                await prison_channel.send(content=member.mention, embed=embed)
                notification_sent = True
                logger.tree("PRISON NOTIFICATION SENT", [
                    ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                    ("ID", str(member.id)),
                    ("Channel", f"#{prison_channel.name}"),
                ], emoji="📢")
            except discord.HTTPException as e:
                logger.tree("PRISON NOTIFICATION FAILED", [
                    ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                    ("ID", str(member.id)),
                    ("Error", str(e)[:50]),
                ], emoji="❌")
        else:
            logger.tree("PRISON NOTIFICATION SKIPPED", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("Reason", "No prison channel configured"),
            ], emoji="⚠️")

        # -----------------------------------------------------------------
        # 5. Create case log entry
        # -----------------------------------------------------------------
        if self.bot.case_log_service:
            try:
                case_result = await asyncio.wait_for(
                    self.bot.case_log_service.log_mute(
                        user=member,
                        moderator=guild.me,  # Bot is the moderator
                        duration="Permanent",
                        reason="Auto-mute: Advertising external Discord server",
                        evidence=f"Posted invite link: `discord.gg/{invite_code}` in #{message.channel.name}",
                    ),
                    timeout=CASE_LOG_TIMEOUT,
                )
                if case_result:
                    logger.tree("CASE LOG CREATED", [
                        ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                        ("ID", str(member.id)),
                        ("Case Number", str(case_result.get("case_number", "N/A"))),
                        ("Thread", case_result.get("thread_name", "N/A")),
                    ], emoji="📋")
                else:
                    logger.tree("CASE LOG FAILED", [
                        ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                        ("ID", str(member.id)),
                        ("Reason", "log_mute returned None"),
                    ], emoji="❌")
            except asyncio.TimeoutError:
                logger.warning("Case Log Timeout", [
                    ("Action", "Auto-Mute (Invite Link)"),
                    ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                    ("ID", str(member.id)),
                ])
            except Exception as e:
                logger.error("Case Log Failed", [
                    ("Action", "Auto-Mute (Invite Link)"),
                    ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                    ("ID", str(member.id)),
                    ("Error", str(e)[:100]),
                ])
        else:
            logger.tree("CASE LOG SKIPPED", [
                ("User", f"{member.name} ({member.nick})" if hasattr(member, 'nick') and member.nick else member.name),
                ("ID", str(member.id)),
                ("Reason", "Case log service not configured"),
            ], emoji="⚠️")


__all__ = ["HelpersMixin", "INVITE_PATTERN"]
