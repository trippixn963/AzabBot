"""
Azab Discord Bot - Message Events
=================================

Handles message create, delete, and edit events.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
from datetime import datetime
from collections import deque
from typing import TYPE_CHECKING, Optional, Set

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# Discord invite link patterns
INVITE_PATTERN = re.compile(
    r'(?:https?://)?(?:www\.)?'
    r'(?:discord\.gg|discord(?:app)?\.com/invite|dsc\.gg)'
    r'/([a-zA-Z0-9-]+)',
    re.IGNORECASE
)


class MessageEvents(commands.Cog):
    """Message event handlers."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self._allowed_guild_invites: Set[str] = set()  # Cached allowed invite codes

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
        # Route 3: DM from tracked mod - alert
        # -----------------------------------------------------------------
        if isinstance(message.channel, discord.DMChannel):
            if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(message.author.id):
                await self.bot.mod_tracker.alert_dm_attempt(
                    mod_id=message.author.id,
                    message_content=message.content or "(no text content)",
                )
            return

        # -----------------------------------------------------------------
        # Cache attachments for delete logging
        # -----------------------------------------------------------------
        if message.attachments and not message.author.bot:
            asyncio.create_task(self.bot._cache_message_attachments(message))

        # -----------------------------------------------------------------
        # Cache message content for mod delete logging
        # -----------------------------------------------------------------
        if not message.author.bot and message.guild:
            if len(self.bot._message_cache) >= self.bot._message_cache_limit:
                oldest = list(self.bot._message_cache.keys())[:100]
                for key in oldest:
                    self.bot._message_cache.pop(key, None)

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
        # Skip: Bots and empty messages
        # -----------------------------------------------------------------
        if message.author.bot:
            return

        if not message.content:
            return

        # -----------------------------------------------------------------
        # Auto-Mod: External Discord Invite Links
        # -----------------------------------------------------------------
        if message.guild and message.content:
            external_invite = await self._check_external_invite(message)
            if external_invite:
                await self._handle_external_invite(message, external_invite)
                return  # Stop processing - message deleted

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

            # Track message history for AI context
            if message.author.id not in self.bot.last_messages:
                self.bot.last_messages[message.author.id] = {
                    "messages": deque(maxlen=self.config.message_history_size),
                    "channel_id": message.channel.id,
                }
            self.bot.last_messages[message.author.id]["messages"].append(message.content)
            self.bot.last_messages[message.author.id]["channel_id"] = message.channel.id

            # Cache messages from tracked mods
            if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(message.author.id):
                if message.attachments:
                    await self.bot.mod_tracker.cache_message(message)

    # =========================================================================
    # Invite Link Detection
    # =========================================================================

    async def _check_external_invite(self, message: discord.Message) -> Optional[str]:
        """
        Check if message contains an external Discord invite link.

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

        # Cache allowed invites for this guild if not already cached
        if not self._allowed_guild_invites:
            try:
                invites = await message.guild.invites()
                self._allowed_guild_invites = {inv.code for inv in invites}
                # Also add vanity URL if exists
                if message.guild.vanity_url_code:
                    self._allowed_guild_invites.add(message.guild.vanity_url_code)
            except discord.Forbidden:
                logger.warning("Cannot fetch guild invites - missing permissions")
            except Exception as e:
                logger.error(f"Failed to fetch guild invites: {e}")

        # Check each invite code
        for invite_code in matches:
            # Skip if it's one of our server's invites
            if invite_code in self._allowed_guild_invites:
                continue

            # Check if invite code matches vanity (case-insensitive)
            if message.guild.vanity_url_code and invite_code.lower() == message.guild.vanity_url_code.lower():
                continue

            # Fetch the invite to verify it's external
            try:
                invite = await self.bot.fetch_invite(invite_code)
                if invite.guild and invite.guild.id != message.guild.id:
                    return invite_code  # External invite found
            except discord.NotFound:
                # Invalid/expired invite - still suspicious, treat as external
                return invite_code
            except discord.HTTPException:
                # Can't verify - be safe and treat as external
                return invite_code

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
        try:
            await message.delete()
        except discord.Forbidden:
            logger.error(f"Cannot delete invite message - missing permissions")
        except discord.HTTPException as e:
            logger.error(f"Failed to delete invite message: {e}")

        # -----------------------------------------------------------------
        # 2. Apply permanent mute role
        # -----------------------------------------------------------------
        muted_role = guild.get_role(self.config.muted_role_id)
        if not muted_role:
            logger.error("Muted role not found for invite auto-mute")
            return

        try:
            await member.add_roles(muted_role, reason="Auto-mute: External Discord invite link")

            logger.tree("AUTO-MUTE: EXTERNAL INVITE", [
                ("User", f"{member} ({member.id})"),
                ("Channel", f"#{message.channel.name}"),
                ("Invite Code", invite_code),
                ("Action", "Permanent mute applied"),
            ], emoji="🔗")

        except discord.Forbidden:
            logger.error(f"Cannot apply mute role to {member} - missing permissions")
            return
        except discord.HTTPException as e:
            logger.error(f"Failed to apply mute role: {e}")
            return

        # -----------------------------------------------------------------
        # 3. Record mute in database
        # -----------------------------------------------------------------
        self.bot.db.record_mute(
            user_id=member.id,
            moderator_id=self.bot.user.id,
            duration="permanent",
            reason="Auto-mute: Advertising external Discord server",
        )

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
            except discord.HTTPException as e:
                logger.error(f"Failed to send prison notification: {e}")

        # -----------------------------------------------------------------
        # 5. Create case log entry
        # -----------------------------------------------------------------
        if self.bot.case_log_service:
            await self.bot.case_log_service.log_mute(
                user=member,
                moderator=guild.me,  # Bot is the moderator
                duration="Permanent",
                reason="Auto-mute: Advertising external Discord server",
                evidence=f"Posted invite link: `discord.gg/{invite_code}` in #{message.channel.name}",
            )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """Track message deletions for tracked mods and logging service."""
        if message.author.bot:
            return

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

        if before.content == after.content:
            return

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
