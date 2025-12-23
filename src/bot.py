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
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from collections import deque

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, NY_TZ
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
       - Event cog loading
       - Command tree syncing

    2. on_ready:
       - AI Service (OpenAI integration)
       - Prison Handler (mute/unmute tracking)
       - Mute Handler (embed parsing)
       - Presence Handler (status updates)
       - Health Check Server
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self) -> None:
        """Initialize the Azab bot with necessary intents and configuration."""
        self.config = get_config()

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

        self.db = get_db()
        self.start_time: datetime = datetime.now()
        self.disabled: bool = False

        # Service placeholders
        self.ai_service = None
        self.prison_handler = None
        self.mute_handler = None
        self.presence_handler = None
        self.health_server = None
        self.mute_scheduler = None
        self.case_log_service = None
        self.alt_detection = None
        self.mod_tracker = None
        self.logging_service = None
        self.webhook_alert_service = None
        self.voice_handler = None

        # Prisoner rate limiting
        self.prisoner_cooldowns: Dict[int, datetime] = {}
        self.prisoner_message_buffer: Dict[int, List[str]] = {}
        self.prisoner_pending_response: Dict[int, bool] = {}

        # Message history tracking
        self.last_messages: Dict[int, dict] = {}

        # Invite cache
        self._invite_cache: Dict[str, int] = {}

        # Message attachment cache
        self._attachment_cache: Dict[int, List[tuple]] = {}
        self._attachment_cache_limit: int = 500

        # Message content cache
        self._message_cache: Dict[int, dict] = {}
        self._message_cache_limit: int = 5000

        # Raid detection
        self._recent_joins: deque = deque(maxlen=50)
        self._raid_threshold: int = 10
        self._raid_window: int = 30
        self._last_raid_alert: Optional[datetime] = None

        # Ready state guard
        self._ready_initialized: bool = False

        logger.info("Bot Instance Created")

    # =========================================================================
    # Setup Hook
    # =========================================================================

    async def setup_hook(self) -> None:
        """Load cogs and sync commands before on_ready."""
        # Load command cogs
        from src.commands import COMMAND_COGS
        for cog in COMMAND_COGS:
            try:
                await self.load_extension(cog)
                logger.info(f"Cog Loaded: {cog.split('.')[-1]}")
            except Exception as e:
                logger.error("Failed to Load Cog", [("Cog", cog), ("Error", str(e))])

        # Load event cogs
        from src.events import EVENT_COGS
        for cog in EVENT_COGS:
            try:
                await self.load_extension(cog)
                logger.debug(f"Event Cog Loaded: {cog.split('.')[-1]}")
            except Exception as e:
                logger.error("Failed to Load Event Cog", [("Cog", cog), ("Error", str(e))])

        # Register persistent views
        from src.services.server_logs.service import setup_log_views
        setup_log_views(self)

        from src.utils.views import setup_moderation_views
        setup_moderation_views(self)

        # Sync commands
        try:
            synced = await self.tree.sync()
            logger.tree("Commands Synced", [("Count", str(len(synced)))], emoji="✅")
        except Exception as e:
            logger.error("Command Sync Failed", [("Error", str(e))])

    # =========================================================================
    # On Ready
    # =========================================================================

    async def on_ready(self) -> None:
        """Initialize services when bot is ready."""
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

        await self._init_services()

        from src.utils.footer import init_footer
        await init_footer(self)

        from src.utils.metrics import init_metrics
        init_metrics()

        self.disabled = not self.db.is_active()
        logger.tree("Bot State Loaded", [("Active", str(not self.disabled))], emoji="ℹ️")

        if self.config.error_webhook_url:
            logger.set_webhook(self.config.error_webhook_url)

        if self.presence_handler:
            asyncio.create_task(self.presence_handler.start_presence_loop())

        await self._cleanup_polls_channel()
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

    # =========================================================================
    # Service Initialization
    # =========================================================================

    async def _init_services(self) -> None:
        """Initialize all services after Discord connection."""
        try:
            from src.services.ai_service import AIService
            self.ai_service = AIService(self.config.openai_api_key)

            from src.handlers.prison_handler import PrisonHandler
            self.prison_handler = PrisonHandler(self, self.ai_service)
            logger.info("Prison Handler Initialized")

            from src.handlers.mute_handler import MuteHandler
            self.mute_handler = MuteHandler(self.prison_handler)
            logger.info("Mute Handler Initialized")

            from src.handlers.presence_handler import PresenceHandler
            self.presence_handler = PresenceHandler(self)
            logger.info("Presence Handler Initialized")

            from src.core.health import HealthCheckServer
            self.health_server = HealthCheckServer(self)
            await self.health_server.start()

            from src.services.mute_scheduler import MuteScheduler
            self.mute_scheduler = MuteScheduler(self)
            await self.mute_scheduler.start()

            from src.services.case_log import CaseLogService
            self.case_log_service = CaseLogService(self)
            if self.case_log_service.enabled:
                await self.case_log_service.start_reason_scheduler()
                logger.tree("Case Log Service Initialized", [
                    ("Forum ID", str(self.config.case_log_forum_id)),
                    ("Reason Scheduler", "Running"),
                ], emoji="📝")
            else:
                logger.info("Case Log Service Disabled (no forum configured)")

            from src.services.alt_detection import AltDetectionService
            self.alt_detection = AltDetectionService(self)
            if self.alt_detection.enabled:
                logger.info("Alt Detection Service Initialized")
            else:
                logger.info("Alt Detection Service Disabled (no case log forum)")

            from src.services.mod_tracker import ModTrackerService
            self.mod_tracker = ModTrackerService(self)
            if self.mod_tracker.enabled:
                logger.tree("Mod Tracker Service Initialized", [
                    ("Server ID", str(self.config.mod_server_id)),
                    ("Forum ID", str(self.config.mod_tracker_forum_id)),
                    ("Role ID", str(self.config.mod_role_id)),
                ], emoji="👁️")
                await self.mod_tracker.auto_scan_mods()
                await self.mod_tracker.start_title_update_scheduler()
                await self.mod_tracker.start_inactivity_checker()
            else:
                logger.info("Mod Tracker Service Disabled (no config)")

            from src.services.server_logs import LoggingService
            self.logging_service = LoggingService(self)
            if await self.logging_service.initialize():
                logger.tree("Logging Service Initialized", [
                    ("Forum ID", str(self.config.server_logs_forum_id)),
                    ("Threads", "15 categories"),
                ], emoji="📋")
            else:
                logger.info("Logging Service Disabled (no forum configured)")

            from src.services.webhook_alerts import get_alert_service
            self.webhook_alert_service = get_alert_service()
            self.webhook_alert_service.set_bot(self)
            await self.webhook_alert_service.send_startup_alert()
            await self.webhook_alert_service.start_hourly_alerts()

            from src.handlers.voice_handler import VoiceHandler
            self.voice_handler = VoiceHandler(self)
            logger.info("Voice Handler Initialized")

            # Summary of all initialized services
            logger.tree("ALL SERVICES INITIALIZED", [
                ("AI Service", "✓ Ready"),
                ("Prison Handler", "✓ Ready"),
                ("Mute Scheduler", "✓ Running"),
                ("Case Log", "✓ Enabled" if self.case_log_service.enabled else "✗ Disabled"),
                ("Alt Detection", "✓ Enabled" if self.alt_detection.enabled else "✗ Disabled"),
                ("Mod Tracker", "✓ Enabled" if self.mod_tracker.enabled else "✗ Disabled"),
                ("Server Logs", "✓ Enabled" if self.logging_service.enabled else "✗ Disabled"),
                ("Voice Handler", "✓ Ready"),
            ], emoji="🚀")

        except Exception as e:
            logger.error("Service Initialization Failed", [("Error", str(e))])

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def is_user_muted(self, member: discord.Member) -> bool:
        """Check if user has the muted role."""
        return any(role.id == self.config.muted_role_id for role in member.roles)

    async def _cleanup_polls_channel(self) -> None:
        """Clean up non-poll messages from polls-only channel."""
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
                        await asyncio.sleep(self.config.rate_limit_delay)
                    except (discord.NotFound, discord.Forbidden):
                        pass

            if deleted > 0:
                logger.tree("Polls Channel Cleaned", [("Deleted", str(deleted))], emoji="🗑️")
        except Exception as e:
            logger.tree("Polls Cleanup Failed", [("Error", str(e))], emoji="⚠️")

    async def _cache_invites(self) -> None:
        """Cache all server invites for tracking."""
        try:
            for guild in self.guilds:
                try:
                    invites = await guild.invites()
                    for invite in invites:
                        self._invite_cache[invite.code] = invite.uses or 0
                    logger.info(f"Cached {len(invites)} invites for {guild.name}")
                except discord.Forbidden:
                    pass
        except Exception as e:
            logger.debug(f"Invite cache failed: {e}")

    async def _find_used_invite(self, guild: discord.Guild) -> Optional[tuple]:
        """Find which invite was used by comparing use counts."""
        try:
            new_invites = await guild.invites()
            for invite in new_invites:
                old_uses = self._invite_cache.get(invite.code, 0)
                if invite.uses and invite.uses > old_uses:
                    self._invite_cache[invite.code] = invite.uses
                    return (invite.code, invite.inviter)
                self._invite_cache[invite.code] = invite.uses or 0
        except discord.Forbidden:
            pass
        except Exception as e:
            logger.debug(f"Find invite failed: {e}")
        return None

    async def _cache_message_attachments(self, message: discord.Message) -> None:
        """Download and cache message attachments."""
        if not message.attachments:
            return

        if len(self._attachment_cache) >= self._attachment_cache_limit:
            oldest = list(self._attachment_cache.keys())[:100]
            for key in oldest:
                self._attachment_cache.pop(key, None)

        attachments = []
        for att in message.attachments:
            if att.size and att.size < 8 * 1024 * 1024:
                try:
                    data = await att.read()
                    attachments.append((att.filename, data))
                except Exception:
                    pass

        if attachments:
            if len(self._attachment_cache) >= self._attachment_cache_limit:
                oldest = list(self._attachment_cache.keys())[:50]
                for key in oldest:
                    self._attachment_cache.pop(key, None)

            self._attachment_cache[message.id] = attachments

    async def _check_raid_detection(self, member: discord.Member) -> None:
        """Check for potential raid by tracking join rate."""
        current_time = datetime.now()
        self._recent_joins.append((current_time, member))

        cutoff_time = current_time - timedelta(seconds=self._raid_window)
        recent = [(t, m) for t, m in self._recent_joins if t >= cutoff_time]
        join_count = len(recent)

        if join_count >= self._raid_threshold:
            can_alert = True
            if self._last_raid_alert:
                time_since_alert = (current_time - self._last_raid_alert).total_seconds()
                if time_since_alert < 300:
                    can_alert = False

            if can_alert and self.logging_service:
                self._last_raid_alert = current_time
                recent_members = [m for _, m in recent]
                await self.logging_service.log_raid_alert(
                    join_count=join_count,
                    time_window=self._raid_window,
                    recent_members=recent_members,
                )

    async def _auto_hide_from_muted(self, channel: discord.abc.GuildChannel) -> None:
        """Automatically hide a new channel from the muted role."""
        if isinstance(channel, discord.CategoryChannel):
            return

        if self.config.logging_guild_id and channel.guild.id != self.config.logging_guild_id:
            return

        muted_role = channel.guild.get_role(self.config.muted_role_id)
        if not muted_role:
            return

        prison_channel_ids = self.config.prison_channel_ids or set()
        if channel.id in prison_channel_ids:
            return

        try:
            await channel.set_permissions(
                muted_role,
                view_channel=False,
                reason="Auto-hide: New channel hidden from muted role",
            )
            logger.tree("Auto-Hide Channel", [
                ("Channel", f"#{channel.name}"),
                ("Hidden From", muted_role.name),
            ], emoji="🔒")
        except discord.Forbidden:
            logger.warning(f"No permission to hide channel #{channel.name} from muted role")
        except discord.HTTPException as e:
            logger.warning(f"Failed to hide channel #{channel.name}: {e}")

    # =========================================================================
    # Shutdown
    # =========================================================================

    async def shutdown(self) -> None:
        """Graceful shutdown with proper cleanup."""
        logger.info("Initiating Graceful Shutdown")

        if self.webhook_alert_service:
            self.webhook_alert_service.stop_hourly_alerts()
            await self.webhook_alert_service.send_shutdown_alert()

        if self.mute_scheduler:
            await self.mute_scheduler.stop()

        if self.case_log_service and self.case_log_service.enabled:
            await self.case_log_service.stop_reason_scheduler()

        if self.health_server:
            await self.health_server.stop()

        self.db.close()
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
