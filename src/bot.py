"""
Azab Discord Bot - Main Bot Class
==================================

Core Discord client for the Syria Discord server providing
AI-powered roasting of muted users (prisoners).

Features:
- AI-powered roasting of muted users
- Prisoner tracking with message batching
- Dynamic presence updates
- Polls-only channel enforcement
- Health check HTTP endpoint
- Mod activity tracking

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime
from typing import Optional, Dict, List
from collections import deque

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, is_developer, NY_TZ
from src.core.database import get_db


# =============================================================================
# AzabBot Class
# =============================================================================

class AzabBot(commands.Bot):
    """
    Main Discord bot class for Azab Prison Warden.

    DESIGN: Central orchestrator that:
    - Routes Discord events to appropriate handlers
    - Holds references to all services for cross-service communication
    - Manages bot lifecycle (startup, shutdown)
    - Tracks prisoner messages with intelligent batching

    SERVICE INITIALIZATION ORDER:
    1. setup_hook (before on_ready):
       - Command cog loading
       - Command tree syncing

    2. on_ready:
       - AI Service (OpenAI integration)
       - Prison Handler (mute/unmute tracking)
       - Mute Handler (embed parsing)
       - Presence Handler (status updates)
       - Health Check Server

    INTENTS REQUIRED:
    - message_content: Read prisoner messages for AI roasting
    - members: Track mute/unmute role changes
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self) -> None:
        """
        Initialize the Azab bot with necessary intents and configuration.

        DESIGN: Lazy initialization pattern - services are None until on_ready
        This prevents issues with Discord API calls before connection is established
        """
        # =================================================================
        # Load Configuration
        # DESIGN: Config loaded once at startup, cached globally
        # =================================================================
        self.config = get_config()

        # =================================================================
        # Setup Discord Intents
        # DESIGN: Minimal intents for security - only what we need
        # =================================================================
        intents = discord.Intents.default()
        intents.message_content = True  # Read prisoner messages
        intents.members = True          # Track mute role changes

        super().__init__(
            command_prefix="!",  # Not used - bot uses slash commands only
            intents=intents,
            help_command=None,
        )

        # =================================================================
        # Database Connection
        # DESIGN: Singleton pattern ensures single connection
        # =================================================================
        self.db = get_db()

        # =================================================================
        # Bot State
        # DESIGN: Tracks runtime state, persisted to database
        # =================================================================
        self.start_time: datetime = datetime.now()
        self.disabled: bool = False

        # =================================================================
        # Service Placeholders
        # DESIGN: Initialized in on_ready to ensure Discord connection first
        # =================================================================
        self.ai_service = None        # AIService - OpenAI roast generation
        self.prison_handler = None    # PrisonHandler - mute/unmute events
        self.mute_handler = None      # MuteHandler - parse mute embeds
        self.presence_handler = None  # PresenceHandler - dynamic status
        self.health_server = None     # HealthCheckServer - HTTP endpoint
        self.mute_scheduler = None    # MuteScheduler - auto-unmute service
        self.case_log_service = None  # CaseLogService - forum case logging
        self.mod_tracker = None       # ModTrackerService - mod activity tracking
        self.logging_service = None   # LoggingService - server activity logging
        self.webhook_alert_service = None  # WebhookAlertService - status alerts

        # =================================================================
        # Prisoner Rate Limiting
        # DESIGN: Prevents spam by batching rapid messages from prisoners
        # =================================================================
        self.prisoner_cooldowns: Dict[int, datetime] = {}
        self.prisoner_message_buffer: Dict[int, List[str]] = {}
        self.prisoner_pending_response: Dict[int, bool] = {}

        # =================================================================
        # Message History Tracking
        # DESIGN: Provides context for AI to reference previous messages
        # =================================================================
        self.last_messages: Dict[int, dict] = {}

        # =================================================================
        # Invite Cache
        # DESIGN: Track invites to identify which one was used on member join
        # =================================================================
        self._invite_cache: Dict[str, int] = {}  # code -> uses

        # =================================================================
        # Message Attachment Cache
        # DESIGN: Cache recent messages with attachments to preserve them
        # on deletion before Discord removes them
        # =================================================================
        self._attachment_cache: Dict[int, List[tuple]] = {}  # msg_id -> [(filename, data)]
        self._attachment_cache_limit: int = 500  # Max messages to cache

        # =================================================================
        # Message Content Cache (for mod delete logging)
        # DESIGN: Cache recent message content for audit log correlation
        # Stores content + metadata for context when content is unavailable
        # =================================================================
        self._message_cache: Dict[int, dict] = {}  # msg_id -> {author, content, channel_id, attachments, stickers, embeds, reply_to}
        self._message_cache_limit: int = 5000  # Max messages to cache (increased for better coverage)

        # =================================================================
        # Raid Detection
        # DESIGN: Track recent joins to detect potential raids
        # =================================================================
        self._recent_joins: deque = deque(maxlen=50)  # (timestamp, member) tuples
        self._raid_threshold: int = 10  # Members joining within window triggers alert
        self._raid_window: int = 30  # Time window in seconds
        self._last_raid_alert: Optional[datetime] = None  # Prevent alert spam

        # =================================================================
        # Ready State Guard
        # DESIGN: Prevents on_ready from running multiple times
        # Discord can fire on_ready multiple times (reconnects, etc.)
        # =================================================================
        self._ready_initialized: bool = False

        logger.info("Bot Instance Created")

    # =========================================================================
    # Event Handlers
    # =========================================================================

    async def setup_hook(self) -> None:
        """
        Setup hook called when bot is starting.

        DESIGN: Load cogs before on_ready so commands are available immediately.
        Command syncing happens here for faster startup.
        Uses COMMAND_COGS registry for dynamic cog loading.
        """
        # Load command cogs from registry
        from src.commands import COMMAND_COGS

        for cog in COMMAND_COGS:
            try:
                await self.load_extension(cog)
                logger.info(f"Cog Loaded: {cog.split('.')[-1]}")
            except Exception as e:
                logger.error("Failed to Load Cog", [
                    ("Cog", cog),
                    ("Error", str(e)),
                ])

        # Sync commands globally
        try:
            synced = await self.tree.sync()
            logger.tree("Commands Synced", [("Count", str(len(synced)))], emoji="✅")
        except Exception as e:
            logger.error("Command Sync Failed", [("Error", str(e))])

    async def on_ready(self) -> None:
        """
        Event handler called when bot is ready.

        NOTE: Discord can fire on_ready multiple times (reconnects, resume, etc.)
        We guard against re-initialization to prevent duplicate services.
        """
        if self._ready_initialized:
            logger.info("Bot Reconnected (skipping re-initialization)")
            return

        self._ready_initialized = True

        if not self.user:
            return

        logger.tree("BOT ONLINE", [
            ("Name", self.user.name),
            ("ID", str(self.user.id)),
            ("Guilds", str(len(self.guilds))),
        ], emoji="🚀")

        # Initialize services
        await self._init_services()

        # Initialize footer with cached avatar
        from src.utils.footer import init_footer
        await init_footer(self)

        # Load state from database
        self.disabled = not self.db.is_active()

        logger.tree("Bot State Loaded", [
            ("Active", str(not self.disabled)),
        ], emoji="ℹ️")

        # Set webhook for logger error notifications
        if self.config.error_webhook_url:
            logger.set_webhook(self.config.error_webhook_url)

        # Start presence updates
        if self.presence_handler:
            asyncio.create_task(self.presence_handler.start_presence_loop())

        # Cleanup polls channel
        await self._cleanup_polls_channel()

        # Cache server invites for tracking
        await self._cache_invites()

        logger.tree("AZAB READY", [
            ("AI Service", "Online" if self.ai_service else "Offline"),
            ("Prison Handler", "Ready" if self.prison_handler else "Missing"),
            ("Mute Scheduler", "Running" if self.mute_scheduler else "Stopped"),
            ("Case Log", "Enabled" if self.case_log_service and self.case_log_service.enabled else "Disabled"),
            ("Mod Tracker", "Enabled" if self.mod_tracker and self.mod_tracker.enabled else "Disabled"),
            ("Health Server", "Running" if self.health_server else "Stopped"),
            ("Webhook Alerts", "Enabled" if self.webhook_alert_service and self.webhook_alert_service.enabled else "Disabled"),
        ], emoji="🔥")

    async def _init_services(self) -> None:
        """
        Initialize all services after Discord connection is established.

        DESIGN: Services initialized in order of dependency.
        Each service logged for debugging startup issues.
        """
        try:
            # -----------------------------------------------------------------
            # AI Service - Core roast generation
            # -----------------------------------------------------------------
            from src.services.ai_service import AIService
            self.ai_service = AIService(self.config.openai_api_key)

            # -----------------------------------------------------------------
            # Prison Handler - Mute/unmute event handling
            # -----------------------------------------------------------------
            from src.handlers.prison_handler import PrisonHandler
            self.prison_handler = PrisonHandler(self, self.ai_service)
            logger.info("Prison Handler Initialized")

            # -----------------------------------------------------------------
            # Mute Handler - Parse mute embeds from logs channel
            # -----------------------------------------------------------------
            from src.handlers.mute_handler import MuteHandler
            self.mute_handler = MuteHandler(self.prison_handler)
            logger.info("Mute Handler Initialized")

            # -----------------------------------------------------------------
            # Presence Handler - Dynamic status updates
            # -----------------------------------------------------------------
            from src.handlers.presence_handler import PresenceHandler
            self.presence_handler = PresenceHandler(self)
            logger.info("Presence Handler Initialized")

            # -----------------------------------------------------------------
            # Health Check Server - HTTP monitoring endpoint
            # -----------------------------------------------------------------
            from src.core.health import HealthCheckServer
            self.health_server = HealthCheckServer(self)
            await self.health_server.start()

            # -----------------------------------------------------------------
            # Mute Scheduler - Automatic mute expiration service
            # -----------------------------------------------------------------
            from src.services.mute_scheduler import MuteScheduler
            self.mute_scheduler = MuteScheduler(self)
            await self.mute_scheduler.start()

            # -----------------------------------------------------------------
            # Case Log Service - Forum thread logging for mod cases
            # -----------------------------------------------------------------
            from src.services.case_log import CaseLogService
            self.case_log_service = CaseLogService(self)
            if self.case_log_service.enabled:
                logger.tree("Case Log Service Initialized", [
                    ("Forum ID", str(self.config.case_log_forum_id)),
                ], emoji="📝")
            else:
                logger.info("Case Log Service Disabled (no forum configured)")

            # -----------------------------------------------------------------
            # Mod Tracker Service - Track moderator activities
            # -----------------------------------------------------------------
            from src.services.mod_tracker import ModTrackerService
            self.mod_tracker = ModTrackerService(self)
            if self.mod_tracker.enabled:
                logger.tree("Mod Tracker Service Initialized", [
                    ("Server ID", str(self.config.mod_server_id)),
                    ("Forum ID", str(self.config.mod_tracker_forum_id)),
                    ("Role ID", str(self.config.mod_role_id)),
                ], emoji="👁️")
                # Auto-scan and create threads for all mods
                await self.mod_tracker.auto_scan_mods()
                # Start scheduled title updates at midnight EST
                await self.mod_tracker.start_title_update_scheduler()
                # Start inactivity checker
                await self.mod_tracker.start_inactivity_checker()
            else:
                logger.info("Mod Tracker Service Disabled (no config)")

            # -----------------------------------------------------------------
            # Logging Service - Server activity logging
            # -----------------------------------------------------------------
            from src.services.server_logs import LoggingService
            self.logging_service = LoggingService(self)
            if await self.logging_service.initialize():
                logger.tree("Logging Service Initialized", [
                    ("Forum ID", str(self.config.server_logs_forum_id)),
                    ("Threads", "15 categories"),
                ], emoji="📋")
            else:
                logger.info("Logging Service Disabled (no forum configured)")

            # -----------------------------------------------------------------
            # Webhook Alert Service - Status notifications
            # -----------------------------------------------------------------
            from src.services.webhook_alerts import get_alert_service
            self.webhook_alert_service = get_alert_service()
            self.webhook_alert_service.set_bot(self)
            await self.webhook_alert_service.send_startup_alert()
            await self.webhook_alert_service.start_hourly_alerts()

        except Exception as e:
            logger.error("Service Initialization Failed", [
                ("Error", str(e)),
            ])

    async def _cleanup_polls_channel(self) -> None:
        """
        Clean up non-poll messages from polls-only channel.

        DESIGN: Runs on startup to enforce channel rules.
        Deletes with rate limiting to avoid API spam.
        """
        if not self.config.permanent_polls_channel_id:
            return

        channel = self.get_channel(self.config.permanent_polls_channel_id)
        if not channel:
            return

        try:
            deleted = 0
            async for message in channel.history(limit=self.config.polls_cleanup_limit):
                if getattr(message, 'poll', None) is None:
                    try:
                        await message.delete()
                        deleted += 1
                        await asyncio.sleep(1.0)
                    except (discord.NotFound, discord.Forbidden):
                        pass

            if deleted > 0:
                logger.tree("Polls Channel Cleaned", [
                    ("Deleted", str(deleted)),
                ], emoji="🗑️")
        except Exception as e:
            logger.tree("Polls Cleanup Failed", [("Error", str(e))], emoji="⚠️")

    async def _cache_invites(self) -> None:
        """
        Cache all server invites for tracking which invite was used.

        DESIGN: Store invite codes and their use counts.
        On member join, compare to find which invite was used.
        """
        try:
            for guild in self.guilds:
                try:
                    invites = await guild.invites()
                    for invite in invites:
                        self._invite_cache[invite.code] = invite.uses or 0
                    logger.info(f"Cached {len(invites)} invites for {guild.name}")
                except discord.Forbidden:
                    pass  # No permission to view invites
        except Exception as e:
            logger.debug(f"Invite cache failed: {e}")

    async def _find_used_invite(self, guild: discord.Guild) -> Optional[tuple]:
        """
        Find which invite was used by comparing use counts.

        Returns:
            Tuple of (invite_code, inviter) or None if not found.
        """
        try:
            new_invites = await guild.invites()
            for invite in new_invites:
                old_uses = self._invite_cache.get(invite.code, 0)
                if invite.uses and invite.uses > old_uses:
                    # This invite was used
                    self._invite_cache[invite.code] = invite.uses
                    return (invite.code, invite.inviter)
                # Update cache
                self._invite_cache[invite.code] = invite.uses or 0
        except discord.Forbidden:
            pass
        except Exception as e:
            logger.debug(f"Find invite failed: {e}")
        return None

    async def _cache_message_attachments(self, message: discord.Message) -> None:
        """
        Download and cache message attachments for later retrieval.

        DESIGN: Caches attachment data so it can be included in delete logs
        after Discord removes the original files.
        """
        if not message.attachments:
            return

        # Limit cache size
        if len(self._attachment_cache) >= self._attachment_cache_limit:
            # Remove oldest entries
            oldest = list(self._attachment_cache.keys())[:100]
            for key in oldest:
                self._attachment_cache.pop(key, None)

        attachments = []
        for att in message.attachments:
            # Only cache small files (< 8MB)
            if att.size and att.size < 8 * 1024 * 1024:
                try:
                    data = await att.read()
                    attachments.append((att.filename, data))
                except Exception:
                    pass

        if attachments:
            self._attachment_cache[message.id] = attachments

    async def _check_raid_detection(self, member: discord.Member) -> None:
        """
        Check for potential raid by tracking join rate.

        DESIGN: Tracks recent joins and alerts if threshold exceeded.
        Prevents alert spam by limiting to once per 5 minutes.
        """
        from datetime import timedelta

        current_time = datetime.now()
        self._recent_joins.append((current_time, member))

        # Count joins within the time window
        cutoff_time = current_time - timedelta(seconds=self._raid_window)
        recent = [(t, m) for t, m in self._recent_joins if t >= cutoff_time]
        join_count = len(recent)

        # Check if raid threshold exceeded
        if join_count >= self._raid_threshold:
            # Prevent alert spam (only alert every 5 minutes)
            can_alert = True
            if self._last_raid_alert:
                time_since_alert = (current_time - self._last_raid_alert).total_seconds()
                if time_since_alert < 300:  # 5 minutes
                    can_alert = False

            if can_alert and self.logging_service:
                self._last_raid_alert = current_time
                recent_members = [m for _, m in recent]
                await self.logging_service.log_raid_alert(
                    join_count=join_count,
                    time_window=self._raid_window,
                    recent_members=recent_members,
                )

    # =========================================================================
    # Message Handling
    # =========================================================================

    def is_user_muted(self, member: discord.Member) -> bool:
        """Check if user has the muted role."""
        return any(role.id == self.config.muted_role_id for role in member.roles)

    async def on_message(self, message: discord.Message) -> None:
        """
        Event handler for messages.

        DESIGN: Multi-path message routing:
        1. Logs channel -> Parse mute embeds
        2. Polls channel -> Delete non-polls
        3. Ignored users -> Skip
        4. Muted users -> Roast with batching
        """
        # -----------------------------------------------------------------
        # Route 1: Logs channel - parse mute embeds
        # -----------------------------------------------------------------
        if message.channel.id == self.config.logs_channel_id and message.embeds:
            if self.mute_handler:
                await self.mute_handler.process_mute_embed(message)
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
                    logger.debug("Deleted Non-Poll Message", [
                        ("Author", str(message.author)),
                    ])
                except discord.Forbidden:
                    pass
            return

        # -----------------------------------------------------------------
        # Route 3: DM from tracked mod - alert
        # -----------------------------------------------------------------
        if isinstance(message.channel, discord.DMChannel):
            if self.mod_tracker and self.mod_tracker.is_tracked(message.author.id):
                await self.mod_tracker.alert_dm_attempt(
                    mod_id=message.author.id,
                    message_content=message.content or "(no text content)",
                )
            return  # Don't process DMs further

        # -----------------------------------------------------------------
        # Cache attachments for delete logging
        # -----------------------------------------------------------------
        if message.attachments and not message.author.bot:
            asyncio.create_task(self._cache_message_attachments(message))

        # -----------------------------------------------------------------
        # Cache message content for mod delete logging
        # -----------------------------------------------------------------
        if not message.author.bot and message.guild:
            # Limit cache size
            if len(self._message_cache) >= self._message_cache_limit:
                # Remove oldest entries (first 100)
                oldest = list(self._message_cache.keys())[:100]
                for key in oldest:
                    self._message_cache.pop(key, None)

            self._message_cache[message.id] = {
                "author": message.author,
                "content": message.content,
                "channel_id": message.channel.id,
                # Store metadata for context when content is empty
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
        # Skip: Ignored users
        # -----------------------------------------------------------------
        if self.db.is_user_ignored(message.author.id):
            return

        # -----------------------------------------------------------------
        # Skip: Bot disabled
        # -----------------------------------------------------------------
        if self.disabled:
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
            await self.db.log_message(
                message.author.id,
                str(message.author),
                message.content,
                message.channel.id,
                message.guild.id,
            )

            # Track message history for AI context
            if message.author.id not in self.last_messages:
                self.last_messages[message.author.id] = {
                    "messages": deque(maxlen=self.config.message_history_size),
                    "channel_id": message.channel.id,
                }
            self.last_messages[message.author.id]["messages"].append(message.content)
            self.last_messages[message.author.id]["channel_id"] = message.channel.id

            # Cache messages from tracked mods (for deleted message attachments)
            if self.mod_tracker and self.mod_tracker.is_tracked(message.author.id):
                if message.attachments:
                    await self.mod_tracker.cache_message(message)

        # -----------------------------------------------------------------
        # Prisoner Response - DISABLED
        # -----------------------------------------------------------------
        # AI prisoner roasting is currently disabled
        return

    async def _handle_prisoner_message(self, message: discord.Message) -> None:
        """
        Handle message from muted user with intelligent batching.

        DESIGN: Batches rapid messages to avoid spam and save API costs.
        Cooldown prevents responding too frequently to same prisoner.
        """
        user_id = message.author.id
        current_time = datetime.now()

        # Check cooldown
        if user_id in self.prisoner_cooldowns:
            last_response = self.prisoner_cooldowns[user_id]
            elapsed = (current_time - last_response).total_seconds()

            if elapsed < self.config.prisoner_cooldown_seconds:
                # Buffer message for later batch
                if user_id not in self.prisoner_message_buffer:
                    self.prisoner_message_buffer[user_id] = []
                self.prisoner_message_buffer[user_id].append(message.content)
                return

        # Buffer message
        if user_id not in self.prisoner_message_buffer:
            self.prisoner_message_buffer[user_id] = []
        self.prisoner_message_buffer[user_id].append(message.content)

        # Check if response already pending
        if self.prisoner_pending_response.get(user_id, False):
            return

        # Mark pending and schedule response
        self.prisoner_pending_response[user_id] = True
        asyncio.create_task(self._send_batched_response(message))

    async def _send_batched_response(self, message: discord.Message) -> None:
        """
        Send batched response to prisoner after collection delay.

        DESIGN: Waits briefly to collect multiple messages, then responds once.
        """
        user_id = message.author.id

        try:
            # Wait to collect more messages
            await asyncio.sleep(self.config.prisoner_batch_delay_seconds)

            # Get buffered messages
            messages = self.prisoner_message_buffer.get(user_id, [])
            if not messages:
                self.prisoner_pending_response[user_id] = False
                return

            # Clear buffer
            self.prisoner_message_buffer[user_id] = []
            self.prisoner_pending_response[user_id] = False

            # Build context from batched messages
            if len(messages) == 1:
                context = messages[0]
            else:
                context = f"User sent {len(messages)} messages: {' | '.join(messages)}"

            async with message.channel.typing():
                # Get mute info for context
                mute_reason = None
                if self.prison_handler:
                    mute_reason = self.prison_handler.mute_reasons.get(user_id)

                mute_duration = await self.db.get_current_mute_duration(user_id)

                # Get message history for AI context
                history = []
                if user_id in self.last_messages:
                    history = list(self.last_messages[user_id]["messages"])

                response = await self.ai_service.generate_response(
                    context,
                    message.author.display_name,
                    True,  # is_muted
                    mute_reason,
                    history[-1] if history else None,
                    user_id=user_id,
                    mute_duration_minutes=mute_duration,
                    message_history=history,
                )

                await message.channel.send(f"{message.author.mention} {response}")

                # Set cooldown
                self.prisoner_cooldowns[user_id] = datetime.now()

                logger.tree("PRISONER ROASTED", [
                    ("User", str(message.author)),
                    ("Messages Batched", str(len(messages))),
                    ("Mute Reason", mute_reason or "Unknown"),
                    ("Duration", f"{mute_duration}min"),
                ], emoji="😈")

        except Exception as e:
            self.prisoner_pending_response[user_id] = False
            logger.error("Prisoner Response Failed", [
                ("User", str(message.author)),
                ("Error", str(e)),
            ])

    async def _handle_normal_message(self, message: discord.Message, is_muted: bool) -> None:
        """Handle normal message response (non-muted user)."""
        async with message.channel.typing():
            mute_reason = None
            if self.prison_handler:
                mute_reason = self.prison_handler.mute_reasons.get(message.author.id)

            response = await self.ai_service.generate_response(
                message.content,
                message.author.display_name,
                is_muted,
                mute_reason,
                None,
                user_id=message.author.id,
                mute_duration_minutes=0,
            )

            await message.reply(response)

    # =========================================================================
    # Member Events
    # =========================================================================

    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """
        Handle member role changes for mute detection and mod tracking.

        DESIGN: Watches for muted role being added/removed to trigger
        prison handler events. Also tracks mod avatar/name/role changes.
        """
        if self.disabled:
            return

        # -----------------------------------------------------------------
        # Mute Role Detection
        # -----------------------------------------------------------------
        had_muted = any(r.id == self.config.muted_role_id for r in before.roles)
        has_muted = any(r.id == self.config.muted_role_id for r in after.roles)

        if not had_muted and has_muted:
            # New prisoner arrived
            logger.tree("NEW PRISONER DETECTED", [
                ("User", str(after)),
                ("User ID", str(after.id)),
            ], emoji="⛓️")

            if self.prison_handler:
                await self.prison_handler.handle_new_prisoner(after)

        elif had_muted and not has_muted:
            # Prisoner released
            logger.tree("PRISONER RELEASED", [
                ("User", str(after)),
                ("User ID", str(after.id)),
            ], emoji="🔓")

            if self.prison_handler:
                await self.prison_handler.handle_prisoner_release(after)

            # Clean up rate limiting state
            self.prisoner_cooldowns.pop(after.id, None)
            self.prisoner_message_buffer.pop(after.id, None)
            self.prisoner_pending_response.pop(after.id, None)

        # -----------------------------------------------------------------
        # Mod Tracker: Auto-track on role add/remove
        # -----------------------------------------------------------------
        if self.mod_tracker and self.mod_tracker.enabled and self.config.mod_role_id:
            had_mod_role = any(r.id == self.config.mod_role_id for r in before.roles)
            has_mod_role = any(r.id == self.config.mod_role_id for r in after.roles)

            # New mod added - start tracking
            if not had_mod_role and has_mod_role:
                if not self.mod_tracker.is_tracked(after.id):
                    await self.mod_tracker.add_tracked_mod(after)

            # Mod removed - stop tracking
            elif had_mod_role and not has_mod_role:
                if self.mod_tracker.is_tracked(after.id):
                    await self.mod_tracker.remove_tracked_mod(after.id)

        # -----------------------------------------------------------------
        # Mod Tracker: Avatar, Name, Role Changes
        # -----------------------------------------------------------------
        if self.mod_tracker and self.mod_tracker.is_tracked(after.id):
            # Avatar change
            if before.avatar != after.avatar:
                await self.mod_tracker.log_avatar_change(
                    after,
                    before.display_avatar if before.avatar else None,
                    after.display_avatar if after.avatar else None,
                )

            # Username change
            if before.name != after.name:
                await self.mod_tracker.log_name_change(
                    after, "Username", before.name, after.name
                )

            # Display name change
            if before.display_name != after.display_name:
                await self.mod_tracker.log_name_change(
                    after, "Display Name", before.display_name, after.display_name
                )

            # Role changes
            added_roles = [r for r in after.roles if r not in before.roles]
            removed_roles = [r for r in before.roles if r not in after.roles]
            if added_roles or removed_roles:
                await self.mod_tracker.log_role_change(after, added_roles, removed_roles)

        # -----------------------------------------------------------------
        # Logging Service: Role Changes
        # -----------------------------------------------------------------
        if self.logging_service and self.logging_service.enabled:
            added_roles = [r for r in after.roles if r not in before.roles]
            removed_roles = [r for r in before.roles if r not in after.roles]
            for role in added_roles:
                await self.logging_service.log_role_add(after, role)
            for role in removed_roles:
                await self.logging_service.log_role_remove(after, role)

            # Nickname changes
            if before.nick != after.nick:
                await self.logging_service.log_nickname_change(after, before.nick, after.nick)
                # Save to nickname history database
                self.db.save_nickname_change(
                    user_id=after.id,
                    guild_id=after.guild.id,
                    old_nickname=before.nick,
                    new_nickname=after.nick,
                    changed_by=None,  # Self-change or unknown
                )

            # Server boost detection
            if before.premium_since is None and after.premium_since is not None:
                # Member started boosting
                await self.logging_service.log_boost(after)
            elif before.premium_since is not None and after.premium_since is None:
                # Member stopped boosting
                await self.logging_service.log_unboost(after)

            # Member verification (passed membership screening)
            if before.pending and not after.pending:
                await self.logging_service.log_member_verification(after)

    async def on_resumed(self) -> None:
        """Event handler for bot resuming connection after disconnect."""
        logger.info("Bot Connection Resumed")

    # =========================================================================
    # Mod Tracker Events - Personal Activity
    # =========================================================================

    async def on_message_delete(self, message: discord.Message) -> None:
        """Track message deletions for tracked mods and logging service."""
        if message.author.bot:
            return

        # -----------------------------------------------------------------
        # Logging Service: Message Delete
        # -----------------------------------------------------------------
        if self.logging_service and self.logging_service.enabled:
            # Get cached attachments (already downloaded before deletion)
            attachments = self._attachment_cache.pop(message.id, None)
            await self.logging_service.log_message_delete(message, attachments)

        # -----------------------------------------------------------------
        # Mod Tracker: Message Delete
        # -----------------------------------------------------------------
        if self.mod_tracker and self.mod_tracker.is_tracked(message.author.id):
            # Get reply info if this was a reply
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

            await self.mod_tracker.log_message_delete(
                mod_id=message.author.id,
                channel=message.channel,
                content=message.content or "",
                attachments=message.attachments,
                message_id=message.id,
                reply_to_user=reply_to_user,
                reply_to_id=reply_to_id,
            )

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        """Track message edits for tracked mods and logging service."""
        if before.author.bot:
            return

        # Skip if content didn't change (embed updates, etc.)
        if before.content == after.content:
            return

        # -----------------------------------------------------------------
        # Logging Service: Message Edit
        # -----------------------------------------------------------------
        if self.logging_service and self.logging_service.enabled:
            await self.logging_service.log_message_edit(before, after)

        # -----------------------------------------------------------------
        # Mod Tracker: Message Edit
        # -----------------------------------------------------------------
        if self.mod_tracker and self.mod_tracker.is_tracked(before.author.id):
            # Get reply info if this was a reply
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

            await self.mod_tracker.log_message_edit(
                mod=before.author,
                channel=before.channel,
                old_content=before.content or "",
                new_content=after.content or "",
                jump_url=after.jump_url,
                reply_to_user=reply_to_user,
                reply_to_id=reply_to_id,
            )

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Track voice channel activity for tracked mods."""
        if not self.mod_tracker or not self.mod_tracker.is_tracked(member.id):
            return

        # Joined a voice channel
        if before.channel is None and after.channel is not None:
            await self.mod_tracker.log_voice_activity(
                mod=member,
                action="Joined",
                channel=after.channel,
            )

        # Left a voice channel
        elif before.channel is not None and after.channel is None:
            await self.mod_tracker.log_voice_activity(
                mod=member,
                action="Left",
                channel=before.channel,
            )

        # Moved between voice channels
        elif before.channel != after.channel:
            await self.mod_tracker.log_voice_activity(
                mod=member,
                action="Moved",
                from_channel=before.channel,
                to_channel=after.channel,
            )

        # -----------------------------------------------------------------
        # Logging Service - Voice Activity
        # -----------------------------------------------------------------
        if self.logging_service and self.logging_service.enabled:
            if before.channel is None and after.channel is not None:
                await self.logging_service.log_voice_join(member, after.channel)
            elif before.channel is not None and after.channel is None:
                await self.logging_service.log_voice_leave(member, before.channel)
            elif before.channel != after.channel and before.channel and after.channel:
                await self.logging_service.log_voice_move(member, before.channel, after.channel)

            # Stage speaker changes
            if after.channel and isinstance(after.channel, discord.StageChannel):
                # Became a speaker (suppress changed from True to False)
                if before.suppress and not after.suppress:
                    await self.logging_service.log_stage_speaker(member, after.channel, True)
                # Stopped being a speaker (suppress changed from False to True)
                elif not before.suppress and after.suppress:
                    await self.logging_service.log_stage_speaker(member, after.channel, False)

    # =========================================================================
    # Logging Service Events
    # =========================================================================

    async def on_member_join(self, member: discord.Member) -> None:
        """Log member joins with invite tracking and raid detection."""
        if self.logging_service and self.logging_service.enabled:
            # Find which invite was used
            invite_info = await self._find_used_invite(member.guild)
            invite_code = invite_info[0] if invite_info else None
            inviter = invite_info[1] if invite_info else None
            await self.logging_service.log_member_join(member, invite_code, inviter)

            # -----------------------------------------------------------------
            # Raid Detection
            # -----------------------------------------------------------------
            await self._check_raid_detection(member)

    async def on_member_remove(self, member: discord.Member) -> None:
        """Log member leaves."""
        if self.logging_service and self.logging_service.enabled:
            await self.logging_service.log_member_leave(member)

    async def on_user_update(self, before: discord.User, after: discord.User) -> None:
        """Log user avatar and username changes."""
        if not self.logging_service or not self.logging_service.enabled:
            return

        # Avatar change
        if before.avatar != after.avatar:
            before_url = before.display_avatar.url if before.avatar else None
            after_url = after.display_avatar.url if after.avatar else None
            await self.logging_service.log_avatar_change(after, before_url, after_url)

        # Username change
        if before.name != after.name:
            await self.logging_service.log_username_change(after, before.name, after.name)

    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        """Log channel creations."""
        if self.logging_service and self.logging_service.enabled:
            await self.logging_service.log_channel_create(channel)

    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """Log channel deletions."""
        if self.logging_service and self.logging_service.enabled:
            await self.logging_service.log_channel_delete(channel.name, str(channel.type))

    async def on_guild_role_create(self, role: discord.Role) -> None:
        """Log role creations."""
        if self.logging_service and self.logging_service.enabled:
            await self.logging_service.log_role_create(role)

    async def on_guild_role_delete(self, role: discord.Role) -> None:
        """Log role deletions."""
        if self.logging_service and self.logging_service.enabled:
            await self.logging_service.log_role_delete(role.name)

    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before: tuple,
        after: tuple,
    ) -> None:
        """Log emoji changes."""
        if not self.logging_service or not self.logging_service.enabled:
            return

        before_ids = {e.id for e in before}
        after_ids = {e.id for e in after}

        # New emojis
        for emoji in after:
            if emoji.id not in before_ids:
                await self.logging_service.log_emoji_create(emoji)

        # Deleted emojis
        for emoji in before:
            if emoji.id not in after_ids:
                await self.logging_service.log_emoji_delete(emoji.name)

    async def on_guild_stickers_update(
        self,
        guild: discord.Guild,
        before: tuple,
        after: tuple,
    ) -> None:
        """Log sticker changes."""
        if not self.logging_service or not self.logging_service.enabled:
            return

        before_ids = {s.id for s in before}
        after_ids = {s.id for s in after}

        # New stickers
        for sticker in after:
            if sticker.id not in before_ids:
                await self.logging_service.log_sticker_create(sticker)

        # Deleted stickers
        for sticker in before:
            if sticker.id not in after_ids:
                await self.logging_service.log_sticker_delete(sticker.name)

    # =========================================================================
    # Invite Tracking
    # =========================================================================

    async def on_invite_create(self, invite: discord.Invite) -> None:
        """Update invite cache and log when new invite is created."""
        self._invite_cache[invite.code] = invite.uses or 0

        # Log the invite creation
        if self.logging_service and self.logging_service.enabled:
            await self.logging_service.log_invite_create(invite)

    async def on_invite_delete(self, invite: discord.Invite) -> None:
        """Update invite cache and log when invite is deleted."""
        uses = self._invite_cache.pop(invite.code, None)

        # Log the invite deletion
        if self.logging_service and self.logging_service.enabled:
            channel_name = invite.channel.name if invite.channel else "Unknown"
            await self.logging_service.log_invite_delete(
                invite_code=invite.code,
                channel_name=channel_name,
                uses=uses,
            )

    # =========================================================================
    # Thread Events
    # =========================================================================

    async def on_thread_create(self, thread: discord.Thread) -> None:
        """Log thread and forum post creations."""
        if self.logging_service and self.logging_service.enabled:
            creator = thread.owner

            # Check if this is a forum post (parent is ForumChannel)
            if thread.parent and isinstance(thread.parent, discord.ForumChannel):
                await self.logging_service.log_forum_post_create(thread, creator)
            else:
                await self.logging_service.log_thread_create(thread, creator)

    async def on_thread_delete(self, thread: discord.Thread) -> None:
        """Log thread deletions."""
        if self.logging_service and self.logging_service.enabled:
            parent_name = thread.parent.name if thread.parent else "Unknown"
            await self.logging_service.log_thread_delete(thread.name, parent_name)

    async def on_thread_update(self, before: discord.Thread, after: discord.Thread) -> None:
        """Log thread archive/unarchive and lock/unlock."""
        if not self.logging_service or not self.logging_service.enabled:
            return

        # Archive state changed
        if before.archived != after.archived:
            await self.logging_service.log_thread_archive(after, after.archived)

        # Lock state changed
        if before.locked != after.locked:
            await self.logging_service.log_thread_lock(after, after.locked)

    # =========================================================================
    # AutoMod Events
    # =========================================================================

    async def on_automod_action(self, execution: discord.AutoModAction) -> None:
        """Log AutoMod actions."""
        if not self.logging_service or not self.logging_service.enabled:
            return

        try:
            # Get the user
            member = execution.member
            if not member and execution.user_id:
                guild = self.get_guild(execution.guild_id)
                if guild:
                    member = guild.get_member(execution.user_id)

            if not member:
                return

            # Get the rule name
            rule_name = "Unknown Rule"
            if execution.rule_id:
                try:
                    guild = self.get_guild(execution.guild_id)
                    if guild:
                        rule = await guild.fetch_automod_rule(execution.rule_id)
                        rule_name = rule.name
                except Exception:
                    pass

            # Get channel
            channel = None
            if execution.channel_id:
                channel = self.get_channel(execution.channel_id)

            # Get action type
            action_type = str(execution.action.type.name) if execution.action else "unknown"

            # Get matched content
            content = execution.content
            matched = execution.matched_keyword

            # Log based on action type
            if execution.action and execution.action.type == discord.AutoModRuleActionType.block_message:
                await self.logging_service.log_automod_block(
                    rule_name=rule_name,
                    user=member,
                    channel=channel,
                    content=content,
                    matched_keyword=matched,
                )
            else:
                await self.logging_service.log_automod_action(
                    rule_name=rule_name,
                    action_type=action_type,
                    user=member,
                    channel=channel,
                    content=content,
                    matched_keyword=matched,
                )
        except Exception as e:
            logger.debug(f"AutoMod log failed: {e}")

    # =========================================================================
    # Scheduled Event Events
    # =========================================================================

    async def on_scheduled_event_create(self, event: discord.ScheduledEvent) -> None:
        """Log scheduled event creations."""
        if self.logging_service and self.logging_service.enabled:
            creator = event.creator
            await self.logging_service.log_event_create(event, creator)

    async def on_scheduled_event_delete(self, event: discord.ScheduledEvent) -> None:
        """Log scheduled event deletions."""
        if self.logging_service and self.logging_service.enabled:
            await self.logging_service.log_event_delete(event.name)

    async def on_scheduled_event_update(
        self,
        before: discord.ScheduledEvent,
        after: discord.ScheduledEvent,
    ) -> None:
        """Log scheduled event updates and status changes."""
        if not self.logging_service or not self.logging_service.enabled:
            return

        # Event started
        if before.status != after.status:
            if after.status == discord.EventStatus.active:
                await self.logging_service.log_event_start(after)
            elif after.status in (discord.EventStatus.completed, discord.EventStatus.cancelled):
                await self.logging_service.log_event_end(after)
            return

        # Other changes
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
            await self.logging_service.log_event_update(after, ", ".join(changes))

    # =========================================================================
    # Reaction Events
    # =========================================================================

    async def on_reaction_add(
        self,
        reaction: discord.Reaction,
        user: discord.Member | discord.User,
    ) -> None:
        """Log reaction additions."""
        # Skip bots and DMs
        if user.bot or not isinstance(user, discord.Member):
            return

        if self.logging_service and self.logging_service.enabled:
            await self.logging_service.log_reaction_add(reaction, user, reaction.message)

    async def on_reaction_remove(
        self,
        reaction: discord.Reaction,
        user: discord.Member | discord.User,
    ) -> None:
        """Log reaction removals."""
        # Skip bots and DMs
        if user.bot or not isinstance(user, discord.Member):
            return

        if self.logging_service and self.logging_service.enabled:
            await self.logging_service.log_reaction_remove(reaction, user, reaction.message)

    async def on_reaction_clear(
        self,
        message: discord.Message,
        reactions: list,
    ) -> None:
        """Log all reactions being cleared."""
        if self.logging_service and self.logging_service.enabled:
            await self.logging_service.log_reaction_clear(message)

    # =========================================================================
    # Stage Events
    # =========================================================================

    async def on_stage_instance_create(self, stage: discord.StageInstance) -> None:
        """Log stage instance starting."""
        if self.logging_service and self.logging_service.enabled:
            await self.logging_service.log_stage_start(stage)

    async def on_stage_instance_delete(self, stage: discord.StageInstance) -> None:
        """Log stage instance ending."""
        if self.logging_service and self.logging_service.enabled:
            channel_name = stage.channel.name if stage.channel else "Unknown"
            await self.logging_service.log_stage_end(channel_name, stage.topic)

    async def on_stage_instance_update(
        self,
        before: discord.StageInstance,
        after: discord.StageInstance,
    ) -> None:
        """Log stage instance updates."""
        if not self.logging_service or not self.logging_service.enabled:
            return

        changes = []
        if before.topic != after.topic:
            changes.append(f"Topic: {before.topic} → {after.topic}")
        if before.privacy_level != after.privacy_level:
            changes.append(f"Privacy: {after.privacy_level.name}")

        if changes:
            await self.logging_service.log_stage_update(after, ", ".join(changes))

    # =========================================================================
    # Mod Tracker Events - Audit Log Based
    # =========================================================================

    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry) -> None:
        """
        Track mod actions via audit log entries.

        DESIGN: Uses audit log to identify which mod performed actions.
        Routes events to both mod_tracker and logging_service.
        """
        # -----------------------------------------------------------------
        # Logging Service: Route all audit log events
        # -----------------------------------------------------------------
        await self._log_audit_event(entry)

        # -----------------------------------------------------------------
        # Mod Tracker: Only track if mod tracker is enabled
        # -----------------------------------------------------------------
        if not self.mod_tracker or not self.mod_tracker.enabled:
            return

        # Get the mod who performed the action
        mod_id = entry.user_id
        if not mod_id or not self.mod_tracker.is_tracked(mod_id):
            return

        try:
            # Timeout (member update with communication_disabled_until)
            if entry.action == discord.AuditLogAction.member_update:
                # Check for new timeout
                if hasattr(entry.after, 'timed_out_until') and entry.after.timed_out_until:
                    await self.mod_tracker.log_timeout(
                        mod_id=mod_id,
                        target=entry.target,
                        until=entry.after.timed_out_until,
                        reason=entry.reason,
                    )

                # Check for timeout removal (had timeout, now doesn't)
                old_timeout = getattr(entry.before, 'timed_out_until', None)
                new_timeout = getattr(entry.after, 'timed_out_until', None)
                if old_timeout and not new_timeout:
                    # Timeout was removed early
                    await self.mod_tracker.log_timeout_remove(
                        mod_id=mod_id,
                        target=entry.target,
                        original_until=old_timeout,
                    )

            # Kick
            elif entry.action == discord.AuditLogAction.kick:
                # Check if kicked target is a bot
                if entry.target and entry.target.bot:
                    await self.mod_tracker.log_bot_remove(
                        mod_id=mod_id,
                        bot_name=entry.target.name,
                        bot_id=entry.target.id,
                    )
                else:
                    await self.mod_tracker.log_kick(
                        mod_id=mod_id,
                        target=entry.target,
                        reason=entry.reason,
                    )

            # Ban
            elif entry.action == discord.AuditLogAction.ban:
                await self.mod_tracker.log_ban(
                    mod_id=mod_id,
                    target=entry.target,
                    reason=entry.reason,
                )

            # Unban
            elif entry.action == discord.AuditLogAction.unban:
                await self.mod_tracker.log_unban(
                    mod_id=mod_id,
                    target=entry.target,
                    reason=entry.reason,
                )

            # Channel create
            elif entry.action == discord.AuditLogAction.channel_create:
                if entry.target:
                    await self.mod_tracker.log_channel_create(
                        mod_id=mod_id,
                        channel=entry.target,
                    )

            # Channel delete
            elif entry.action == discord.AuditLogAction.channel_delete:
                channel_name = getattr(entry.before, 'name', 'Unknown')
                channel_type = str(getattr(entry.target, 'type', 'Unknown'))
                await self.mod_tracker.log_channel_delete(
                    mod_id=mod_id,
                    channel_name=channel_name,
                    channel_type=channel_type,
                )

            # Channel update
            elif entry.action == discord.AuditLogAction.channel_update:
                if entry.target:
                    # Check for slowmode change
                    if hasattr(entry.before, 'slowmode_delay') and hasattr(entry.after, 'slowmode_delay'):
                        if entry.before.slowmode_delay != entry.after.slowmode_delay:
                            await self.mod_tracker.log_slowmode_change(
                                mod_id=mod_id,
                                channel=entry.target,
                                old_delay=entry.before.slowmode_delay or 0,
                                new_delay=entry.after.slowmode_delay or 0,
                            )

                    # Check for forum tag changes
                    if isinstance(entry.target, discord.ForumChannel):
                        old_tags = getattr(entry.before, 'available_tags', []) or []
                        new_tags = getattr(entry.after, 'available_tags', []) or []
                        old_tag_names = {t.name for t in old_tags}
                        new_tag_names = {t.name for t in new_tags}

                        # Detect added tags
                        for tag_name in new_tag_names - old_tag_names:
                            await self.mod_tracker.log_forum_tag_create(
                                mod_id=mod_id,
                                forum=entry.target,
                                tag_name=tag_name,
                            )

                        # Detect removed tags
                        for tag_name in old_tag_names - new_tag_names:
                            await self.mod_tracker.log_forum_tag_delete(
                                mod_id=mod_id,
                                forum=entry.target,
                                tag_name=tag_name,
                            )

                        # Detect renamed tags (name in old but not new, different count)
                        if len(old_tags) == len(new_tags):
                            for old_tag, new_tag in zip(
                                sorted(old_tags, key=lambda t: t.id),
                                sorted(new_tags, key=lambda t: t.id)
                            ):
                                if old_tag.id == new_tag.id and old_tag.name != new_tag.name:
                                    await self.mod_tracker.log_forum_tag_update(
                                        mod_id=mod_id,
                                        forum=entry.target,
                                        old_name=old_tag.name,
                                        new_name=new_tag.name,
                                    )

                    # Log other channel changes
                    changes = []
                    if hasattr(entry.before, 'name') and hasattr(entry.after, 'name'):
                        if entry.before.name != entry.after.name:
                            changes.append(f"Name: {entry.before.name} → {entry.after.name}")
                    if hasattr(entry.before, 'topic') and hasattr(entry.after, 'topic'):
                        if entry.before.topic != entry.after.topic:
                            changes.append("Topic changed")
                    if changes:
                        await self.mod_tracker.log_channel_update(
                            mod_id=mod_id,
                            channel=entry.target,
                            changes=", ".join(changes) if changes else "Settings updated",
                        )

            # Role create
            elif entry.action == discord.AuditLogAction.role_create:
                if entry.target:
                    await self.mod_tracker.log_role_create(
                        mod_id=mod_id,
                        role=entry.target,
                    )

            # Role delete
            elif entry.action == discord.AuditLogAction.role_delete:
                role_name = getattr(entry.before, 'name', 'Unknown')
                await self.mod_tracker.log_role_delete(
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

                    # Check for role icon changes
                    old_icon = getattr(entry.before, 'icon', None)
                    new_icon = getattr(entry.after, 'icon', None)
                    if old_icon != new_icon:
                        if old_icon is None and new_icon is not None:
                            await self.mod_tracker.log_role_icon_change(
                                mod_id=mod_id,
                                role=entry.target,
                                action="added",
                            )
                        elif old_icon is not None and new_icon is None:
                            await self.mod_tracker.log_role_icon_change(
                                mod_id=mod_id,
                                role=entry.target,
                                action="removed",
                            )
                        else:
                            await self.mod_tracker.log_role_icon_change(
                                mod_id=mod_id,
                                role=entry.target,
                                action="changed",
                            )

                    if changes:
                        await self.mod_tracker.log_role_update(
                            mod_id=mod_id,
                            role=entry.target,
                            changes=", ".join(changes) if changes else "Settings updated",
                        )

            # Message pin/unpin
            elif entry.action == discord.AuditLogAction.message_pin:
                if entry.target and hasattr(entry.extra, 'channel'):
                    try:
                        channel = entry.extra.channel
                        message = await channel.fetch_message(entry.extra.message_id)
                        await self.mod_tracker.log_message_pin(
                            mod_id=mod_id,
                            channel=channel,
                            message=message,
                            pinned=True,
                        )
                    except Exception:
                        pass

            elif entry.action == discord.AuditLogAction.message_unpin:
                if entry.target and hasattr(entry.extra, 'channel'):
                    try:
                        channel = entry.extra.channel
                        message = await channel.fetch_message(entry.extra.message_id)
                        await self.mod_tracker.log_message_pin(
                            mod_id=mod_id,
                            channel=channel,
                            message=message,
                            pinned=False,
                        )
                    except Exception:
                        pass

            # Emoji create
            elif entry.action == discord.AuditLogAction.emoji_create:
                if entry.target:
                    await self.mod_tracker.log_emoji_create(
                        mod_id=mod_id,
                        emoji=entry.target,
                    )

            # Emoji delete
            elif entry.action == discord.AuditLogAction.emoji_delete:
                emoji_name = getattr(entry.before, 'name', 'Unknown')
                await self.mod_tracker.log_emoji_delete(
                    mod_id=mod_id,
                    emoji_name=emoji_name,
                )

            # Webhook create
            elif entry.action == discord.AuditLogAction.webhook_create:
                webhook_name = getattr(entry.target, 'name', 'Unknown')
                channel_name = getattr(entry.extra, 'channel', None)
                channel_name = channel_name.name if channel_name else "Unknown"
                await self.mod_tracker.log_webhook_create(
                    mod_id=mod_id,
                    webhook_name=webhook_name,
                    channel_name=channel_name,
                )

            # Webhook delete
            elif entry.action == discord.AuditLogAction.webhook_delete:
                webhook_name = getattr(entry.before, 'name', 'Unknown')
                channel_name = "Unknown"
                await self.mod_tracker.log_webhook_delete(
                    mod_id=mod_id,
                    webhook_name=webhook_name,
                    channel_name=channel_name,
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

                # Check for verification level change
                if hasattr(entry.before, 'verification_level') and hasattr(entry.after, 'verification_level'):
                    if entry.before.verification_level != entry.after.verification_level:
                        await self.mod_tracker.log_verification_level_change(
                            mod_id=mod_id,
                            old_level=str(entry.before.verification_level).replace('_', ' ').title(),
                            new_level=str(entry.after.verification_level).replace('_', ' ').title(),
                        )

                # Check for explicit content filter change
                if hasattr(entry.before, 'explicit_content_filter') and hasattr(entry.after, 'explicit_content_filter'):
                    if entry.before.explicit_content_filter != entry.after.explicit_content_filter:
                        await self.mod_tracker.log_explicit_filter_change(
                            mod_id=mod_id,
                            old_filter=str(entry.before.explicit_content_filter).replace('_', ' ').title(),
                            new_filter=str(entry.after.explicit_content_filter).replace('_', ' ').title(),
                        )

                # Check for 2FA requirement change
                if hasattr(entry.before, 'mfa_level') and hasattr(entry.after, 'mfa_level'):
                    if entry.before.mfa_level != entry.after.mfa_level:
                        await self.mod_tracker.log_2fa_requirement_change(
                            mod_id=mod_id,
                            enabled=entry.after.mfa_level == 1,
                        )

                if changes:
                    await self.mod_tracker.log_guild_update(
                        mod_id=mod_id,
                        changes=", ".join(changes) if changes else "Server settings updated",
                    )

            # Thread create
            elif entry.action == discord.AuditLogAction.thread_create:
                if entry.target:
                    await self.mod_tracker.log_thread_create(
                        mod_id=mod_id,
                        thread=entry.target,
                    )

            # Thread delete
            elif entry.action == discord.AuditLogAction.thread_delete:
                thread_name = getattr(entry.before, 'name', 'Unknown')
                parent_name = "Unknown"
                if hasattr(entry.target, 'parent') and entry.target.parent:
                    parent_name = entry.target.parent.name
                await self.mod_tracker.log_thread_delete(
                    mod_id=mod_id,
                    thread_name=thread_name,
                    parent_name=parent_name,
                )

            # Invite create
            elif entry.action == discord.AuditLogAction.invite_create:
                if entry.target:
                    await self.mod_tracker.log_invite_create(
                        mod_id=mod_id,
                        invite=entry.target,
                    )

            # Invite delete
            elif entry.action == discord.AuditLogAction.invite_delete:
                invite_code = getattr(entry.target, 'code', 'Unknown')
                channel_name = "Unknown"
                if hasattr(entry.target, 'channel') and entry.target.channel:
                    channel_name = entry.target.channel.name
                await self.mod_tracker.log_invite_delete(
                    mod_id=mod_id,
                    invite_code=invite_code,
                    channel_name=channel_name,
                )

            # AutoMod rule create
            elif entry.action == discord.AuditLogAction.auto_moderation_rule_create:
                rule_name = getattr(entry.target, 'name', 'Unknown')
                trigger_type = str(getattr(entry.target, 'trigger_type', 'Unknown'))
                await self.mod_tracker.log_automod_rule_create(
                    mod_id=mod_id,
                    rule_name=rule_name,
                    trigger_type=trigger_type,
                )

            # AutoMod rule update
            elif entry.action == discord.AuditLogAction.auto_moderation_rule_update:
                rule_name = getattr(entry.target, 'name', 'Unknown')
                changes = "Settings updated"
                await self.mod_tracker.log_automod_rule_update(
                    mod_id=mod_id,
                    rule_name=rule_name,
                    changes=changes,
                )

            # AutoMod rule delete
            elif entry.action == discord.AuditLogAction.auto_moderation_rule_delete:
                rule_name = getattr(entry.before, 'name', 'Unknown')
                await self.mod_tracker.log_automod_rule_delete(
                    mod_id=mod_id,
                    rule_name=rule_name,
                )

            # Member nickname change (by mod, not self)
            elif entry.action == discord.AuditLogAction.member_update:
                if entry.target and entry.target.id != mod_id:  # Only if changing someone else's
                    if hasattr(entry.before, 'nick') and hasattr(entry.after, 'nick'):
                        if entry.before.nick != entry.after.nick:
                            await self.mod_tracker.log_nickname_change(
                                mod_id=mod_id,
                                target=entry.target,
                                old_nick=entry.before.nick,
                                new_nick=entry.after.nick,
                            )

            # Member voice move
            elif entry.action == discord.AuditLogAction.member_move:
                # entry.extra has channel (destination) and count
                if entry.extra and hasattr(entry.extra, 'channel'):
                    to_channel = entry.extra.channel
                    count = getattr(entry.extra, 'count', 1)
                    # Note: Audit log doesn't give us who specifically was moved or from where
                    # We'll log it generically
                    embed = discord.Embed(
                        title="Users Moved (Voice)",
                        color=0xFFFF00,
                        timestamp=datetime.now(NY_TZ),
                    )
                    embed.add_field(name="To Channel", value=f"🔊 {to_channel.name}", inline=True)
                    embed.add_field(name="Count", value=str(count), inline=True)
                    embed.set_footer(text=datetime.now(NY_TZ).strftime("%B %d, %Y"))
                    await self.mod_tracker._send_log(mod_id, embed, "Voice Move")

            # Bulk message delete (purge)
            elif entry.action == discord.AuditLogAction.message_bulk_delete:
                if entry.target:  # target is the channel
                    count = getattr(entry.extra, 'count', 0) if entry.extra else 0
                    await self.mod_tracker.log_message_purge(
                        mod_id=mod_id,
                        channel=entry.target,
                        count=count,
                    )

            # Member role update (add/remove roles from user)
            elif entry.action == discord.AuditLogAction.member_role_update:
                if hasattr(entry.before, 'roles') and hasattr(entry.after, 'roles'):
                    before_roles = set(entry.before.roles) if entry.before.roles else set()
                    after_roles = set(entry.after.roles) if entry.after.roles else set()

                    # Check if mod is changing their own roles (self-elevation alert)
                    if entry.target and entry.target.id == mod_id:
                        for role in after_roles - before_roles:
                            await self.mod_tracker.alert_self_role_change(
                                mod_id=mod_id,
                                role=role,
                                action="added",
                            )
                        for role in before_roles - after_roles:
                            await self.mod_tracker.alert_self_role_change(
                                mod_id=mod_id,
                                role=role,
                                action="removed",
                            )
                    else:
                        # Changing someone else's roles
                        for role in after_roles - before_roles:
                            await self.mod_tracker.log_role_assign(
                                mod_id=mod_id,
                                target=entry.target,
                                role=role,
                                action="added",
                            )
                        for role in before_roles - after_roles:
                            await self.mod_tracker.log_role_assign(
                                mod_id=mod_id,
                                target=entry.target,
                                role=role,
                                action="removed",
                            )

            # Voice mute/deafen
            elif entry.action == discord.AuditLogAction.member_update:
                if entry.target:
                    # Check for voice mute changes
                    if hasattr(entry.before, 'mute') and hasattr(entry.after, 'mute'):
                        if entry.before.mute != entry.after.mute:
                            action = "muted" if entry.after.mute else "unmuted"
                            await self.mod_tracker.log_voice_mute_deafen(
                                mod_id=mod_id,
                                target=entry.target,
                                action=action,
                            )
                    # Check for voice deafen changes
                    if hasattr(entry.before, 'deaf') and hasattr(entry.after, 'deaf'):
                        if entry.before.deaf != entry.after.deaf:
                            action = "deafened" if entry.after.deaf else "undeafened"
                            await self.mod_tracker.log_voice_mute_deafen(
                                mod_id=mod_id,
                                target=entry.target,
                                action=action,
                            )

            # Voice disconnect
            elif entry.action == discord.AuditLogAction.member_disconnect:
                if entry.target:
                    channel_name = "Unknown"
                    if entry.extra and hasattr(entry.extra, 'channel'):
                        channel_name = entry.extra.channel.name
                    await self.mod_tracker.log_voice_disconnect(
                        mod_id=mod_id,
                        target=entry.target,
                        channel_name=channel_name,
                    )

            # Permission overwrite create
            elif entry.action == discord.AuditLogAction.overwrite_create:
                if entry.target and entry.extra:
                    target_name = getattr(entry.extra, 'name', 'Unknown')
                    target_type = "role" if hasattr(entry.extra, 'type') and entry.extra.type == discord.Role else "member"
                    await self.mod_tracker.log_permission_overwrite(
                        mod_id=mod_id,
                        channel=entry.target,
                        target=target_name,
                        target_type=target_type,
                        action="added",
                    )

            # Permission overwrite update
            elif entry.action == discord.AuditLogAction.overwrite_update:
                if entry.target and entry.extra:
                    target_name = getattr(entry.extra, 'name', 'Unknown')
                    target_type = "role" if hasattr(entry.extra, 'type') and entry.extra.type == discord.Role else "member"
                    await self.mod_tracker.log_permission_overwrite(
                        mod_id=mod_id,
                        channel=entry.target,
                        target=target_name,
                        target_type=target_type,
                        action="updated",
                    )

            # Permission overwrite delete
            elif entry.action == discord.AuditLogAction.overwrite_delete:
                if entry.target and entry.extra:
                    target_name = getattr(entry.extra, 'name', 'Unknown')
                    target_type = "role" if hasattr(entry.extra, 'type') and entry.extra.type == discord.Role else "member"
                    await self.mod_tracker.log_permission_overwrite(
                        mod_id=mod_id,
                        channel=entry.target,
                        target=target_name,
                        target_type=target_type,
                        action="removed",
                    )

            # Sticker create
            elif entry.action == discord.AuditLogAction.sticker_create:
                sticker_name = getattr(entry.target, 'name', 'Unknown')
                await self.mod_tracker.log_sticker_create(
                    mod_id=mod_id,
                    sticker_name=sticker_name,
                )

            # Sticker delete
            elif entry.action == discord.AuditLogAction.sticker_delete:
                sticker_name = getattr(entry.before, 'name', 'Unknown')
                await self.mod_tracker.log_sticker_delete(
                    mod_id=mod_id,
                    sticker_name=sticker_name,
                )

            # Scheduled event create
            elif entry.action == discord.AuditLogAction.scheduled_event_create:
                event_name = getattr(entry.target, 'name', 'Unknown')
                event_type = str(getattr(entry.target, 'entity_type', 'Unknown'))
                await self.mod_tracker.log_event_create(
                    mod_id=mod_id,
                    event_name=event_name,
                    event_type=event_type,
                )

            # Scheduled event update
            elif entry.action == discord.AuditLogAction.scheduled_event_update:
                event_name = getattr(entry.target, 'name', 'Unknown')
                await self.mod_tracker.log_event_update(
                    mod_id=mod_id,
                    event_name=event_name,
                )

            # Scheduled event delete
            elif entry.action == discord.AuditLogAction.scheduled_event_delete:
                event_name = getattr(entry.before, 'name', 'Unknown')
                await self.mod_tracker.log_event_delete(
                    mod_id=mod_id,
                    event_name=event_name,
                )

            # Stage instance create (topic change via audit)
            elif entry.action == discord.AuditLogAction.stage_instance_create:
                if entry.target and hasattr(entry.target, 'channel'):
                    topic = getattr(entry.target, 'topic', None)
                    await self.mod_tracker.log_stage_topic_change(
                        mod_id=mod_id,
                        stage_channel=entry.target.channel,
                        old_topic=None,
                        new_topic=topic,
                    )

            # Stage instance update
            elif entry.action == discord.AuditLogAction.stage_instance_update:
                if entry.target and hasattr(entry.target, 'channel'):
                    old_topic = getattr(entry.before, 'topic', None) if entry.before else None
                    new_topic = getattr(entry.after, 'topic', None) if entry.after else None
                    if old_topic != new_topic:
                        await self.mod_tracker.log_stage_topic_change(
                            mod_id=mod_id,
                            stage_channel=entry.target.channel,
                            old_topic=old_topic,
                            new_topic=new_topic,
                        )

            # Integration create
            elif entry.action == discord.AuditLogAction.integration_create:
                integration_name = getattr(entry.target, 'name', 'Unknown')
                integration_type = getattr(entry.target, 'type', 'Unknown')
                await self.mod_tracker.log_integration_create(
                    mod_id=mod_id,
                    integration_name=integration_name,
                    integration_type=str(integration_type),
                )

            # Integration delete
            elif entry.action == discord.AuditLogAction.integration_delete:
                integration_name = getattr(entry.before, 'name', 'Unknown')
                await self.mod_tracker.log_integration_delete(
                    mod_id=mod_id,
                    integration_name=integration_name,
                )

            # Bot add (via member_update with bot flag)
            elif entry.action == discord.AuditLogAction.bot_add:
                if entry.target and entry.target.bot:
                    await self.mod_tracker.log_bot_add(
                        mod_id=mod_id,
                        bot=entry.target,
                    )

            # Member prune
            elif entry.action == discord.AuditLogAction.member_prune:
                days = getattr(entry.extra, 'delete_member_days', 0)
                members_removed = getattr(entry.extra, 'members_removed', 0)
                await self.mod_tracker.log_member_prune(
                    mod_id=mod_id,
                    days=days,
                    members_removed=members_removed,
                )

            # Soundboard sound create
            elif entry.action == discord.AuditLogAction.soundboard_sound_create:
                sound_name = getattr(entry.target, 'name', 'Unknown')
                await self.mod_tracker.log_soundboard_create(
                    mod_id=mod_id,
                    sound_name=sound_name,
                )

            # Soundboard sound delete
            elif entry.action == discord.AuditLogAction.soundboard_sound_delete:
                sound_name = getattr(entry.before, 'name', 'Unknown')
                await self.mod_tracker.log_soundboard_delete(
                    mod_id=mod_id,
                    sound_name=sound_name,
                )

            # Soundboard sound update
            elif entry.action == discord.AuditLogAction.soundboard_sound_update:
                sound_name = getattr(entry.target, 'name', 'Unknown')
                changes = []
                if hasattr(entry.before, 'name') and hasattr(entry.after, 'name'):
                    if entry.before.name != entry.after.name:
                        changes.append(f"Name: {entry.before.name} → {entry.after.name}")
                if hasattr(entry.before, 'volume') and hasattr(entry.after, 'volume'):
                    if entry.before.volume != entry.after.volume:
                        changes.append(f"Volume: {entry.before.volume} → {entry.after.volume}")
                await self.mod_tracker.log_soundboard_update(
                    mod_id=mod_id,
                    sound_name=sound_name,
                    changes=", ".join(changes) if changes else "Settings changed",
                )

            # Onboarding create
            elif entry.action == discord.AuditLogAction.onboarding_create:
                await self.mod_tracker.log_onboarding_create(mod_id=mod_id)

            # Onboarding update
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
                await self.mod_tracker.log_onboarding_update(
                    mod_id=mod_id,
                    changes=", ".join(changes) if changes else "Settings changed",
                )

        except Exception as e:
            logger.warning("Mod Tracker: Audit Log Event Failed", [
                ("Action", str(entry.action)),
                ("Error", str(e)[:50]),
            ])

    # =========================================================================
    # Logging Service - Audit Log Routing
    # =========================================================================

    async def _log_audit_event(self, entry: discord.AuditLogEntry) -> None:
        """
        Route audit log events to the logging service.

        DESIGN: Handles all audit log events and routes them to the
        appropriate logging service method.
        """
        if not self.logging_service or not self.logging_service.enabled:
            return

        try:
            # Get the moderator who performed the action
            moderator = None
            if entry.user_id:
                guild = entry.guild
                if guild:
                    moderator = guild.get_member(entry.user_id)

            # -----------------------------------------------------------------
            # Bans & Kicks
            # -----------------------------------------------------------------
            if entry.action == discord.AuditLogAction.ban:
                if entry.target:
                    await self.logging_service.log_ban(
                        entry.target,
                        moderator=moderator,
                        reason=entry.reason,
                    )

            elif entry.action == discord.AuditLogAction.unban:
                if entry.target:
                    await self.logging_service.log_unban(
                        entry.target,
                        moderator=moderator,
                        reason=entry.reason,
                    )

            elif entry.action == discord.AuditLogAction.kick:
                if entry.target and not entry.target.bot:
                    await self.logging_service.log_kick(
                        entry.target,
                        moderator=moderator,
                        reason=entry.reason,
                    )

            # -----------------------------------------------------------------
            # Mutes & Timeouts & Voice Mute/Deafen
            # -----------------------------------------------------------------
            elif entry.action == discord.AuditLogAction.member_update:
                # Check for new timeout
                if hasattr(entry.after, 'timed_out_until') and entry.after.timed_out_until:
                    if entry.target and isinstance(entry.target, discord.Member):
                        await self.logging_service.log_timeout(
                            entry.target,
                            until=entry.after.timed_out_until,
                            moderator=moderator,
                            reason=entry.reason,
                        )

                # Check for timeout removal
                old_timeout = getattr(entry.before, 'timed_out_until', None)
                new_timeout = getattr(entry.after, 'timed_out_until', None)
                if old_timeout and not new_timeout:
                    if entry.target and isinstance(entry.target, discord.Member):
                        await self.logging_service.log_timeout_remove(
                            entry.target,
                            moderator=moderator,
                        )

                # Voice server mute
                if entry.target and isinstance(entry.target, discord.Member):
                    if hasattr(entry.before, 'mute') and hasattr(entry.after, 'mute'):
                        if entry.before.mute != entry.after.mute:
                            await self.logging_service.log_server_voice_mute(
                                member=entry.target,
                                muted=entry.after.mute,
                                moderator=moderator,
                            )

                    # Voice server deafen
                    if hasattr(entry.before, 'deaf') and hasattr(entry.after, 'deaf'):
                        if entry.before.deaf != entry.after.deaf:
                            await self.logging_service.log_server_voice_deafen(
                                member=entry.target,
                                deafened=entry.after.deaf,
                                moderator=moderator,
                            )

                    # Nickname force change (by mod)
                    if hasattr(entry.before, 'nick') and hasattr(entry.after, 'nick'):
                        if entry.before.nick != entry.after.nick:
                            # Only log if moderator is different from target
                            if moderator and entry.target and moderator.id != entry.target.id:
                                await self.logging_service.log_nickname_force_change(
                                    target=entry.target,
                                    old_nick=entry.before.nick,
                                    new_nick=entry.after.nick,
                                    moderator=moderator,
                                )
                                # Save to nickname history database with moderator info
                                self.db.save_nickname_change(
                                    user_id=entry.target.id,
                                    guild_id=entry.guild.id,
                                    old_nickname=entry.before.nick,
                                    new_nickname=entry.after.nick,
                                    changed_by=moderator.id,
                                )

            # -----------------------------------------------------------------
            # Voice Disconnect (by mod)
            # -----------------------------------------------------------------
            elif entry.action == discord.AuditLogAction.member_disconnect:
                if entry.extra and hasattr(entry.extra, 'count'):
                    # Get target member info if available
                    channel_name = "Unknown"
                    if hasattr(entry.extra, 'channel') and entry.extra.channel:
                        channel_name = entry.extra.channel.name

                    # Note: member_disconnect doesn't have specific target
                    # It logs the count of disconnections
                    if entry.extra.count == 1 and entry.target:
                        # Single disconnect - we can identify the member
                        if isinstance(entry.target, discord.Member):
                            await self.logging_service.log_voice_disconnect(
                                target=entry.target,
                                channel_name=channel_name,
                                moderator=moderator,
                            )

            # -----------------------------------------------------------------
            # Mod Message Delete
            # -----------------------------------------------------------------
            elif entry.action == discord.AuditLogAction.message_delete:
                if entry.target and entry.extra:
                    # Check if mod deleted someone else's message
                    if moderator and entry.target.id != moderator.id:
                        channel_id = getattr(entry.extra, 'channel', None)
                        if channel_id:
                            channel = entry.guild.get_channel(channel_id.id) if hasattr(channel_id, 'id') else entry.guild.get_channel(channel_id)
                        else:
                            channel = None

                        # Try to get cached message content
                        message_data = None
                        if hasattr(entry.extra, 'message_id'):
                            message_data = self._message_cache.pop(entry.extra.message_id, None)

                        # Get attachments from cache
                        attachments = None
                        if hasattr(entry.extra, 'message_id'):
                            attachments = self._attachment_cache.pop(entry.extra.message_id, None)

                        if channel:
                            await self.logging_service.log_mod_message_delete(
                                author=entry.target,
                                channel=channel,
                                content=message_data.get('content') if message_data else None,
                                moderator=moderator,
                                attachments=attachments,
                                # Pass metadata for context when content is empty
                                attachment_names=message_data.get('attachment_names') if message_data else None,
                                sticker_names=message_data.get('sticker_names') if message_data else None,
                                has_embeds=message_data.get('has_embeds') if message_data else False,
                                embed_titles=message_data.get('embed_titles') if message_data else None,
                            )

            # -----------------------------------------------------------------
            # Bulk Message Delete
            # -----------------------------------------------------------------
            elif entry.action == discord.AuditLogAction.message_bulk_delete:
                if entry.target:
                    count = getattr(entry.extra, 'count', 0) if entry.extra else 0
                    await self.logging_service.log_bulk_delete(
                        entry.target,
                        count=count,
                        moderator=moderator,
                    )

            # -----------------------------------------------------------------
            # Permission Overwrites
            # -----------------------------------------------------------------
            elif entry.action == discord.AuditLogAction.overwrite_create:
                if entry.target and entry.extra:
                    target_name = getattr(entry.extra, 'name', 'Unknown')
                    await self.logging_service.log_permission_update(
                        entry.target,
                        target=target_name,
                        action="added",
                        moderator=moderator,
                    )

            elif entry.action == discord.AuditLogAction.overwrite_update:
                if entry.target and entry.extra:
                    target_name = getattr(entry.extra, 'name', 'Unknown')
                    await self.logging_service.log_permission_update(
                        entry.target,
                        target=target_name,
                        action="updated",
                        moderator=moderator,
                    )

            elif entry.action == discord.AuditLogAction.overwrite_delete:
                if entry.target and entry.extra:
                    target_name = getattr(entry.extra, 'name', 'Unknown')
                    await self.logging_service.log_permission_update(
                        entry.target,
                        target=target_name,
                        action="removed",
                        moderator=moderator,
                    )

            # -----------------------------------------------------------------
            # Channel Updates
            # -----------------------------------------------------------------
            elif entry.action == discord.AuditLogAction.channel_update:
                if entry.target:
                    changes = []
                    if hasattr(entry.before, 'name') and hasattr(entry.after, 'name'):
                        if entry.before.name != entry.after.name:
                            changes.append(f"Name: {entry.before.name} → {entry.after.name}")
                    if hasattr(entry.before, 'topic') and hasattr(entry.after, 'topic'):
                        if entry.before.topic != entry.after.topic:
                            changes.append("Topic changed")

                    # Dedicated slowmode change logging
                    if hasattr(entry.before, 'slowmode_delay') and hasattr(entry.after, 'slowmode_delay'):
                        if entry.before.slowmode_delay != entry.after.slowmode_delay:
                            changes.append(f"Slowmode: {entry.before.slowmode_delay}s → {entry.after.slowmode_delay}s")
                            # Log dedicated slowmode change
                            await self.logging_service.log_slowmode_change(
                                channel=entry.target,
                                old_delay=entry.before.slowmode_delay,
                                new_delay=entry.after.slowmode_delay,
                                moderator=moderator,
                            )

                    # Channel category move
                    if hasattr(entry.before, 'category') and hasattr(entry.after, 'category'):
                        old_cat = entry.before.category
                        new_cat = entry.after.category
                        if old_cat != new_cat:
                            old_name = old_cat.name if old_cat else None
                            new_name = new_cat.name if new_cat else None
                            await self.logging_service.log_channel_category_move(
                                channel=entry.target,
                                old_category=old_name,
                                new_category=new_name,
                                moderator=moderator,
                            )

                    # Forum tag changes (for ForumChannels)
                    if isinstance(entry.target, discord.ForumChannel):
                        if hasattr(entry.before, 'available_tags') and hasattr(entry.after, 'available_tags'):
                            old_tags = {t.name: t for t in (entry.before.available_tags or [])}
                            new_tags = {t.name: t for t in (entry.after.available_tags or [])}

                            # Find new tags (created)
                            for tag_name in new_tags:
                                if tag_name not in old_tags:
                                    await self.logging_service.log_forum_tag_create(
                                        forum=entry.target,
                                        tag_name=tag_name,
                                        moderator=moderator,
                                    )

                            # Find removed tags (deleted)
                            for tag_name in old_tags:
                                if tag_name not in new_tags:
                                    await self.logging_service.log_forum_tag_delete(
                                        forum=entry.target,
                                        tag_name=tag_name,
                                        moderator=moderator,
                                    )

                    if changes:
                        await self.logging_service.log_channel_update(
                            entry.target,
                            changes=", ".join(changes),
                            moderator=moderator,
                        )

            # -----------------------------------------------------------------
            # Role Updates
            # -----------------------------------------------------------------
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

                    # Role position/hierarchy changes
                    if hasattr(entry.before, 'position') and hasattr(entry.after, 'position'):
                        if entry.before.position != entry.after.position:
                            await self.logging_service.log_role_position_change(
                                role=entry.target,
                                old_position=entry.before.position,
                                new_position=entry.after.position,
                                moderator=moderator,
                            )

                    if changes:
                        await self.logging_service.log_role_update(
                            entry.target,
                            changes=", ".join(changes),
                            moderator=moderator,
                        )

            # -----------------------------------------------------------------
            # Server Settings
            # -----------------------------------------------------------------
            elif entry.action == discord.AuditLogAction.guild_update:
                changes = []
                if hasattr(entry.before, 'name') and hasattr(entry.after, 'name'):
                    if entry.before.name != entry.after.name:
                        changes.append(f"Name: {entry.before.name} → {entry.after.name}")

                # Icon change - log with images
                if hasattr(entry.before, 'icon') and hasattr(entry.after, 'icon'):
                    if entry.before.icon != entry.after.icon:
                        old_icon = None
                        new_icon = None
                        if entry.before.icon:
                            old_icon = f"https://cdn.discordapp.com/icons/{entry.guild.id}/{entry.before.icon}.png?size=256"
                        if entry.after.icon:
                            new_icon = f"https://cdn.discordapp.com/icons/{entry.guild.id}/{entry.after.icon}.png?size=256"
                        await self.logging_service.log_server_icon_change(
                            guild=entry.guild,
                            old_icon_url=old_icon,
                            new_icon_url=new_icon,
                            moderator=moderator,
                        )

                # Banner change - log with images
                if hasattr(entry.before, 'banner') and hasattr(entry.after, 'banner'):
                    if entry.before.banner != entry.after.banner:
                        old_banner = None
                        new_banner = None
                        if entry.before.banner:
                            old_banner = f"https://cdn.discordapp.com/banners/{entry.guild.id}/{entry.before.banner}.png?size=512"
                        if entry.after.banner:
                            new_banner = f"https://cdn.discordapp.com/banners/{entry.guild.id}/{entry.after.banner}.png?size=512"
                        await self.logging_service.log_server_banner_change(
                            guild=entry.guild,
                            old_banner_url=old_banner,
                            new_banner_url=new_banner,
                            moderator=moderator,
                        )

                if hasattr(entry.before, 'verification_level') and hasattr(entry.after, 'verification_level'):
                    if entry.before.verification_level != entry.after.verification_level:
                        changes.append(f"Verification: {entry.after.verification_level}")
                if hasattr(entry.before, 'explicit_content_filter') and hasattr(entry.after, 'explicit_content_filter'):
                    if entry.before.explicit_content_filter != entry.after.explicit_content_filter:
                        changes.append(f"Content Filter: {entry.after.explicit_content_filter}")
                if changes:
                    await self.logging_service.log_server_update(
                        changes=", ".join(changes),
                        moderator=moderator,
                    )

            # -----------------------------------------------------------------
            # Bots & Integrations
            # -----------------------------------------------------------------
            elif entry.action == discord.AuditLogAction.bot_add:
                if entry.target and entry.target.bot:
                    await self.logging_service.log_bot_add(
                        entry.target,
                        moderator=moderator,
                    )

            elif entry.action == discord.AuditLogAction.integration_create:
                name = getattr(entry.target, 'name', 'Unknown')
                int_type = str(getattr(entry.target, 'type', 'Unknown'))
                await self.logging_service.log_integration_add(
                    name=name,
                    int_type=int_type,
                    moderator=moderator,
                )

            elif entry.action == discord.AuditLogAction.integration_delete:
                name = getattr(entry.before, 'name', 'Unknown')
                await self.logging_service.log_integration_remove(
                    name=name,
                    moderator=moderator,
                )

            # -----------------------------------------------------------------
            # Webhooks
            # -----------------------------------------------------------------
            elif entry.action == discord.AuditLogAction.webhook_create:
                webhook_name = getattr(entry.target, 'name', 'Unknown')
                channel = entry.target.channel if hasattr(entry.target, 'channel') else None
                if channel:
                    await self.logging_service.log_webhook_create(
                        webhook_name=webhook_name,
                        channel=channel,
                        moderator=moderator,
                    )

            elif entry.action == discord.AuditLogAction.webhook_delete:
                webhook_name = getattr(entry.before, 'name', 'Unknown')
                channel_name = "Unknown"
                if hasattr(entry.before, 'channel') and entry.before.channel:
                    channel_name = entry.before.channel.name
                await self.logging_service.log_webhook_delete(
                    webhook_name=webhook_name,
                    channel_name=channel_name,
                    moderator=moderator,
                )

            # -----------------------------------------------------------------
            # Message Pin/Unpin
            # -----------------------------------------------------------------
            elif entry.action == discord.AuditLogAction.message_pin:
                if entry.extra and hasattr(entry.extra, 'channel'):
                    try:
                        channel = entry.extra.channel
                        message = await channel.fetch_message(entry.extra.message_id)
                        await self.logging_service.log_message_pin(
                            message=message,
                            pinned=True,
                            moderator=moderator,
                        )
                    except Exception:
                        pass

            elif entry.action == discord.AuditLogAction.message_unpin:
                if entry.extra and hasattr(entry.extra, 'channel'):
                    try:
                        channel = entry.extra.channel
                        message = await channel.fetch_message(entry.extra.message_id)
                        await self.logging_service.log_message_pin(
                            message=message,
                            pinned=False,
                            moderator=moderator,
                        )
                    except Exception:
                        pass

        except Exception as e:
            logger.debug(f"Logging Service: Audit event failed: {e}")

    # =========================================================================
    # Shutdown
    # =========================================================================

    async def shutdown(self) -> None:
        """
        Graceful shutdown with proper cleanup.

        DESIGN: Closes services in reverse order of initialization.
        """
        logger.info("Initiating Graceful Shutdown")

        # Send shutdown webhook alert
        if self.webhook_alert_service:
            self.webhook_alert_service.stop_hourly_alerts()
            await self.webhook_alert_service.send_shutdown_alert()

        # Stop mute scheduler
        if self.mute_scheduler:
            await self.mute_scheduler.stop()

        # Stop health server
        if self.health_server:
            await self.health_server.stop()

        # Close database connection
        self.db.close()

        # Close Discord connection
        await super().close()

        logger.tree("SHUTDOWN COMPLETE", [
            ("Uptime", str(datetime.now() - self.start_time)),
        ], emoji="🛑")

    async def close(self) -> None:
        """Override close to ensure proper shutdown."""
        await self.shutdown()


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["AzabBot"]
