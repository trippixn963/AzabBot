"""
AzabBot - Cog
=============

Main MessageEvents cog with event listeners.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import base64
from datetime import datetime
from collections import deque
from typing import TYPE_CHECKING, Dict, List

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, NY_TZ
from src.core.database import get_db
from src.utils.async_utils import create_safe_task
from src.utils.snipe_blocker import should_block_snipe, is_snipe_clearer, block_from_snipe
from src.utils.discord_rate_limit import log_http_error
from src.api.services.event_logger import event_logger

from .helpers import HelpersMixin, INVITE_PATTERN

if TYPE_CHECKING:
    from src.bot import AzabBot


class MessageEvents(HelpersMixin, commands.Cog):
    """Message event handlers."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        # Prisoner ping abuse tracking
        self._prisoner_ping_violations: Dict[int, List[float]] = {}
        self._prisoner_warning_times: Dict[int, float] = {}
        self._ping_lock = asyncio.Lock()

        # GIF domains to filter (when user can't embed)
        self._gif_domains: List[str] = [
            "tenor.com",
            "giphy.com",
            "gfycat.com",
            "imgur.com/a/",  # imgur albums often contain gifs
            "i.imgur.com",   # direct imgur images/gifs
            "media.discordapp.net",
            "cdn.discordapp.com",
        ]

    # -------------------------------------------------------------------------
    # GIF Link Filter
    # -------------------------------------------------------------------------

    async def _check_gif_link_filter(self, message: discord.Message) -> bool:
        """
        Check and delete GIF links from users who can't embed.

        Deletes GIF links (tenor, giphy, gfycat) for:
        - Users under level 5 (don't have gif_permission_role_id)
        - Users with "Forbid: Embed Links" role

        Args:
            message: The message to check. Must have guild and Member author.

        Returns:
            True if message was deleted, False otherwise.
        """
        # Type narrowing - caller ensures these conditions
        if not isinstance(message.author, discord.Member):
            return False

        author: discord.Member = message.author
        content: str = message.content or ""

        if not content:
            return False

        # Check for GIF links FIRST (fast string check before role lookups)
        content_lower: str = content.lower()
        gif_reason: str | None = None

        # Check for known GIF domains
        for domain in self._gif_domains:
            if domain in content_lower:
                gif_reason = f"domain:{domain}"
                break

        # Check for .gif extension in URLs (catches any GIF link)
        if not gif_reason and ".gif" in content_lower:
            # Make sure it's in a URL context (has http or starts with domain pattern)
            if "http" in content_lower or "www." in content_lower:
                gif_reason = "extension:.gif"

        # No GIF link found - nothing to filter
        if not gif_reason:
            return False

        # GIF link found - now check if user is allowed to post it
        has_forbid_embeds: bool = any(
            r.name == "Forbid: Embed Links" for r in author.roles
        )

        # Check level 5 role - default to True if not configured (only filter forbid users)
        has_level_5: bool = True
        if self.config.gif_permission_role_id is not None:
            role = author.get_role(self.config.gif_permission_role_id)
            has_level_5 = role is not None

        # Debug logging to trace filter decisions
        logger.debug("GIF Filter Check", [
            ("User", f"{author.name} ({author.id})"),
            ("Match", gif_reason),
            ("Has Level 5", str(has_level_5)),
            ("Has Forbid Embeds", str(has_forbid_embeds)),
            ("Role ID Config", str(self.config.gif_permission_role_id)),
        ])

        # User can embed if they have level 5 AND don't have forbid embeds
        if has_level_5 and not has_forbid_embeds:
            return False

        # Determine filter reason
        filter_reason: str = "Forbid: Embed Links role" if has_forbid_embeds else "Under level 5"

        # Delete the message
        try:
            await block_from_snipe(
                message.id,
                reason="GIF link filter",
                user_id=author.id,
                channel_name=getattr(message.channel, 'name', 'Unknown'),
            )
            await message.delete()

            logger.tree("GIF LINK DELETED", [
                ("User", f"{author.name} ({author.id})"),
                ("Channel", f"#{getattr(message.channel, 'name', 'Unknown')}"),
                ("Match", gif_reason),
                ("Filter Reason", filter_reason),
            ], emoji="🖼️")

            return True

        except discord.Forbidden:
            logger.warning("GIF Link Delete Failed", [
                ("User", f"{author.name} ({author.id})"),
                ("Channel", f"#{getattr(message.channel, 'name', 'Unknown')}"),
                ("Error", "Missing permissions"),
            ])
            return False

        except discord.HTTPException as e:
            log_http_error(e, "GIF Link Delete", [
                ("User", f"{author.name} ({author.id})"),
                ("Channel", f"#{getattr(message.channel, 'name', 'Unknown')}"),
            ])
            return False

        except Exception as e:
            logger.error("GIF Link Filter Error", [
                ("User", f"{author.name} ({author.id})"),
                ("Channel", f"#{getattr(message.channel, 'name', 'Unknown')}"),
                ("Error", str(e)[:100]),
            ])
            return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Event handler for messages.

        DESIGN: Multi-path message routing:
        1. Case forum thread -> Check for reason replies
        2. Logs channel -> Parse mute embeds
        3. Polls channel -> Delete non-polls
        4. Ignored users -> Skip
        5. Muted users -> Track messages
        """
        # -----------------------------------------------------------------
        # Route 1: Case forum thread - check for reason/evidence replies
        # -----------------------------------------------------------------
        if (
            self.config.case_log_forum_id
            and isinstance(message.channel, discord.Thread)
            and message.channel.parent_id == self.config.case_log_forum_id
            and message.reference  # It's a reply
            and not message.author.bot
            and self.bot.case_log_service
        ):
            # Check for evidence reply first (if message has attachments)
            if message.attachments:
                evidence_handled = await self.bot.case_log_service.handle_evidence_reply(message)
                if evidence_handled:
                    return  # Evidence was captured, don't process as reason

            # Otherwise check for reason reply
            await self.bot.case_log_service.handle_reason_reply(message)

        # -----------------------------------------------------------------
        # Route 1.5: Ticket channel - track activity and store message
        # -----------------------------------------------------------------
        if (
            not message.author.bot
            and self.bot.ticket_service
            and self.bot.ticket_service.enabled
        ):
            await self.bot.ticket_service.handle_ticket_message(message)

        # -----------------------------------------------------------------
        # Route 2: Mod logs forum - parse mute embeds from threads
        # -----------------------------------------------------------------
        # Check if message is in a thread within the mod logs forum
        if (
            isinstance(message.channel, discord.Thread)
            and message.channel.parent_id == self.config.mod_logs_forum_id
            and message.embeds
        ):
            if self.bot.mute:
                await self.bot.mute.process_mute_embed(message)
            return

        # -----------------------------------------------------------------
        # Route 2: Polls-only channels - delete non-polls and poll results
        # -----------------------------------------------------------------
        if message.channel.id in self.config.polls_only_channel_ids:
            # Delete poll result messages ("X's poll has closed")
            if message.type == discord.MessageType.poll_result:
                try:
                    await message.delete()
                    # Use debug logging to reduce noise in high-volume poll channels
                    logger.debug("Poll Result Deleted", [("Channel", message.channel.name)])
                except discord.Forbidden:
                    logger.warning("No permission to delete poll result message")
                except discord.HTTPException as e:
                    log_http_error(e, "Poll Result Delete", [("Channel", message.channel.name)])
                return

            # Delete non-poll messages
            if getattr(message, 'poll', None) is None:
                try:
                    await message.delete()
                    # Use debug logging to reduce noise in high-volume poll channels
                    logger.debug("Non-Poll Deleted", [("Author", str(message.author)), ("Channel", message.channel.name)])
                except discord.Forbidden:
                    logger.warning("Non-Poll Delete Denied", [("Author", str(message.author))])
            return

        # -----------------------------------------------------------------
        # Route 3: DM handling (mod tracker alerts)
        # -----------------------------------------------------------------
        if isinstance(message.channel, discord.DMChannel):
            # Check if this is a tracked mod DMing the bot
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
            create_safe_task(self.bot._cache_message_attachments(message), "Attachment Cache")

        # -----------------------------------------------------------------
        # Cache message content for mod delete logging (OrderedDict LRU)
        # -----------------------------------------------------------------
        if not message.author.bot and message.guild:
            # Use lock for cache modification to prevent race conditions
            async with self.bot._message_cache_lock:
                # Evict oldest entries if at limit (O(1) with OrderedDict)
                while len(self.bot._message_cache) >= self.bot._message_cache_limit:
                    try:
                        self.bot._message_cache.popitem(last=False)  # Remove oldest
                    except KeyError:
                        break  # Cache was cleared by another task

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
        # GIF Link Filter: Delete GIF links from users who can't embed
        # When embed_links is forbidden, GIFs show as plain links - delete them
        # Applies to: users under level 5 OR users with "Forbid: Embed Links" role
        # -----------------------------------------------------------------
        if (
            message.guild
            and message.content
            and isinstance(message.author, discord.Member)
        ):
            if await self._check_gif_link_filter(message):
                return  # Message was deleted, stop processing

        # -----------------------------------------------------------------
        # Content Moderation Check (AI-powered religion talk detection)
        # -----------------------------------------------------------------
        if self.bot.content_moderation and self.bot.content_moderation.enabled and message.guild:
            result = await self.bot.content_moderation.check_message(message)
            if result and result.violation:
                await self.bot.content_moderation.handle_violation(message, result)
                # Don't return - let other handlers run (message may or may not be deleted)

        # -----------------------------------------------------------------
        # Skip: Bots and empty messages
        # -----------------------------------------------------------------
        if message.author.bot:
            return

        if not message.content:
            return

        # -----------------------------------------------------------------
        # Auto-Response: Partnership keyword detection (main server only)
        # -----------------------------------------------------------------
        if (
            message.guild
            and message.guild.id == self.config.main_guild_id
            and "partnership" in message.content.lower()
        ):
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
                # Check if in ticket channel (allow invites for partnership tickets)
                is_ticket_channel = (
                    self.config.ticket_category_id
                    and hasattr(message.channel, 'category_id')
                    and message.channel.category_id == self.config.ticket_category_id
                )
                # Check if user is owner (always exempt)
                is_owner = message.author.id == self.config.owner_id

                if is_ticket_channel:
                    logger.tree("INVITE LINK ALLOWED", [
                        ("User", f"{message.author.name} ({message.author.nick})" if hasattr(message.author, 'nick') and message.author.nick else message.author.name),
                        ("ID", str(message.author.id)),
                        ("Channel", f"#{message.channel.name}"),
                        ("Reason", "Ticket channel"),
                        ("Invite(s)", ", ".join(invite_matches)),
                    ], emoji="✅")
                    # Don't return - continue processing message
                elif is_owner:
                    logger.tree("INVITE LINK ALLOWED", [
                        ("User", f"{message.author.name} ({message.author.nick})" if hasattr(message.author, 'nick') and message.author.nick else message.author.name),
                        ("ID", str(message.author.id)),
                        ("Channel", f"#{message.channel.name}"),
                        ("Reason", "Owner"),
                        ("Invite(s)", ", ".join(invite_matches)),
                    ], emoji="✅")
                    # Don't return - continue processing message
                elif is_links_allowed_channel:
                    logger.tree("INVITE LINK ALLOWED", [
                        ("User", f"{message.author.name} ({message.author.nick})" if hasattr(message.author, 'nick') and message.author.nick else message.author.name),
                        ("ID", str(message.author.id)),
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
                            ("User", f"{message.author.name} ({message.author.nick})" if hasattr(message.author, 'nick') and message.author.nick else message.author.name),
                            ("ID", str(message.author.id)),
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
                                ("User", f"{message.author.name} ({message.author.nick})" if hasattr(message.author, 'nick') and message.author.nick else message.author.name),
                                ("ID", str(message.author.id)),
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

            # Track message history for context (OrderedDict LRU)
            async with self.bot._last_messages_lock:
                if message.author.id not in self.bot.last_messages:
                    # Evict oldest user if at limit
                    while len(self.bot.last_messages) >= self.bot._last_messages_limit:
                        try:
                            self.bot.last_messages.popitem(last=False)
                        except KeyError:
                            break  # Cache was cleared by another task
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

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """Track message deletions for tracked mods and logging service."""
        if message.author.bot:
            return

        # -----------------------------------------------------------------
        # Check if message was auto-deleted by bot (skip snipe cache)
        # This covers: content moderation, antispam, external invites, etc.
        # -----------------------------------------------------------------
        skip_snipe, block_reason = await should_block_snipe(message.id)
        if skip_snipe:
            # Log to dashboard (handles console logging too)
            if message.guild and hasattr(message.channel, 'name'):
                event_logger.log_message_delete(
                    guild=message.guild,
                    channel=message.channel,
                    author=message.author,
                    content=message.content,
                    moderator=message.guild.me,  # Bot is the moderator for auto-deletes
                )

            # Still run logging service and mod tracker
            if self.bot.logging_service and self.bot.logging_service.enabled:
                async with self.bot._attachment_cache_lock:
                    attachments = self.bot._attachment_cache.pop(message.id, None)
                await self.bot.logging_service.log_message_delete(message, attachments)

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
                    except (discord.NotFound, discord.HTTPException):
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
            return  # Skip snipe cache

        # Check if this is a "snipe clearer" (just dots like ".", "..", "...")
        # We'll skip saving to snipe cache but still log everything else
        skip_snipe_save = is_snipe_clearer(message.content)

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
                    "id": sticker.id,
                    "name": sticker.name,
                    "url": sticker.url,
                })

        # Get attachment bytes from cache BEFORE logging service pops it
        # Store as base64 in database for reliable /snipe display
        attachment_data = None
        if message.id in self.bot._attachment_cache:
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
        # Skip if this is a "snipe clearer" (dots only) - preserves previous real snipe
        if not skip_snipe_save:
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

        # Log to dashboard (handles console logging too)
        if message.guild and hasattr(message.channel, 'name'):
            event_logger.log_message_delete(
                guild=message.guild,
                channel=message.channel,
                author=message.author,
                content=message.content,
                attachments=attachment_names if attachment_names else None,
            )

        # -----------------------------------------------------------------
        # Logging Service: Message Delete
        # -----------------------------------------------------------------
        if self.bot.logging_service and self.bot.logging_service.enabled:
            # Use lock for cache modification to prevent race conditions
            async with self.bot._attachment_cache_lock:
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
                except (discord.NotFound, discord.HTTPException):
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

        # Build before/after attachment data (outside lock)
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

        # Use lock for cache modification to prevent race conditions
        async with self.bot._editsnipe_cache_lock:
            # Initialize deque if not exists, with LRU eviction
            if channel_id not in self.bot._editsnipe_cache:
                # Evict oldest channel if at limit
                while len(self.bot._editsnipe_cache) >= self.bot._editsnipe_channel_limit:
                    try:
                        self.bot._editsnipe_cache.popitem(last=False)
                    except KeyError:
                        break  # Cache was cleared by another task
                self.bot._editsnipe_cache[channel_id] = deque(maxlen=self.bot._editsnipe_limit)
            else:
                # Move to end (most recently used)
                self.bot._editsnipe_cache.move_to_end(channel_id)

            # Add to front of deque (most recent first)
            self.bot._editsnipe_cache[channel_id].appendleft(edit_data)

        # Log to dashboard events (handles console logging too)
        if before.guild and hasattr(before.channel, 'name'):
            event_logger.log_message_edit(
                guild=before.guild,
                channel=before.channel,
                author=before.author,
                before_content=before.content,
                after_content=after.content,
            )

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
                except (discord.NotFound, discord.HTTPException):
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

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        """
        Handle raw message deletions.

        Used for detecting ticket panel deletion (message may not be cached).
        """
        # Check if this is the ticket panel being deleted
        if self.bot.ticket_service and self.bot.ticket_service.enabled:
            await self.bot.ticket_service.handle_panel_deletion(payload.message_id)


__all__ = ["MessageEvents"]
