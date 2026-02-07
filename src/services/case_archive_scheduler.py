"""
AzabBot - Case Archive Scheduler
================================

Background service for automatic deletion of old case threads.

DESIGN:
    Runs as a background task checking for active cases older than retention period.
    Builds and saves transcripts before deleting threads.
    Marks cases as resolved and clears thread_id after deletion.

    Retention periods:
    - Ban cases: 14 days after creation
    - Other cases (mute, warn, forbid): 7 days after creation

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import discord
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from src.core.logger import logger
from src.core.config import get_config, NY_TZ
from src.core.database import get_db
from src.core.constants import CASE_ARCHIVE_CHECK_INTERVAL, QUERY_LIMIT_LARGE
from src.utils.async_utils import create_safe_task
from src.utils.discord_rate_limit import log_http_error
from src.services.case_log.transcript import TranscriptBuilder

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Action-type-based retention (days after creation)
RETENTION_DAYS_BAN = 14
RETENTION_DAYS_DEFAULT = 7

CHECK_INTERVAL_HOURS = 1


# =============================================================================
# Case Archive Scheduler
# =============================================================================

class CaseArchiveScheduler:
    """
    Background service for automatic case thread deletion.

    DESIGN:
        Runs a loop every hour checking for active case threads.
        Builds transcripts before deletion for permanent record.
        Deletes threads based on retention period (7d mute/warn, 14d ban).
        Marks cases as resolved and clears thread_id after deletion.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
        db: Database manager.
        assets_thread_id: Thread ID for storing transcript assets.
        task: Background task reference.
        running: Whether the scheduler is active.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the case archive scheduler.

        Args:
            bot: Main bot instance.
        """
        self.bot = bot
        self.config = get_config()
        self.db = get_db()
        self.assets_thread_id: Optional[int] = None
        self.task: Optional[asyncio.Task] = None
        self.running: bool = False

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    async def start(self) -> None:
        """
        Start the case archive scheduler background task.

        DESIGN:
            Cancels any existing task before starting new one.
            Auto-creates transcript assets thread if needed.
        """
        if self.task and not self.task.done():
            self.task.cancel()

        # Auto-create assets thread if not configured
        await self._ensure_assets_thread()

        self.running = True
        self.task = create_safe_task(self._scheduler_loop(), "Case Archive Scheduler")

        logger.tree("Case Archive Scheduler Started", [
            ("Retention (Ban)", f"{RETENTION_DAYS_BAN} days"),
            ("Retention (Other)", f"{RETENTION_DAYS_DEFAULT} days"),
            ("Check Interval", f"{CHECK_INTERVAL_HOURS} hour(s)"),
            ("Assets Thread", str(self.assets_thread_id) if self.assets_thread_id else "None"),
        ], emoji="🗑️")

    async def _ensure_assets_thread(self) -> None:
        """
        Ensure the transcript assets thread exists.
        Creates it in the logs forum if not configured.
        """
        self.assets_thread_id = self.config.transcript_assets_thread_id

        # If already configured, verify it exists
        if self.assets_thread_id:
            try:
                thread = await self.bot.fetch_channel(self.assets_thread_id)
                if thread:
                    return
            except discord.NotFound:
                logger.warning("Configured Assets Thread Not Found", [
                    ("Thread ID", str(self.assets_thread_id)),
                ])
                self.assets_thread_id = None
            except discord.HTTPException:
                return

        # Try to create in logs forum
        if not self.config.server_logs_forum_id:
            return

        try:
            forum = self.bot.get_channel(self.config.server_logs_forum_id)
            if not forum:
                forum = await self.bot.fetch_channel(self.config.server_logs_forum_id)

            if not forum or not isinstance(forum, discord.ForumChannel):
                return

            # Known asset thread names (current and legacy)
            asset_thread_names = {"📁 Assets", "Assets", "Transcript Assets"}

            # Check if thread already exists by name
            async for thread in forum.archived_threads(limit=QUERY_LIMIT_LARGE):
                if thread.name in asset_thread_names:
                    self.assets_thread_id = thread.id
                    # Rename to current standard if using old name
                    if thread.name != "📁 Assets":
                        try:
                            await thread.edit(name="📁 Assets")
                            logger.info("Renamed Assets Thread", [
                                ("Old Name", thread.name),
                                ("New Name", "📁 Assets"),
                            ])
                        except discord.Forbidden:
                            logger.debug("Case Archive Rename Denied", [("Thread", str(thread.id))])
                        except Exception as e:
                            logger.warning("Case Archive: Failed to rename assets thread", [
                                ("Thread ID", str(thread.id)),
                                ("Error", str(e)[:50]),
                            ])
                    logger.info("Found Existing Assets Thread", [
                        ("Thread ID", str(thread.id)),
                    ])
                    return

            for thread in forum.threads:
                if thread.name in asset_thread_names:
                    self.assets_thread_id = thread.id
                    # Rename to current standard if using old name
                    if thread.name != "📁 Assets":
                        try:
                            await thread.edit(name="📁 Assets")
                            logger.info("Renamed Assets Thread", [
                                ("Old Name", thread.name),
                                ("New Name", "📁 Assets"),
                            ])
                        except discord.Forbidden:
                            logger.debug("Case Archive Rename Denied", [("Thread", str(thread.id))])
                        except Exception as e:
                            logger.warning("Case Archive: Failed to rename assets thread", [
                                ("Thread ID", str(thread.id)),
                                ("Error", str(e)[:50]),
                            ])
                    logger.info("Found Existing Assets Thread", [
                        ("Thread ID", str(thread.id)),
                    ])
                    return

            # Create new thread
            thread_with_msg = await forum.create_thread(
                name="📁 Assets",
                content="This thread stores permanent copies of attachments for cases and transcripts.\n\n*Do not delete this thread.*",
            )
            self.assets_thread_id = thread_with_msg.thread.id

            logger.tree("Created Assets Thread", [
                ("Thread ID", str(self.assets_thread_id)),
                ("Forum", forum.name),
            ], emoji="📁")

        except Exception as e:
            logger.warning("Failed To Create Assets Thread", [
                ("Error", str(e)[:50]),
            ])

    async def stop(self) -> None:
        """
        Stop the case archive scheduler background task.
        """
        self.running = False

        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.info("Case Archive Scheduler Stopped")

    # =========================================================================
    # Scheduler Loop
    # =========================================================================

    async def _scheduler_loop(self) -> None:
        """
        Main scheduler loop.

        DESIGN:
            Runs every hour checking for old active case threads.
            Continues running even if individual deletions fail.
        """
        await self.bot.wait_until_ready()

        # Wait a bit on startup to let other services initialize
        await asyncio.sleep(CASE_ARCHIVE_CHECK_INTERVAL)

        while self.running:
            try:
                await self._process_old_cases()
                await asyncio.sleep(CHECK_INTERVAL_HOURS * 3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Case Archive Scheduler Error", [
                    ("Error", str(e)[:100]),
                ])
                # Send error alert to webhook
                if self.bot.webhook_alert_service:
                    await self.bot.webhook_alert_service.send_error_alert(
                        "Case Archive Scheduler Error",
                        str(e)[:500]
                    )
                await asyncio.sleep(CHECK_INTERVAL_HOURS * 3600)

    # =========================================================================
    # Case Processing
    # =========================================================================

    async def _process_old_cases(self) -> None:
        """
        Process old cases and delete their threads.

        DESIGN:
            Auto-deletes cases based on creation time:
            - Ban: 14 days after creation
            - Other (mute, warn, etc.): 7 days after creation
            Builds and saves transcript before deletion.
            Marks the case as resolved in the database.
        """
        now = datetime.now(NY_TZ)

        # Get old cases for each retention category
        ban_cutoff = (now - timedelta(days=RETENTION_DAYS_BAN)).timestamp()
        default_cutoff = (now - timedelta(days=RETENTION_DAYS_DEFAULT)).timestamp()

        old_cases = self.db.get_old_cases_for_deletion(
            ban_cutoff=ban_cutoff,
            default_cutoff=default_cutoff,
        )

        if not old_cases:
            return

        deleted_count = 0
        transcript_count = 0
        failed_count = 0

        for case in old_cases:
            case_id = case.get("case_id")
            if not case_id:
                failed_count += 1
                continue

            try:
                # Build and save transcript FIRST (before any deletion)
                transcript_saved = await self._save_transcript(case)
                if transcript_saved:
                    transcript_count += 1

                # Delete the thread from Discord
                thread_deleted = await self._delete_case_thread(case)

                # Mark case as resolved and clear thread_id
                self.db.archive_case(case_id)
                if thread_deleted:
                    self.db.clear_case_thread_id(case_id)

                deleted_count += 1

            except Exception as e:
                logger.error("Failed To Archive Case", [
                    ("Case ID", case_id),
                    ("Error", str(e)[:100]),
                ])
                failed_count += 1

        if deleted_count > 0 or failed_count > 0:
            logger.tree("Case Archive Cleanup", [
                ("Archived", str(deleted_count)),
                ("Transcripts Saved", str(transcript_count)),
                ("Failed", str(failed_count)),
                ("Total Checked", str(len(old_cases))),
            ], emoji="🗑️")

    async def _save_transcript(self, case: dict) -> bool:
        """
        Build and save transcript for a case before deletion.

        Args:
            case: Case record from database.

        Returns:
            True if transcript was saved, False otherwise.
        """
        case_id = case.get("case_id")
        thread_id = case.get("thread_id")

        if not case_id or not thread_id:
            return False

        # Skip if transcript already exists
        existing = self.db.get_case_transcript(case_id)
        if existing:
            return True

        try:
            # Get the thread
            thread = self.bot.get_channel(thread_id)
            if not thread:
                try:
                    thread = await self.bot.fetch_channel(thread_id)
                except discord.NotFound:
                    # Thread already deleted, can't build transcript
                    return False
                except discord.HTTPException:
                    return False

            if not isinstance(thread, discord.Thread):
                return False

            # Get target user and moderator info from case
            target_user_id = case.get("user_id")
            moderator_id = case.get("moderator_id")
            target_user_name = None
            moderator_name = None

            # Try to fetch user names from Discord
            if target_user_id:
                try:
                    target_user = await self.bot.fetch_user(target_user_id)
                    target_user_name = target_user.display_name
                except discord.NotFound:
                    logger.debug("Case Archive Target Not Found", [("User", str(target_user_id))])
                except Exception as e:
                    logger.debug("Case Archive Target Fetch Failed", [("User", str(target_user_id)), ("Error", str(e)[:30])])

            if moderator_id:
                try:
                    moderator_user = await self.bot.fetch_user(moderator_id)
                    moderator_name = moderator_user.display_name
                except discord.NotFound:
                    logger.debug("Case Archive Mod Not Found", [("Mod", str(moderator_id))])
                except Exception as e:
                    logger.debug("Case Archive Mod Fetch Failed", [("Mod", str(moderator_id)), ("Error", str(e)[:30])])

            # Build transcript
            transcript_builder = TranscriptBuilder(self.bot, self.assets_thread_id)
            transcript = await transcript_builder.build_from_thread(
                thread=thread,
                case_id=case_id,
                target_user_id=target_user_id,
                target_user_name=target_user_name,
                moderator_id=moderator_id,
                moderator_name=moderator_name,
            )

            if not transcript:
                return False

            # Save to database
            success = self.db.save_case_transcript(case_id, transcript.to_json())

            if success:
                logger.tree("Transcript Saved", [
                    ("Case ID", case_id),
                    ("Messages", str(transcript.message_count)),
                    ("Target", f"{target_user_name} ({target_user_id})"),
                    ("Moderator", f"{moderator_name} ({moderator_id})"),
                ], emoji="📝")

            return success

        except Exception as e:
            logger.warning("Transcript Save Failed", [
                ("Case ID", case_id),
                ("Error", str(e)[:50]),
            ])
            return False

    async def _delete_case_thread(self, case: dict) -> bool:
        """
        Delete a case thread from the forum.

        Args:
            case: Case record from database.

        Returns:
            True if successfully deleted, False otherwise.
        """
        thread_id = case.get("thread_id")
        if not thread_id:
            return False

        try:
            thread = self.bot.get_channel(thread_id)
            if not thread:
                # Try to fetch it
                try:
                    thread = await self.bot.fetch_channel(thread_id)
                except discord.NotFound:
                    # Thread already deleted
                    return True
                except discord.HTTPException:
                    return False

            if thread:
                action_type = case.get("action_type", "unknown")
                retention = RETENTION_DAYS_BAN if action_type == "ban" else RETENTION_DAYS_DEFAULT
                await thread.delete(reason=f"Case archive: {retention} days after creation ({action_type})")
                return True

        except discord.NotFound:
            # Thread already deleted
            return True
        except discord.Forbidden:
            logger.warning("No Permission To Delete Thread", [
                ("Thread ID", str(thread_id)),
                ("Case ID", case.get("case_id", "Unknown")),
            ])
            return False
        except discord.HTTPException as e:
            log_http_error(e, "Delete Case Thread", [
                ("Thread ID", str(thread_id)),
            ])
            return False

        return False


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["CaseArchiveScheduler"]
