"""
AzabBot - Main Bot
==================

Core Discord client with prisoner tracking and moderation services.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import asyncio
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
from src.utils.discord_rate_limit import log_http_error
from src.utils.http import http_session
from src.core.constants import (
    GUILD_FETCH_TIMEOUT,
    SECONDS_PER_HOUR,
    QUERY_LIMIT_LARGE,
    EDITSNIPE_CACHE_TTL,
)


# =============================================================================
# Guild Protection
# =============================================================================

def get_authorized_guilds() -> set:
    """Get authorized guild IDs from config (loaded after dotenv)."""
    config = get_config()
    guilds = set()
    if config.main_guild_id:
        guilds.add(config.main_guild_id)
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
        intents.presences = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
            chunk_guilds_at_startup=True,  # Load all members into cache for search
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
        self.case_archiver = None
        self.mod_tracker = None
        self.logging_service = None
        self.voice = None
        self.antispam_service = None
        self.antinuke_service = None
        self.raid_lockdown_service = None
        self.appeal_service = None
        self.ticket_service = None
        self.ai_service = None
        self.api_service = None
        self.content_moderation = None
        self.maintenance = None
        self.prisoner_service = None

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
        # Start unified HTTP session
        await http_session.start(user_agent="AzabBot/1.0")

        # Load command cogs
        from src.commands import COMMAND_COGS
        for cog in COMMAND_COGS:
            try:
                await self.load_extension(cog)
                logger.info("Cog Loaded", [("Cog", cog.split('.')[-1])])
            except Exception as e:
                logger.error("Failed to Load Cog", [("Cog", cog), ("Error", str(e))])

        # Load event cogs
        from src.handlers import EVENT_COGS
        for cog in EVENT_COGS:
            try:
                await self.load_extension(cog)
                logger.debug("Event Cog Loaded", [("Cog", cog.split('.')[-1])])
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

        from src.services.jawdat_economy import setup_jawdat_economy
        setup_jawdat_economy(self)

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
            if self.config.main_guild_id:
                guild = discord.Object(id=self.config.main_guild_id)
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
        self._cleanup_unjail_records()

        # Backfill historical join positions (runs once in background)
        create_safe_task(self._backfill_join_positions(), "Join Position Backfill")

        logger.tree("AZAB READY", [
            ("Prison Handler", "Ready" if self.prison else "Missing"),
            ("Mute Scheduler", "Running" if self.mute_scheduler else "Stopped"),
            ("Case Log", "Enabled" if self.case_log_service and self.case_log_service.enabled else "Disabled"),
            ("Mod Tracker", "Enabled" if self.mod_tracker and self.mod_tracker.enabled else "Disabled"),
            ("API Service", "Running" if self.api_service else "Stopped"),
        ], emoji="🔥")

    # =========================================================================
    # Health Tracking
    # =========================================================================

    async def on_disconnect(self) -> None:
        """Track disconnection for health monitoring."""
        from src.api.services.health_tracker import get_health_tracker
        health_tracker = get_health_tracker()
        health_tracker.record_reconnect()
        logger.debug("Bot Disconnected", [("Reconnects", str(health_tracker.reconnect_count))])

    async def on_resumed(self) -> None:
        """Track resume after disconnect."""
        logger.info("Bot Connection Resumed")

    async def on_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        """Broadcast presence changes to dashboard WebSocket clients watching this user."""
        # Only care about online/offline transitions
        was_online = str(before.status) != "offline"
        is_online = str(after.status) != "offline"

        if was_online == is_online:
            return  # No change in online/offline state

        try:
            from src.api.services.websocket import get_ws_manager
            ws_manager = get_ws_manager()

            # Only broadcast if someone is watching this user
            if after.id in ws_manager.get_watched_users():
                await ws_manager.broadcast_user_presence(after.id, is_online)
        except Exception:
            pass  # Don't let presence errors affect bot operation

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
        """
        Initialize all services after Discord connection.

        SERVICE INITIALIZATION ORDER (dependencies in parentheses):
        ==========================================================
        1. PrisonerService       - Core prisoner management
        2. PrisonHandler         - Prison channel events (needs PrisonerService)
        3. MuteHandler           - Mute embed parsing (needs PrisonHandler)
        4. PresenceHandler       - Status rotation (independent)
        5. MaintenanceService    - Cleanup tasks (independent)
        6. APIService            - REST API server (independent)
        7. BackupScheduler       - Database backups (independent)
        8. MuteScheduler         - Mute expiration checks (needs db)
        9. CaseLogService        - Case logging to forum (needs db)
        10. CaseArchiveScheduler - Archive old cases (needs CaseLogService)
        11. ModTrackerService    - Mod action tracking (needs db)
        12. LoggingService       - Server event logging (independent)
        13. VoiceHandler         - Voice channel events (independent)
        14. AntiSpamService      - Spam detection (independent)
        15. ContentModerationService - Content filtering (independent)
        16. AntiNukeService      - Raid protection (independent)
        17. RaidLockdownService  - Auto-lockdown (needs AntiNukeService)
        18. AppealService        - Ban/mute appeals (needs CaseLogService)
        19. AIService            - OpenAI integration (independent)
        20. TicketService        - Support tickets (needs AIService)
        21. UserSnapshotsService - Avatar/name tracking (independent)

        IMPORTANT: Do not reorder without understanding dependencies.
        """
        # Guard against re-initialization on reconnects
        if self.prison is not None:
            logger.debug("Services already initialized, skipping")
            return

        # Leave unauthorized guilds before initializing services
        await self._leave_unauthorized_guilds()

        try:
            from src.services.prisoner import PrisonerService
            self.prisoner_service = PrisonerService(self)

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

            from src.api import APIService
            self.api_service = APIService(self)
            await self.api_service.start()

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

                # Start case archiver
                from src.services.case_archiver import CaseArchiveScheduler
                self.case_archiver = CaseArchiveScheduler(self)
                await self.case_archiver.start()
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
            elif self.config.server_logs_forum_id:
                # Forum ID is configured but initialization failed - this is an error
                logger.error("Logging Service FAILED", [
                    ("Forum ID", str(self.config.server_logs_forum_id)),
                    ("Impact", "Server logs will NOT be sent"),
                    ("Check", "Forum exists, bot has access, correct guild"),
                ])
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

            from src.services.ai import AIService
            self.ai_service = AIService(self)

            from src.services.tickets import TicketService
            self.ticket_service = TicketService(self)
            await self.ticket_service.start()
            if self.ticket_service.enabled:
                logger.tree("Ticket Service Initialized", [
                    ("Channel ID", str(self.config.ticket_channel_id)),
                    ("Auto-close", "Enabled"),
                    ("AI Greeting", "Enabled" if self.ai_service.enabled else "Disabled"),
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
                ("AI Service", "✓ Enabled" if self.ai_service.enabled else "✗ Disabled"),
                ("Interaction Logger", "✓ Ready"),
                ("Voice Handler", "✓ Ready"),
                ("Anti-Spam", "✓ Ready"),
                ("Anti-Nuke", "✓ Ready"),
                ("Raid Lockdown", "✓ Ready"),
                ("Content Moderation", "✓ Enabled" if self.content_moderation and self.content_moderation.enabled else "✗ Disabled"),
            ], emoji="🚀")

        except Exception as e:
            import traceback
            logger.error("Service Initialization Failed", [
                ("Error", str(e)),
                ("Traceback", traceback.format_exc()[:500]),
            ])

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def is_user_muted(self, member: discord.Member) -> bool:
        """Check if user has the muted role."""
        return any(role.id == self.config.muted_role_id for role in member.roles)

    async def _backfill_join_positions(self) -> None:
        """
        Backfill historical join positions for all guild members.

        Runs once on startup. Positions are assigned based on original
        join date, sorted oldest to newest. Positions are permanent and
        persist even if members leave and rejoin.
        """
        guild_id = self.config.main_guild_id
        if not guild_id:
            return

        guild = self.get_guild(guild_id)
        if not guild:
            return

        member_count = guild.member_count or len(guild.members)

        # Check if already backfilled (count should be close to member count)
        existing_count = self.db.get_total_join_positions(guild_id)
        if existing_count > member_count * 0.5:
            logger.debug("Join Position Backfill Skipped", [
                ("Reason", "Already backfilled"),
                ("Existing", str(existing_count)),
                ("Members", str(member_count)),
            ])
            return

        # If we have very few positions but many members, clear the bad data
        if existing_count > 0 and existing_count < 100:
            logger.warning("Clearing Invalid Join Positions", [
                ("Bad Count", str(existing_count)),
                ("Expected", f"~{member_count}"),
            ])
            self.db.execute(
                "DELETE FROM member_join_positions WHERE guild_id = ?",
                (guild_id,)
            )
            self.db.execute(
                "DELETE FROM guild_join_counters WHERE guild_id = ?",
                (guild_id,)
            )

        # Get historical first_joined_at from member_activity (more accurate)
        historical_joins = {}
        rows = self.db.fetchall(
            "SELECT user_id, first_joined_at FROM member_activity WHERE guild_id = ? AND first_joined_at IS NOT NULL",
            (guild_id,)
        )
        for row in rows:
            historical_joins[row["user_id"]] = row["first_joined_at"]

        # Collect all members - prefer historical data, fall back to current joined_at
        members_data = []
        for member in guild.members:
            first_join = historical_joins.get(member.id)
            if first_join:
                members_data.append((member.id, first_join))
            elif member.joined_at:
                members_data.append((member.id, member.joined_at.timestamp()))

        if not members_data:
            return

        # Sort by join time (oldest first)
        members_data.sort(key=lambda x: x[1])

        # Backfill
        backfilled = self.db.backfill_join_positions(guild_id, members_data)

        logger.tree("JOIN POSITIONS BACKFILLED", [
            ("Guild", guild.name),
            ("Members", str(len(members_data))),
            ("Positions Assigned", str(backfilled)),
        ], emoji="📊")

    async def _cleanup_polls_channel(self) -> None:
        """Clean up poll result messages from polls channels on startup."""
        await self._scan_and_clean_poll_results()

    async def _scan_and_clean_poll_results(self) -> None:
        """Scan polls channels and delete poll result messages ('X's poll has closed')."""
        # Get polls channels from config (polls_only_channel_ids is a set)
        channel_ids = list(self.config.polls_only_channel_ids) if self.config.polls_only_channel_ids else []

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
                            log_http_error(e, "Polls Cleanup Delete", [
                                ("Channel", f"#{channel.name}"),
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

        Delegates to PrisonerService.cleanup_stale_entries().

        Returns:
            Number of entries cleaned up.
        """
        if self.prisoner_service:
            return await self.prisoner_service.cleanup_stale_entries()
        return 0

    def _cleanup_unjail_records(self) -> None:
        """Clean up old unjail card usage records (older than 7 days)."""
        try:
            deleted = self.db.cleanup_old_unjail_records(days=7)
            if deleted > 0:
                logger.tree("Unjail Records Cleaned", [
                    ("Deleted", str(deleted)),
                ], emoji="🔓")
        except Exception as e:
            logger.warning("Unjail Cleanup Failed", [
                ("Error", str(e)[:50]),
            ])

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
            logger.debug("EditSnipe Cache Cleanup", [("Removed", str(cleaned))])

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
                    logger.info("Invites Cached", [("Count", str(len(invites))), ("Guild", guild.name)])
                except discord.Forbidden:
                    logger.debug("No Permission to Fetch Invites", [("Guild", guild.name)])
                except asyncio.TimeoutError:
                    logger.warning("Invite Fetch Timeout", [("Guild", guild.name)])
        except Exception as e:
            logger.warning("Invite Cache Failed", [("Error", str(e)[:50])])

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
                            log_http_error(e, "Lockdown Restart Alert", [])

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
            logger.debug("No Permission to Check Invites", [("Guild", guild.name)])
        except Exception as e:
            logger.debug("Find Invite Failed", [("Error", str(e)[:50])])
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
                except discord.HTTPException:
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

        if self.config.main_guild_id and channel.guild.id != self.config.main_guild_id:
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
            logger.warning("No Permission to Hide Channel", [("Channel", f"#{channel.name}")])
        except discord.HTTPException as e:
            log_http_error(e, "Auto-Hide Channel", [("Channel", f"#{channel.name}")])

    # =========================================================================
    # Shutdown
    # =========================================================================

    async def shutdown(self) -> None:
        """Graceful shutdown with proper cleanup."""
        logger.info("Initiating Graceful Shutdown")

        if self.mute_scheduler:
            await self.mute_scheduler.stop()

        if self.case_log_service and self.case_log_service.enabled:
            await self.case_log_service.stop_reason_scheduler()

        if self.case_archiver:
            await self.case_archiver.stop()

        if self.ticket_service:
            await self.ticket_service.stop()

        if self.presence:
            await self.presence.stop()

        if self.api_service:
            await self.api_service.stop()

        if hasattr(self, 'backup_scheduler') and self.backup_scheduler:
            await self.backup_scheduler.stop()

        # Close unified HTTP session
        await http_session.stop()

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
