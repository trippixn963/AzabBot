"""
AzabBot - Main Bot
==================

Core Discord client with prisoner tracking and moderation services.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
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
from src.core.constants import (
    GUILD_FETCH_TIMEOUT,
    SECONDS_PER_HOUR,
    QUERY_LIMIT_LARGE,
    EDITSNIPE_CACHE_TTL,
)

# Constants for cache limits
PRISONER_TRACKING_LIMIT = 1000  # Max prisoner tracking entries
MESSAGE_BUFFER_LIMIT = 50  # Max messages per prisoner buffer


# =============================================================================
# Guild Protection
# =============================================================================

def get_authorized_guilds() -> set:
    """Get authorized guild IDs from config (loaded after dotenv)."""
    config = get_config()
    guilds = set()
    if config.logging_guild_id:
        guilds.add(config.logging_guild_id)
    if config.mod_server_id:
        guilds.add(config.mod_server_id)
    return guilds


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
        self.prison = None
        self.mute = None
        self.presence = None
        self.mute_scheduler = None
        self.case_log_service = None
        self.case_archive_scheduler = None
        self.mod_tracker = None
        self.logging_service = None
        self.webhook_alert_service = None
        self.voice = None
        self.antispam_service = None
        self.antinuke_service = None
        self.raid_lockdown_service = None
        self.appeal_service = None
        self.ticket_service = None
        self.stats_api = None
        self.content_moderation = None
        self.maintenance = None

        # Shared HTTP session for all services
        self._http_session: Optional[aiohttp.ClientSession] = None

        # Prisoner rate limiting (with async lock for thread safety)
        # IMPORTANT: All three dicts below MUST be accessed within `async with self._prisoner_lock:`
        self._prisoner_lock = asyncio.Lock()
        self.prisoner_cooldowns: Dict[int, datetime] = {}  # Protected by _prisoner_lock
        self.prisoner_message_buffer: Dict[int, List[str]] = {}  # Protected by _prisoner_lock
        self.prisoner_pending_response: Dict[int, bool] = {}  # Protected by _prisoner_lock

        # Message history tracking (LRU cache with limit)
        self._last_messages_lock = asyncio.Lock()
        self.last_messages: OrderedDict[int, dict] = OrderedDict()
        self._last_messages_limit: int = 5000

        # Invite cache (with limit to prevent unbounded growth)
        self._invite_cache: Dict[str, int] = {}
        self._invite_cache_limit: int = 1000

        # Message attachment cache (OrderedDict for O(1) LRU eviction)
        self._attachment_cache_lock = asyncio.Lock()
        self._attachment_cache: OrderedDict[int, List[tuple]] = OrderedDict()
        self._attachment_cache_limit: int = 500

        # Message content cache (OrderedDict for O(1) LRU eviction)
        self._message_cache_lock = asyncio.Lock()
        self._message_cache: OrderedDict[int, dict] = OrderedDict()
        self._message_cache_limit: int = 5000

        # Snipe cache (channel_id -> deque of last 10 deleted messages)
        self._snipe_cache: Dict[int, deque] = {}
        self._snipe_limit: int = 10

        # Edit snipe cache (channel_id -> deque of last 10 edits)
        self._editsnipe_cache_lock = asyncio.Lock()
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
        from src.handlers import EVENT_COGS
        for cog in EVENT_COGS:
            try:
                await self.load_extension(cog)
                logger.debug(f"Event Cog Loaded: {cog.split('.')[-1]}")
            except Exception as e:
                logger.error("Failed to Load Event Cog", [("Cog", cog), ("Error", str(e))])

        # Register persistent views
        from src.services.server_logs.service import setup_log_views
        setup_log_views(self)

        from src.views import setup_moderation_views
        setup_moderation_views(self)

        from src.services.appeals import setup_appeal_views
        setup_appeal_views(self)

        from src.services.tickets import setup_ticket_views
        setup_ticket_views(self)

        from src.services.case_log.views import setup_case_log_views
        setup_case_log_views(self)

        # Block slash commands in DMs (buttons/modals still work for appeals)
        @self.tree.interaction_check
        async def global_interaction_check(interaction: discord.Interaction) -> bool:
            """
            Global check that runs before any slash command.

            Blocks all slash commands in DMs while allowing buttons/modals
            to continue working (for appeal system, etc.).

            NOTE: This only affects ApplicationCommand interactions.
            Component (button) and ModalSubmit interactions bypass this check.
            """
            if interaction.guild is None:
                # DM command attempt
                logger.tree("DM Command Blocked", [
                    ("User", f"{interaction.user.name} ({interaction.user.id})"),
                    ("Command", interaction.command.name if interaction.command else "Unknown"),
                ], emoji="🚫")

                try:
                    await interaction.response.send_message(
                        "❌ Commands are not available in DMs. Please use commands in the server.",
                        ephemeral=True,
                    )
                except discord.HTTPException:
                    pass

                return False  # Block the command

            return True  # Allow in guilds

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

        # Auto-ignore bot's own ID in logs to prevent clutter
        if self.config.ignored_bot_ids is None:
            self.config.ignored_bot_ids = set()
        self.config.ignored_bot_ids.add(self.user.id)

        logger.startup_banner(
            "AzabBot",
            self.user.id,
            len(self.guilds),
            self.latency * 1000,
        )

        # Initialize footer first so embeds have server icon
        from src.utils.footer import init_footer
        await init_footer(self)

        await self._init_services()

        from src.utils.metrics import init_metrics
        init_metrics()

        self.disabled = not self.db.is_active()
        logger.tree("Bot State Loaded", [("Active", str(not self.disabled))], emoji="ℹ️")

        if self.presence:
            create_safe_task(self.presence.start(), "Presence Handler")

        if self.maintenance:
            self.maintenance.start()

        await self._cleanup_polls_channel()
        await self._cache_invites()
        await self._check_lockdown_state()

        logger.tree("AZAB READY", [
            ("Prison Handler", "Ready" if self.prison else "Missing"),
            ("Mute Scheduler", "Running" if self.mute_scheduler else "Stopped"),
            ("Case Log", "Enabled" if self.case_log_service and self.case_log_service.enabled else "Disabled"),
            ("Mod Tracker", "Enabled" if self.mod_tracker and self.mod_tracker.enabled else "Disabled"),
            ("Stats API", "Running" if self.stats_api else "Stopped"),
            ("Webhook Alerts", "Enabled" if self.webhook_alert_service and self.webhook_alert_service.enabled else "Disabled"),
        ], emoji="🔥")

    # =========================================================================
    # Guild Protection
    # =========================================================================

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Leave immediately if guild is not authorized."""
        authorized = get_authorized_guilds()
        # Safety: Don't leave if authorized set is empty (misconfigured env)
        if not authorized:
            return
        if guild.id not in authorized:
            logger.warning("Added To Unauthorized Guild - Leaving", [
                ("Guild", guild.name),
                ("ID", str(guild.id)),
                ("Authorized", str(authorized)),
            ])
            try:
                await guild.leave()
            except Exception as e:
                logger.error("Failed To Leave Unauthorized Guild", [
                    ("Guild", guild.name),
                    ("Error", str(e)),
                ])

    async def _leave_unauthorized_guilds(self) -> None:
        """Leave any guilds not in authorized list."""
        authorized = get_authorized_guilds()
        # Safety: Don't leave any guilds if authorized set is empty (misconfigured env)
        if not authorized:
            logger.warning("Guild Protection Skipped", [
                ("Reason", "Authorized guild set is empty"),
                ("Action", "Check GUILD_ID and MODS_GUILD_ID in .env"),
            ])
            return
        unauthorized = [g for g in self.guilds if g.id not in authorized]
        if not unauthorized:
            return

        logger.tree("Leaving Unauthorized Guilds", [
            ("Count", str(len(unauthorized))),
        ], emoji="⚠️")

        for guild in unauthorized:
            try:
                logger.warning("Leaving Unauthorized Guild", [
                    ("Guild", guild.name),
                    ("ID", str(guild.id)),
                ])
                await guild.leave()
            except Exception as e:
                logger.error("Failed To Leave Guild", [
                    ("Guild", guild.name),
                    ("Error", str(e)),
                ])

    # =========================================================================
    # Service Initialization
    # =========================================================================

    async def _init_services(self) -> None:
        """Initialize all services after Discord connection."""
        # Guard against re-initialization on reconnects
        if self.prison is not None:
            logger.debug("Services already initialized, skipping")
            return

        # Leave unauthorized guilds before initializing services
        await self._leave_unauthorized_guilds()

        try:
            from src.handlers.prison import PrisonHandler
            self.prison = PrisonHandler(self)
            logger.info("Prison Handler Initialized")

            from src.handlers.mute import MuteHandler
            self.mute = MuteHandler(self.prison)
            logger.info("Mute Handler Initialized")

            from src.services.presence import PresenceHandler
            self.presence = PresenceHandler(self)
            logger.info("Presence Handler Initialized")

            from src.services.maintenance import MaintenanceService
            self.maintenance = MaintenanceService(self)

            from src.services.stats_api import AzabAPI
            self.stats_api = AzabAPI(self)
            await self.stats_api.start()

            from src.services.backup import BackupScheduler
            self.backup_scheduler = BackupScheduler()
            await self.backup_scheduler.start()

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

            from src.services.mod_tracker import ModTrackerService
            self.mod_tracker = ModTrackerService(self)
            if self.mod_tracker.enabled:
                logger.tree("Mod Tracker Service Initialized", [
                    ("Server ID", str(self.config.mod_server_id)),
                    ("Forum ID", str(self.config.mod_logs_forum_id)),
                    ("Role ID", str(self.config.moderation_role_id)),
                ], emoji="👁️")
                await self.mod_tracker.auto_scan_mods()
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

            from src.handlers.voice import VoiceHandler
            self.voice = VoiceHandler(self)
            logger.info("Voice Handler Initialized")

            from src.services.antispam import AntiSpamService
            self.antispam_service = AntiSpamService(self)

            from src.services.content_moderation import ContentModerationService
            self.content_moderation = ContentModerationService(self)

            from src.services.antinuke import AntiNukeService
            self.antinuke_service = AntiNukeService(self)

            from src.services.raid_lockdown import RaidLockdownService
            self.raid_lockdown_service = RaidLockdownService(self)

            from src.services.appeals import AppealService
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

            # Summary of all initialized services
            logger.tree("ALL SERVICES INITIALIZED", [
                ("Prison Handler", "✓ Ready"),
                ("Mute Scheduler", "✓ Running"),
                ("Case Log", "✓ Enabled" if self.case_log_service.enabled else "✗ Disabled"),
                ("Mod Tracker", "✓ Enabled" if self.mod_tracker.enabled else "✗ Disabled"),
                ("Server Logs", "✓ Enabled" if self.logging_service.enabled else "✗ Disabled"),
                ("Appeals", "✓ Enabled" if self.appeal_service.enabled else "✗ Disabled"),
                ("Tickets", "✓ Enabled" if self.ticket_service.enabled else "✗ Disabled"),
                ("Interaction Logger", "✓ Ready"),
                ("Voice Handler", "✓ Ready"),
                ("Anti-Spam", "✓ Ready"),
                ("Anti-Nuke", "✓ Ready"),
                ("Raid Lockdown", "✓ Ready"),
                ("Content Moderation", "✓ Enabled" if self.content_moderation and self.content_moderation.enabled else "✗ Disabled"),
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
            ("Limit", f"{QUERY_LIMIT_LARGE} messages each"),
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
                async for message in channel.history(limit=QUERY_LIMIT_LARGE):
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

    async def _cleanup_prisoner_tracking(self) -> int:
        """
        Clean up prisoner tracking for users no longer muted.

        Removes entries from prisoner_cooldowns, prisoner_message_buffer,
        and prisoner_pending_response for users not currently muted.

        Returns:
            Number of entries cleaned up.
        """
        if not self.config.muted_role_id:
            return 0

        # Get all currently muted user IDs across all guilds
        muted_user_ids: set = set()
        for guild in self.guilds:
            for member in guild.members:
                if any(r.id == self.config.muted_role_id for r in member.roles):
                    muted_user_ids.add(member.id)

        cleaned = 0

        # Use lock to prevent race conditions during cleanup
        async with self._prisoner_lock:
            # Clean cooldowns
            for user_id in list(self.prisoner_cooldowns.keys()):
                if user_id not in muted_user_ids:
                    self.prisoner_cooldowns.pop(user_id, None)
                    cleaned += 1

            # Clean message buffers
            for user_id in list(self.prisoner_message_buffer.keys()):
                if user_id not in muted_user_ids:
                    self.prisoner_message_buffer.pop(user_id, None)
                    cleaned += 1

            # Clean pending response flags
            for user_id in list(self.prisoner_pending_response.keys()):
                if user_id not in muted_user_ids:
                    self.prisoner_pending_response.pop(user_id, None)
                    cleaned += 1

            # Enforce max size limits (evict oldest entries if over limit)
            while len(self.prisoner_cooldowns) > PRISONER_TRACKING_LIMIT:
                try:
                    oldest_key = next(iter(self.prisoner_cooldowns))
                    self.prisoner_cooldowns.pop(oldest_key, None)
                    cleaned += 1
                except StopIteration:
                    break

        if cleaned > 0:
            logger.debug(f"Prisoner tracking cleanup: {cleaned} stale entries removed")

        return cleaned

    async def _cleanup_editsnipe_cache(self) -> int:
        """
        Clean up stale editsnipe cache entries based on TTL.

        Removes channels that haven't had edits tracked in EDITSNIPE_CACHE_TTL.
        This prevents unbounded memory growth from inactive channels.

        Returns:
            Number of channels removed from cache.
        """
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(seconds=EDITSNIPE_CACHE_TTL)
        cleaned = 0

        async with self._editsnipe_cache_lock:
            # Check each channel's most recent edit timestamp
            stale_channels = []
            for channel_id, edits in list(self._editsnipe_cache.items()):
                if edits:
                    # Get timestamp of most recent edit (edits are stored newest first)
                    most_recent = edits[0] if edits else None
                    if most_recent:
                        edit_time = most_recent.get("edited_at")
                        if edit_time and edit_time < cutoff:
                            stale_channels.append(channel_id)
                else:
                    # Empty deque, remove it
                    stale_channels.append(channel_id)

            # Remove stale channels
            for channel_id in stale_channels:
                self._editsnipe_cache.pop(channel_id, None)
                cleaned += 1

        if cleaned > 0:
            logger.debug(f"EditSnipe cache cleanup: {cleaned} stale channels removed")

        return cleaned

    async def _cache_invites(self) -> None:
        """Cache all server invites for tracking."""
        try:
            # Clear old cache and rebuild to prevent stale entries
            self._invite_cache.clear()
            for guild in self.guilds:
                try:
                    invites = await asyncio.wait_for(guild.invites(), timeout=GUILD_FETCH_TIMEOUT)
                    for invite in invites:
                        # Enforce cache limit
                        if len(self._invite_cache) >= self._invite_cache_limit:
                            break
                        self._invite_cache[invite.code] = invite.uses or 0
                    logger.info(f"Cached {len(invites)} invites for {guild.name}")
                except discord.Forbidden:
                    logger.debug(f"No permission to fetch invites for {guild.name}")
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

                # Alert in alert channel (not forum)
                if self.config.alert_channel_id:
                    alert_channel = guild.get_channel(self.config.alert_channel_id)
                    if alert_channel and not isinstance(alert_channel, discord.ForumChannel):
                        try:
                            alert_msg = (
                                f"⚠️ **Bot Restarted During Lockdown**\n"
                                f"Server is still locked since <t:{int(locked_at)}:R>\n"
                                f"Use `/unlock` to restore permissions."
                            )
                            if self.config.owner_id:
                                alert_msg = f"<@{self.config.owner_id}> {alert_msg}"
                            await alert_channel.send(alert_msg)
                        except discord.HTTPException as e:
                            logger.warning(f"Failed to send lockdown restart alert: {e}")

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
            logger.debug(f"No permission to check invites for {guild.name}")
        except Exception as e:
            logger.debug(f"Find invite failed: {e}")
        return None

    async def _cache_message_attachments(self, message: discord.Message) -> None:
        """Download and cache message attachments."""
        if not message.attachments:
            return

        # Download attachments first (outside lock to avoid blocking)
        attachments = []
        for att in message.attachments:
            if att.size and att.size < 8 * 1024 * 1024:
                try:
                    data = await att.read()
                    attachments.append((att.filename, data))
                except Exception:
                    pass

        if not attachments:
            return

        # Use lock for cache modification to prevent race conditions
        async with self._attachment_cache_lock:
            # Evict oldest entries if at limit (O(1) with OrderedDict)
            while len(self._attachment_cache) >= self._attachment_cache_limit:
                try:
                    self._attachment_cache.popitem(last=False)
                except KeyError:
                    break  # Cache was cleared by another task

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

        if self.presence:
            await self.presence.stop()

        if self.stats_api:
            await self.stats_api.stop()

        if hasattr(self, 'backup_scheduler') and self.backup_scheduler:
            await self.backup_scheduler.stop()

        # Close shared HTTP session
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

        # Close logger webhook session
        await logger.close_webhook_session()

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
