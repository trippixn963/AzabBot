"""
Azab Discord Bot - Main Bot Class
==================================

Core Discord client for the Syria Discord server providing
comprehensive moderation for muted users (prisoners).

Features:
- Prisoner tracking with message batching
- Dynamic presence updates
- Polls-only channel enforcement
- Health check HTTP endpoint
- Mod activity tracking

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from collections import deque, OrderedDict

import discord
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, NY_TZ
from src.core.database import get_db
from src.utils.rate_limiter import rate_limit
from src.utils.async_utils import create_safe_task


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
        self.prison_handler = None
        self.mute_handler = None
        self.presence_handler = None
        self.health_server = None
        self.mute_scheduler = None
        self.case_log_service = None
        self.case_archive_scheduler = None
        self.alt_detection = None
        self.mod_tracker = None
        self.logging_service = None
        self.webhook_alert_service = None
        self.voice_handler = None
        self.antispam_service = None
        self.antinuke_service = None
        self.raid_lockdown_service = None
        self.appeal_service = None
        self.ticket_service = None
        self.modmail_service = None
        self.stats_api = None

        # Shared HTTP session for all services
        self._http_session: Optional[aiohttp.ClientSession] = None

        # Prisoner rate limiting
        self.prisoner_cooldowns: Dict[int, datetime] = {}
        self.prisoner_message_buffer: Dict[int, List[str]] = {}
        self.prisoner_pending_response: Dict[int, bool] = {}

        # Message history tracking (LRU cache with limit)
        self.last_messages: OrderedDict[int, dict] = OrderedDict()
        self._last_messages_limit: int = 5000

        # Invite cache
        self._invite_cache: Dict[str, int] = {}

        # Message attachment cache (OrderedDict for O(1) LRU eviction)
        self._attachment_cache: OrderedDict[int, List[tuple]] = OrderedDict()
        self._attachment_cache_limit: int = 500

        # Message content cache (OrderedDict for O(1) LRU eviction)
        self._message_cache: OrderedDict[int, dict] = OrderedDict()
        self._message_cache_limit: int = 5000

        # Snipe cache (channel_id -> deque of last 10 deleted messages)
        self._snipe_cache: Dict[int, deque] = {}
        self._snipe_limit: int = 10

        # Edit snipe cache (channel_id -> deque of last 10 edits)
        self._editsnipe_cache: OrderedDict[int, deque] = OrderedDict()
        self._editsnipe_limit: int = 10
        self._editsnipe_channel_limit: int = 500  # Max channels to track

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

        from src.services.appeal_service import setup_appeal_views
        setup_appeal_views(self)

        from src.services.tickets import setup_ticket_views
        setup_ticket_views(self)

        from src.services.modmail_service import setup_modmail_views
        setup_modmail_views(self)

        # Sync commands globally
        try:
            # Clear any guild-specific commands first (to remove duplicates)
            if self.config.logging_guild_id:
                guild = discord.Object(id=self.config.logging_guild_id)
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
                logger.debug("Cleared guild-specific commands")

            # Global sync
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

        from src.utils.banner import init_banner
        await init_banner(self)

        from src.utils.metrics import init_metrics
        init_metrics()

        self.disabled = not self.db.is_active()
        logger.tree("Bot State Loaded", [("Active", str(not self.disabled))], emoji="ℹ️")

        if self.presence_handler:
            create_safe_task(self.presence_handler.start(), "Presence Handler")

        await self._cleanup_polls_channel()
        await self._cache_invites()
        await self._check_lockdown_state()

        logger.tree("AZAB READY", [
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
            from src.handlers.prison_handler import PrisonHandler
            self.prison_handler = PrisonHandler(self)
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

            from src.services.stats_api import AzabAPI
            self.stats_api = AzabAPI(self)
            await self.stats_api.start()

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

                # Start case archive scheduler
                from src.services.case_archive_scheduler import CaseArchiveScheduler
                self.case_archive_scheduler = CaseArchiveScheduler(self)
                await self.case_archive_scheduler.start()
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
                    ("Role ID", str(self.config.moderation_role_id)),
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
                # Start log retention cleanup
                await self.logging_service.start_retention_cleanup()
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

            from src.services.antispam import AntiSpamService
            self.antispam_service = AntiSpamService(self)

            from src.services.antinuke import AntiNukeService
            self.antinuke_service = AntiNukeService(self)

            from src.services.raid_lockdown import RaidLockdownService
            self.raid_lockdown_service = RaidLockdownService(self)

            from src.services.appeal_service import AppealService
            self.appeal_service = AppealService(self)
            if self.appeal_service.enabled:
                logger.tree("Appeal Service Initialized", [
                    ("Forum ID", str(self.config.appeal_forum_id)),
                    ("Min Mute Duration", "6 hours"),
                ], emoji="📝")
            else:
                logger.info("Appeal Service Disabled (no forum configured)")

            from src.services.tickets import TicketService
            self.ticket_service = TicketService(self)
            await self.ticket_service.start()
            if self.ticket_service.enabled:
                logger.tree("Ticket Service Initialized", [
                    ("Channel ID", str(self.config.ticket_channel_id)),
                    ("Auto-close", "Enabled"),
                ], emoji="🎫")
            else:
                logger.info("Ticket Service Disabled (no channel configured)")

            from src.services.modmail_service import ModmailService
            self.modmail_service = ModmailService(self)
            if self.modmail_service.enabled:
                logger.tree("Modmail Service Initialized", [
                    ("Forum ID", str(self.config.modmail_forum_id)),
                    ("For", "Banned users only"),
                ], emoji="📬")
            else:
                logger.info("Modmail Service Disabled (no forum configured)")

            # Summary of all initialized services
            logger.tree("ALL SERVICES INITIALIZED", [
                ("Prison Handler", "✓ Ready"),
                ("Mute Scheduler", "✓ Running"),
                ("Case Log", "✓ Enabled" if self.case_log_service.enabled else "✗ Disabled"),
                ("Alt Detection", "✓ Enabled" if self.alt_detection.enabled else "✗ Disabled"),
                ("Mod Tracker", "✓ Enabled" if self.mod_tracker.enabled else "✗ Disabled"),
                ("Server Logs", "✓ Enabled" if self.logging_service.enabled else "✗ Disabled"),
                ("Appeals", "✓ Enabled" if self.appeal_service.enabled else "✗ Disabled"),
                ("Tickets", "✓ Enabled" if self.ticket_service.enabled else "✗ Disabled"),
                ("Modmail", "✓ Enabled" if self.modmail_service.enabled else "✗ Disabled"),
                ("Interaction Logger", "✓ Ready"),
                ("Voice Handler", "✓ Ready"),
                ("Anti-Spam", "✓ Ready"),
                ("Anti-Nuke", "✓ Ready"),
                ("Raid Lockdown", "✓ Ready"),
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
        """Clean up poll result messages from polls channels on startup."""
        await self._scan_and_clean_poll_results()

        # Start midnight cleanup scheduler
        create_safe_task(self._polls_cleanup_scheduler(), "Polls Cleanup Scheduler")

    async def _scan_and_clean_poll_results(self) -> None:
        """Scan polls channels and delete poll result messages ('X's poll has closed')."""
        # Get both polls channels
        channel_ids = []
        if self.config.polls_only_channel_id:
            channel_ids.append(self.config.polls_only_channel_id)
        if self.config.permanent_polls_channel_id:
            channel_ids.append(self.config.permanent_polls_channel_id)

        if not channel_ids:
            logger.tree("Polls Cleanup Skipped", [
                ("Reason", "No channels configured"),
            ], emoji="⏭️")
            return

        logger.tree("Scanning Polls Channels", [
            ("Channels", str(len(channel_ids))),
            ("Limit", "100 messages each"),
        ], emoji="🔍")

        total_deleted = 0
        total_checked = 0

        for channel_id in channel_ids:
            channel = self.get_channel(channel_id)
            if not channel:
                logger.warning("Polls Cleanup Channel Not Found", [
                    ("Channel ID", str(channel_id)),
                ])
                continue

            try:
                deleted = 0
                checked = 0
                async for message in channel.history(limit=100):
                    checked += 1
                    # Delete poll result messages ("X's poll has closed")
                    if message.type == discord.MessageType.poll_result:
                        try:
                            await message.delete()
                            deleted += 1
                            await rate_limit("bulk_operation")
                        except discord.NotFound:
                            pass
                        except discord.Forbidden:
                            logger.warning("Polls Cleanup Permission Denied", [
                                ("Channel", f"#{channel.name}"),
                                ("Action", "Cannot delete poll results"),
                            ])
                            break
                        except discord.HTTPException as e:
                            logger.warning("Polls Cleanup Delete Failed", [
                                ("Channel", f"#{channel.name}"),
                                ("Error", str(e)[:50]),
                            ])

                if deleted > 0:
                    logger.tree("Poll Results Cleaned", [
                        ("Channel", f"#{channel.name}"),
                        ("Checked", str(checked)),
                        ("Deleted", str(deleted)),
                    ], emoji="🗑️")

                total_deleted += deleted
                total_checked += checked

            except Exception as e:
                logger.error("Polls Cleanup Failed", [
                    ("Channel", f"#{channel.name}" if channel else str(channel_id)),
                    ("Error", str(e)),
                ])

        if total_deleted > 0:
            logger.tree("Polls Cleanup Complete", [
                ("Channels", str(len(channel_ids))),
                ("Messages Checked", str(total_checked)),
                ("Poll Results Deleted", str(total_deleted)),
            ], emoji="✅")
        else:
            logger.tree("Polls Cleanup Complete", [
                ("Channels", str(len(channel_ids))),
                ("Messages Checked", str(total_checked)),
                ("Result", "No poll results to delete"),
            ], emoji="✅")

    async def _polls_cleanup_scheduler(self) -> None:
        """Run polls cleanup at midnight daily."""
        logger.tree("Polls Cleanup Scheduler Started", [
            ("Schedule", "Daily at midnight"),
            ("Channels", "polls_only + permanent_polls"),
        ], emoji="📅")

        while True:
            try:
                # Calculate time until next midnight
                now = datetime.now(NY_TZ)
                next_midnight = (now + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                sleep_seconds = (next_midnight - now).total_seconds()

                logger.tree("Polls Cleanup Scheduled", [
                    ("Next Run", next_midnight.strftime("%Y-%m-%d %I:%M %p")),
                    ("Sleep", f"{sleep_seconds/3600:.1f} hours"),
                ], emoji="⏰")

                await asyncio.sleep(sleep_seconds)

                # Run cleanup
                logger.tree("Midnight Polls Cleanup Starting", [
                    ("Time", datetime.now(NY_TZ).strftime("%I:%M %p %Z")),
                ], emoji="🌙")

                await self._scan_and_clean_poll_results()

            except asyncio.CancelledError:
                logger.tree("Polls Cleanup Scheduler Stopped", [
                    ("Reason", "Task cancelled"),
                ], emoji="🛑")
                break
            except Exception as e:
                logger.error("Polls Cleanup Scheduler Error", [
                    ("Error", str(e)),
                    ("Retry", "1 hour"),
                ])
                await asyncio.sleep(3600)  # Retry in 1 hour on error

    async def _cache_invites(self) -> None:
        """Cache all server invites for tracking."""
        try:
            for guild in self.guilds:
                try:
                    invites = await asyncio.wait_for(guild.invites(), timeout=5.0)
                    for invite in invites:
                        self._invite_cache[invite.code] = invite.uses or 0
                    logger.info(f"Cached {len(invites)} invites for {guild.name}")
                except discord.Forbidden:
                    pass
                except asyncio.TimeoutError:
                    logger.warning(f"Invite fetch timeout for {guild.name}")
        except Exception as e:
            logger.warning(f"Invite cache failed: {e}")

    async def _check_lockdown_state(self) -> None:
        """Check if any guild is in lockdown state on startup."""
        for guild in self.guilds:
            lockdown = self.db.get_lockdown_state(guild.id)
            if lockdown:
                locked_at = lockdown.get("locked_at", 0)
                locked_by = lockdown.get("locked_by", 0)
                channel_count = lockdown.get("channel_count", 0)
                reason = lockdown.get("reason", "None")

                logger.tree("SERVER IS LOCKED", [
                    ("Guild", f"{guild.name} ({guild.id})"),
                    ("Locked At", f"<t:{int(locked_at)}:R>"),
                    ("Locked By", str(locked_by)),
                    ("Channels", str(channel_count)),
                    ("Reason", reason or "None"),
                ], emoji="🔒")

                # Alert in logs channel
                if self.config.logs_channel_id:
                    logs_channel = guild.get_channel(self.config.logs_channel_id)
                    if logs_channel:
                        try:
                            alert_msg = (
                                f"⚠️ **Bot Restarted During Lockdown**\n"
                                f"Server is still locked since <t:{int(locked_at)}:R>\n"
                                f"Use `/unlock` to restore permissions."
                            )
                            if self.config.developer_id:
                                alert_msg = f"<@{self.config.developer_id}> {alert_msg}"
                            await logs_channel.send(alert_msg)
                        except discord.HTTPException:
                            pass

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

        # Evict oldest entries if at limit (O(1) with OrderedDict)
        # Use try/except to handle race condition with concurrent evictions
        while len(self._attachment_cache) >= self._attachment_cache_limit:
            try:
                self._attachment_cache.popitem(last=False)
            except KeyError:
                break  # Another task already evicted

        attachments = []
        for att in message.attachments:
            if att.size and att.size < 8 * 1024 * 1024:
                try:
                    data = await att.read()
                    attachments.append((att.filename, data))
                except Exception:
                    pass

        if attachments:
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

            if can_alert:
                self._last_raid_alert = current_time
                recent_members = [m for _, m in recent]

                # Log raid alert
                if self.logging_service:
                    await self.logging_service.log_raid_alert(
                        join_count=join_count,
                        time_window=self._raid_window,
                        recent_members=recent_members,
                    )

                # Trigger auto-lockdown
                if self.raid_lockdown_service:
                    await self.raid_lockdown_service.trigger_raid_lockdown(
                        guild=member.guild,
                        join_count=join_count,
                        time_window=self._raid_window,
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
    # Shared HTTP Session
    # =========================================================================

    async def get_http_session(self) -> aiohttp.ClientSession:
        """Get or create the shared HTTP session for all services."""
        if self._http_session is None or self._http_session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._http_session = aiohttp.ClientSession(timeout=timeout)
        return self._http_session

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

        if self.case_archive_scheduler:
            await self.case_archive_scheduler.stop()

        if self.ticket_service:
            await self.ticket_service.stop()

        if self.presence_handler:
            await self.presence_handler.stop()

        if self.health_server:
            await self.health_server.stop()

        if self.stats_api:
            await self.stats_api.stop()

        # Close shared HTTP session
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

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
