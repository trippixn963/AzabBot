"""
Azab Discord Bot - Message Events
=================================

Handles message create, delete, and edit events.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
import time
from datetime import datetime, timedelta
from collections import deque
from typing import TYPE_CHECKING, Optional, Dict, List

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.utils.footer import set_footer
from src.utils.async_utils import create_safe_task

if TYPE_CHECKING:
    from src.bot import AzabBot


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


class MessageEvents(commands.Cog):
    """Message event handlers."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()

        # Prisoner ping abuse tracking
        self._prisoner_ping_violations: Dict[int, List[float]] = {}
        self._prisoner_warning_times: Dict[int, float] = {}
        self._ping_lock = asyncio.Lock()

    # =========================================================================
    # Prisoner Ping Violation Handler
    # =========================================================================

    async def _handle_prisoner_ping_violation(self, message: discord.Message) -> None:
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
                ("User", f"{message.author} ({message.author.id})"),
                ("Reason", "Missing permissions"),
            ])
            return
        except discord.HTTPException as e:
            logger.warning("Prisoner Ping Delete Failed", [
                ("User", f"{message.author} ({message.author.id})"),
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
                        ("User", f"{message.author} ({message.author.id})"),
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
                    ("User", f"{message.author} ({message.author.id})"),
                    ("Reason", "Missing permissions"),
                ])
            except discord.HTTPException as e:
                logger.warning("Prisoner Timeout Failed", [
                    ("User", f"{message.author} ({message.author.id})"),
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
            ("User", f"{message.author} ({message.author.id})"),
            ("Violations", f"{violation_count}/{PRISONER_PING_MAX}"),
            ("Warning", "Yes" if should_warn else "No (cooldown)"),
        ], emoji="🚫")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Event handler for messages.

        DESIGN: Multi-path message routing:
        1. Case forum thread -> Check for reason replies
        2. Logs channel -> Parse mute embeds
        3. Polls channel -> Delete non-polls
        4. Ignored users -> Skip
        5. Muted users -> Roast with batching
        """
        # -----------------------------------------------------------------
        # Route 1: Case forum thread - check for reason replies
        # -----------------------------------------------------------------
        if (
            self.config.case_log_forum_id
            and isinstance(message.channel, discord.Thread)
            and message.channel.parent_id == self.config.case_log_forum_id
            and message.reference  # It's a reply
            and not message.author.bot
            and self.bot.case_log_service
        ):
            await self.bot.case_log_service.handle_reason_reply(message)

        # -----------------------------------------------------------------
        # Route 1.5: Ticket thread - track activity for auto-close
        # -----------------------------------------------------------------
        if (
            isinstance(message.channel, discord.Thread)
            and not message.author.bot
            and self.bot.ticket_service
            and self.bot.ticket_service.enabled
        ):
            await self.bot.ticket_service.track_ticket_activity(message.channel.id)

        # -----------------------------------------------------------------
        # Route 2: Logs channel - parse mute embeds
        # -----------------------------------------------------------------
        if message.channel.id == self.config.logs_channel_id and message.embeds:
            if self.bot.mute_handler:
                await self.bot.mute_handler.process_mute_embed(message)
            return

        # -----------------------------------------------------------------
        # Route 2: Polls-only channel - delete non-polls
        # -----------------------------------------------------------------
        is_polls_channel = (
            message.channel.id == self.config.polls_only_channel_id or
            message.channel.id == self.config.permanent_polls_channel_id
        )
        if is_polls_channel:
            if getattr(message, 'poll', None) is None:
                try:
                    await message.delete()
                    logger.tree("NON-POLL DELETED", [
                        ("Author", f"{message.author} ({message.author.id})"),
                        ("Channel", message.channel.name),
                        ("Content", (message.content[:50] + "...") if len(message.content) > 50 else (message.content or "(empty)")),
                    ], emoji="🗑️")
                except discord.Forbidden:
                    logger.warning(f"No permission to delete non-poll by {message.author}")
            return

        # -----------------------------------------------------------------
        # Route 3: DM handling (modmail for banned users, mod tracker alerts)
        # -----------------------------------------------------------------
        if isinstance(message.channel, discord.DMChannel):
            # Check if this is a banned user trying to contact staff (modmail)
            if (
                self.bot.modmail_service
                and self.bot.modmail_service.enabled
                and not message.author.bot
            ):
                handled = await self.bot.modmail_service.handle_dm(message)
                if handled:
                    return  # Modmail handled the message

            # Check if this is a tracked mod DMing the bot
            if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(message.author.id):
                await self.bot.mod_tracker.alert_dm_attempt(
                    mod_id=message.author.id,
                    message_content=message.content or "(no text content)",
                )
            return

        # -----------------------------------------------------------------
        # Route 3.5: Modmail thread - relay staff replies to user
        # -----------------------------------------------------------------
        if (
            isinstance(message.channel, discord.Thread)
            and self.config.modmail_forum_id
            and message.channel.parent_id == self.config.modmail_forum_id
            and not message.author.bot
            and self.bot.modmail_service
            and self.bot.modmail_service.enabled
        ):
            await self.bot.modmail_service.handle_thread_message(message)
            # Don't return - let other handlers run if needed

        # -----------------------------------------------------------------
        # Cache attachments for delete logging
        # -----------------------------------------------------------------
        if message.attachments and not message.author.bot:
            create_safe_task(self.bot._cache_message_attachments(message), "Attachment Cache")

        # -----------------------------------------------------------------
        # Cache message content for mod delete logging (OrderedDict LRU)
        # -----------------------------------------------------------------
        if not message.author.bot and message.guild:
            # Evict oldest entries if at limit (O(1) with OrderedDict)
            while len(self.bot._message_cache) >= self.bot._message_cache_limit:
                self.bot._message_cache.popitem(last=False)  # Remove oldest

            self.bot._message_cache[message.id] = {
                "author": message.author,
                "content": message.content,
                "channel_id": message.channel.id,
                "attachment_names": [a.filename for a in message.attachments] if message.attachments else [],
                "sticker_names": [s.name for s in message.stickers] if message.stickers else [],
                "has_embeds": len(message.embeds) > 0,
                "embed_titles": [e.title for e in message.embeds if e.title] if message.embeds else [],
                "reply_to": message.reference.message_id if message.reference else None,
            }

        # -----------------------------------------------------------------
        # Anti-Spam Check (early exit if spam detected)
        # -----------------------------------------------------------------
        if self.bot.antispam_service and message.guild:
            spam_type = await self.bot.antispam_service.check_message(message)
            if spam_type:
                if spam_type == "webhook_spam":
                    await self.bot.antispam_service.handle_webhook_spam(message)
                else:
                    await self.bot.antispam_service.handle_spam(message, spam_type)
                return  # Don't process spam messages further

        # -----------------------------------------------------------------
        # Skip: Bots and empty messages
        # -----------------------------------------------------------------
        if message.author.bot:
            return

        if not message.content:
            return

        # -----------------------------------------------------------------
        # Auto-Response: Partnership keyword detection
        # -----------------------------------------------------------------
        if message.guild and "partnership" in message.content.lower():
            await self._handle_partnership_mention(message)

        # -----------------------------------------------------------------
        # Auto-Mod: External Discord Invite Links
        # Skip: links-allowed channel, management role holders
        # -----------------------------------------------------------------
        if message.guild and message.content:
            invite_matches = INVITE_PATTERN.findall(message.content)
            if invite_matches:
                # Check if in links-allowed channel
                is_links_allowed_channel = (
                    self.config.links_allowed_channel_id
                    and message.channel.id == self.config.links_allowed_channel_id
                )
                if is_links_allowed_channel:
                    logger.tree("INVITE LINK ALLOWED", [
                        ("User", f"{message.author} ({message.author.id})"),
                        ("Channel", f"#{message.channel.name}"),
                        ("Reason", "Links-allowed channel"),
                        ("Invite(s)", ", ".join(invite_matches)),
                    ], emoji="✅")
                    # Don't return - continue processing message
                else:
                    # Check if user has management role
                    is_mod = (
                        isinstance(message.author, discord.Member)
                        and self.config.moderation_role_id
                        and message.author.get_role(self.config.moderation_role_id)
                    )
                    if is_mod:
                        logger.tree("INVITE LINK ALLOWED", [
                            ("User", f"{message.author} ({message.author.id})"),
                            ("Channel", f"#{message.channel.name}"),
                            ("Reason", "Management role holder"),
                            ("Invite(s)", ", ".join(invite_matches)),
                        ], emoji="✅")
                        # Don't return - continue processing message
                    else:
                        # Check if it's an external invite
                        external_invite = self._check_external_invite(message)
                        if external_invite:
                            await self._handle_external_invite(message, external_invite)
                            return  # Stop processing - message deleted
                        else:
                            logger.tree("INVITE LINK ALLOWED", [
                                ("User", f"{message.author} ({message.author.id})"),
                                ("Channel", f"#{message.channel.name}"),
                                ("Reason", "Server invite (syria)"),
                                ("Invite(s)", ", ".join(invite_matches)),
                            ], emoji="✅")

        # -----------------------------------------------------------------
        # Skip: Ignored users
        # -----------------------------------------------------------------
        if self.bot.db.is_user_ignored(message.author.id):
            return

        # -----------------------------------------------------------------
        # Skip: Bot disabled
        # -----------------------------------------------------------------
        if self.bot.disabled:
            return

        # -----------------------------------------------------------------
        # Channel restrictions
        # -----------------------------------------------------------------
        if self.config.prison_channel_ids:
            if message.channel.id not in self.config.prison_channel_ids:
                return

        # -----------------------------------------------------------------
        # Prison ping blocking: Prisoners cannot ping anyone
        # -----------------------------------------------------------------
        if self.config.prison_channel_ids and message.channel.id in self.config.prison_channel_ids:
            # Check if author is a prisoner (has muted role)
            if isinstance(message.author, discord.Member) and self.config.muted_role_id:
                is_prisoner = any(r.id == self.config.muted_role_id for r in message.author.roles)

                # Check if they're a mod (bypass)
                is_mod = False
                if self.config.moderation_role_id:
                    is_mod = any(r.id == self.config.moderation_role_id for r in message.author.roles)

                # If prisoner (not mod) and has explicit pings, handle violation
                if is_prisoner and not is_mod:
                    # Get mentions that are NOT from a reply
                    explicit_mentions = list(message.mentions)
                    if message.reference and message.reference.resolved:
                        # Remove the replied-to user from mentions (replies are allowed)
                        replied_to = getattr(message.reference.resolved, 'author', None)
                        if replied_to and replied_to in explicit_mentions:
                            explicit_mentions.remove(replied_to)

                    has_pings = (
                        explicit_mentions or  # @user mentions (excluding reply)
                        message.role_mentions or  # @role mentions
                        message.mention_everyone  # @everyone/@here
                    )
                    if has_pings:
                        await self._handle_prisoner_ping_violation(message)
                        return  # Stop processing this message

        # -----------------------------------------------------------------
        # Log message to database for context
        # -----------------------------------------------------------------
        if message.guild:
            await self.bot.db.log_message(
                message.author.id,
                str(message.author),
                message.content,
                message.channel.id,
                message.guild.id,
            )

            # Track message history for AI context (OrderedDict LRU)
            if message.author.id not in self.bot.last_messages:
                # Evict oldest user if at limit
                while len(self.bot.last_messages) >= self.bot._last_messages_limit:
                    self.bot.last_messages.popitem(last=False)
                self.bot.last_messages[message.author.id] = {
                    "messages": deque(maxlen=self.config.message_history_size),
                    "channel_id": message.channel.id,
                }
            else:
                # Move to end (most recently used)
                self.bot.last_messages.move_to_end(message.author.id)
            self.bot.last_messages[message.author.id]["messages"].append(message.content)
            self.bot.last_messages[message.author.id]["channel_id"] = message.channel.id

            # Cache messages from tracked mods
            if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(message.author.id):
                if message.attachments:
                    await self.bot.mod_tracker.cache_message(message)

    # =========================================================================
    # Partnership Auto-Response
    # =========================================================================

    async def _handle_partnership_mention(self, message: discord.Message) -> None:
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
                ("User", f"{message.author} ({message.author.id})"),
                ("Channel", f"#{message.channel.name}"),
            ], emoji="🤝")

        except discord.HTTPException:
            pass

    # =========================================================================
    # Invite Link Detection
    # =========================================================================

    def _check_external_invite(self, message: discord.Message) -> Optional[str]:
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

    async def _handle_external_invite(self, message: discord.Message, invite_code: str) -> None:
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
                ("User", f"{member} ({member.id})"),
                ("Channel", f"#{message.channel.name}"),
                ("Reason", "Missing permissions"),
            ], emoji="❌")
        except discord.HTTPException as e:
            logger.tree("INVITE DELETE FAILED", [
                ("User", f"{member} ({member.id})"),
                ("Channel", f"#{message.channel.name}"),
                ("Error", str(e)[:50]),
            ], emoji="❌")

        # -----------------------------------------------------------------
        # 2. Apply permanent mute role
        # -----------------------------------------------------------------
        muted_role = guild.get_role(self.config.muted_role_id)
        if not muted_role:
            logger.tree("INVITE MUTE FAILED", [
                ("User", f"{member} ({member.id})"),
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
                ("User", f"{member} ({member.id})"),
                ("Reason", "Missing permissions"),
            ], emoji="❌")
            return
        except discord.HTTPException as e:
            logger.tree("INVITE MUTE FAILED", [
                ("User", f"{member} ({member.id})"),
                ("Error", str(e)[:50]),
            ], emoji="❌")
            return

        # Comprehensive success log
        logger.tree("AUTO-MUTE: EXTERNAL INVITE", [
            ("User", f"{member} ({member.id})"),
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
                    ("User", f"{member} ({member.id})"),
                    ("Channel", f"#{prison_channel.name}"),
                ], emoji="📢")
            except discord.HTTPException as e:
                logger.tree("PRISON NOTIFICATION FAILED", [
                    ("User", f"{member} ({member.id})"),
                    ("Error", str(e)[:50]),
                ], emoji="❌")
        else:
            logger.tree("PRISON NOTIFICATION SKIPPED", [
                ("User", f"{member} ({member.id})"),
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
                    timeout=10.0,
                )
                if case_result:
                    logger.tree("CASE LOG CREATED", [
                        ("User", f"{member} ({member.id})"),
                        ("Case Number", str(case_result.get("case_number", "N/A"))),
                        ("Thread", case_result.get("thread_name", "N/A")),
                    ], emoji="📋")
                else:
                    logger.tree("CASE LOG FAILED", [
                        ("User", f"{member} ({member.id})"),
                        ("Reason", "log_mute returned None"),
                    ], emoji="❌")
            except asyncio.TimeoutError:
                logger.warning("Case Log Timeout", [
                    ("Action", "Auto-Mute (Invite Link)"),
                    ("User", f"{member} ({member.id})"),
                ])
            except Exception as e:
                logger.error("Case Log Failed", [
                    ("Action", "Auto-Mute (Invite Link)"),
                    ("User", f"{member} ({member.id})"),
                    ("Error", str(e)[:100]),
                ])
        else:
            logger.tree("CASE LOG SKIPPED", [
                ("User", f"{member} ({member.id})"),
                ("Reason", "Case log service not configured"),
            ], emoji="⚠️")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """Track message deletions for tracked mods and logging service."""
        if message.author.bot:
            return

        # -----------------------------------------------------------------
        # Snipe Cache: Store deleted messages (database + memory)
        # -----------------------------------------------------------------
        channel_id = message.channel.id
        deleted_at = datetime.now(NY_TZ).timestamp()
        attachment_names = [a.filename for a in message.attachments] if message.attachments else []

        # Build attachment URL data for snipe display
        attachment_urls = []
        if message.attachments:
            for att in message.attachments:
                attachment_urls.append({
                    "filename": att.filename,
                    "url": att.url,
                    "content_type": att.content_type,
                    "size": att.size,
                })

        # Build sticker data for snipe display
        sticker_urls = []
        if message.stickers:
            for sticker in message.stickers:
                sticker_urls.append({
                    "name": sticker.name,
                    "url": sticker.url,
                })

        # Get attachment bytes from cache BEFORE logging service pops it
        # Store as base64 in database for reliable /snipe display
        attachment_data = None
        if message.id in self.bot._attachment_cache:
            import base64
            attachment_data = []
            for filename, file_bytes in self.bot._attachment_cache[message.id]:
                try:
                    attachment_data.append({
                        "filename": filename,
                        "data": base64.b64encode(file_bytes).decode("utf-8"),
                    })
                except Exception as e:
                    logger.warning("Snipe Attachment Encode Failed", [
                        ("Filename", filename),
                        ("Error", str(e)[:50]),
                    ])

        # Save to database (persists across restarts)
        self.bot.db.save_snipe(
            channel_id=channel_id,
            author_id=message.author.id,
            author_name=str(message.author),
            author_display=message.author.display_name,
            author_avatar=message.author.display_avatar.url,
            content=message.content,
            attachment_names=attachment_names,
            deleted_at=deleted_at,
            attachment_urls=attachment_urls if attachment_urls else None,
            sticker_urls=sticker_urls if sticker_urls else None,
            message_id=message.id,
            attachment_data=attachment_data,
        )

        # Tree logging for message deletions
        content_preview = "(empty)"
        if message.content:
            content_preview = (message.content[:40] + "...") if len(message.content) > 40 else message.content

        attachment_info = ""
        if message.attachments:
            attachment_info = f" +{len(message.attachments)} attachment(s)"

        logger.tree("MESSAGE DELETED", [
            ("Author", f"{message.author} ({message.author.id})"),
            ("Channel", f"#{message.channel.name}" if hasattr(message.channel, 'name') else "DM"),
            ("Content", content_preview + attachment_info),
        ], emoji="🗑️")

        # -----------------------------------------------------------------
        # Logging Service: Message Delete
        # -----------------------------------------------------------------
        if self.bot.logging_service and self.bot.logging_service.enabled:
            attachments = self.bot._attachment_cache.pop(message.id, None)
            await self.bot.logging_service.log_message_delete(message, attachments)

        # -----------------------------------------------------------------
        # Mod Tracker: Message Delete
        # -----------------------------------------------------------------
        if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(message.author.id):
            reply_to_user = None
            reply_to_id = None
            if message.reference and message.reference.message_id:
                try:
                    ref_msg = message.reference.cached_message
                    if not ref_msg:
                        ref_msg = await message.channel.fetch_message(message.reference.message_id)
                    if ref_msg:
                        reply_to_user = ref_msg.author
                        reply_to_id = ref_msg.author.id
                except Exception:
                    pass

            await self.bot.mod_tracker.log_message_delete(
                mod_id=message.author.id,
                channel=message.channel,
                content=message.content or "",
                attachments=message.attachments,
                message_id=message.id,
                reply_to_user=reply_to_user,
                reply_to_id=reply_to_id,
            )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        """Track message edits for tracked mods and logging service."""
        if before.author.bot:
            return

        # Check if content or attachments changed
        content_changed = before.content != after.content
        attachments_changed = len(before.attachments) != len(after.attachments)

        if not content_changed and not attachments_changed:
            return

        # -----------------------------------------------------------------
        # Edit Snipe Cache: Store last 10 edits per channel (OrderedDict LRU)
        # -----------------------------------------------------------------
        channel_id = before.channel.id

        # Initialize deque if not exists, with LRU eviction
        if channel_id not in self.bot._editsnipe_cache:
            # Evict oldest channel if at limit
            while len(self.bot._editsnipe_cache) >= self.bot._editsnipe_channel_limit:
                self.bot._editsnipe_cache.popitem(last=False)
            self.bot._editsnipe_cache[channel_id] = deque(maxlen=self.bot._editsnipe_limit)
        else:
            # Move to end (most recently used)
            self.bot._editsnipe_cache.move_to_end(channel_id)

        # Build before/after attachment data
        before_attachments = []
        for att in before.attachments:
            before_attachments.append({
                "filename": att.filename,
                "url": att.url,
                "content_type": att.content_type,
                "size": att.size,
            })

        after_attachments = []
        for att in after.attachments:
            after_attachments.append({
                "filename": att.filename,
                "url": att.url,
                "content_type": att.content_type,
                "size": att.size,
            })

        edit_data = {
            "author_id": before.author.id,
            "author_name": str(before.author),
            "author_display": before.author.display_name,
            "author_avatar": before.author.display_avatar.url,
            "before_content": before.content,
            "after_content": after.content,
            "before_attachments": before_attachments,
            "after_attachments": after_attachments,
            "edited_at": datetime.now(NY_TZ).timestamp(),
            "message_id": before.id,
            "jump_url": after.jump_url,
        }

        # Add to front of deque (most recent first)
        self.bot._editsnipe_cache[channel_id].appendleft(edit_data)

        # Tree logging for message edits
        before_preview = (before.content[:30] + "...") if len(before.content) > 30 else (before.content or "(empty)")
        after_preview = (after.content[:30] + "...") if len(after.content) > 30 else (after.content or "(empty)")

        logger.tree("MESSAGE EDITED", [
            ("Author", f"{before.author} ({before.author.id})"),
            ("Channel", f"#{before.channel.name}" if hasattr(before.channel, 'name') else "DM"),
            ("Before", before_preview),
            ("After", after_preview),
        ], emoji="✏️")

        # -----------------------------------------------------------------
        # Logging Service: Message Edit
        # -----------------------------------------------------------------
        if self.bot.logging_service and self.bot.logging_service.enabled:
            await self.bot.logging_service.log_message_edit(before, after)

        # -----------------------------------------------------------------
        # Mod Tracker: Message Edit
        # -----------------------------------------------------------------
        if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(before.author.id):
            reply_to_user = None
            reply_to_id = None
            if after.reference and after.reference.message_id:
                try:
                    ref_msg = after.reference.cached_message
                    if not ref_msg:
                        ref_msg = await after.channel.fetch_message(after.reference.message_id)
                    if ref_msg:
                        reply_to_user = ref_msg.author
                        reply_to_id = ref_msg.author.id
                except Exception:
                    pass

            await self.bot.mod_tracker.log_message_edit(
                mod=before.author,
                channel=before.channel,
                old_content=before.content or "",
                new_content=after.content or "",
                jump_url=after.jump_url,
                reply_to_user=reply_to_user,
                reply_to_id=reply_to_id,
            )


async def setup(bot: "AzabBot") -> None:
    """Add the message events cog to the bot."""
    await bot.add_cog(MessageEvents(bot))
    logger.debug("Message Events Loaded")
