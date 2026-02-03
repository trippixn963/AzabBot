"""
AzabBot - Mute Scheduler Service
================================

Background service for automatic unmuting of expired mutes.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import discord
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer
from src.views import CASE_EMOJI
from src.utils.async_utils import create_safe_task
from src.utils.rate_limiter import rate_limit
from src.core.constants import (
    CASE_LOG_TIMEOUT,
    MUTE_CHECK_INTERVAL,
    BACKOFF_MIN,
    BACKOFF_MAX,
    BACKOFF_MULTIPLIER,
    STARTUP_SYNC_BACKOFF_MIN,
    STARTUP_SYNC_BACKOFF_MAX,
    LOG_TRUNCATE_MEDIUM,
    SECONDS_PER_HOUR,
)

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Mute Scheduler Service
# =============================================================================

class MuteScheduler:
    """
    Background service for automatic mute expiration.

    DESIGN:
        Runs a loop every MUTE_CHECK_INTERVAL seconds checking for expired mutes.
        Uses database as source of truth, syncs with Discord state.
        Gracefully handles errors without crashing the loop.
        Implements exponential backoff on repeated errors.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
        db: Database manager.
        task: Background task reference.
        running: Whether the scheduler is active.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the mute scheduler.

        Args:
            bot: Main bot instance.
        """
        self.bot = bot
        self.config = get_config()
        self.db = get_db()
        self.task: Optional[asyncio.Task] = None
        self.running: bool = False
        self._consecutive_errors: int = 0
        self._current_backoff: int = BACKOFF_MIN

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    async def start(self) -> None:
        """
        Start the mute scheduler background task.

        DESIGN:
            Cancels any existing task before starting new one.
            Syncs mute state on startup to handle offline changes.
        """
        if self.task and not self.task.done():
            self.task.cancel()

        self.running = True
        self.task = create_safe_task(self._scheduler_loop(), "Mute Scheduler Loop")

        # Sync mute state on startup
        await self._sync_mute_state()

        # Start mute role overwrites scan (delayed)
        create_safe_task(self._run_startup_overwrites_scan(), "Mute Overwrites Scan")

        # Start midnight scan loop
        create_safe_task(self._midnight_scan_loop(), "Mute Midnight Scan")

        logger.tree("Mute Scheduler Started", [
            ("Check Interval", "30 seconds"),
            ("Startup Scan", "30s after ready"),
            ("Midnight Scan", "12:00 AM EST"),
            ("Status", "Running"),
        ], emoji="⏰")

    async def stop(self) -> None:
        """
        Stop the mute scheduler background task.
        """
        self.running = False

        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.info("Mute Scheduler Stopped")

    # =========================================================================
    # Scheduler Loop
    # =========================================================================

    async def _scheduler_loop(self) -> None:
        """
        Main scheduler loop.

        DESIGN:
            Runs every 30 seconds checking for expired mutes.
            Continues running even if individual unmutes fail.
            Implements exponential backoff on repeated errors.
        """
        await self.bot.wait_until_ready()

        while self.running:
            try:
                await self._process_expired_mutes()
                # Reset backoff on success
                self._consecutive_errors = 0
                self._current_backoff = BACKOFF_MIN
                await asyncio.sleep(self.config.mute_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_errors += 1
                logger.error("Mute Scheduler Error", [
                    ("Error", str(e)[:100]),
                    ("Consecutive Errors", str(self._consecutive_errors)),
                    ("Backoff", f"{self._current_backoff}s"),
                ])
                # Send error alert to webhook (with null check)
                if self.bot.webhook_alert_service and self.bot.webhook_alert_service.enabled:
                    try:
                        await self.bot.webhook_alert_service.send_error_alert(
                            "Mute Scheduler Error",
                            f"Error #{self._consecutive_errors}: {str(e)[:500]}"
                        )
                    except Exception:
                        pass  # Don't fail scheduler loop due to webhook issues

                # Apply exponential backoff
                await asyncio.sleep(self._current_backoff)
                self._current_backoff = min(
                    self._current_backoff * BACKOFF_MULTIPLIER,
                    BACKOFF_MAX
                )

    # =========================================================================
    # Mute Processing
    # =========================================================================

    async def _process_expired_mutes(self) -> None:
        """
        Process all expired mutes and unmute users concurrently.

        DESIGN:
            Fetches expired mutes from database.
            Groups by guild to cache role lookup (avoids N+1).
            Processes up to 25 mutes concurrently using asyncio.gather.
        """
        expired_mutes = self.db.get_expired_mutes()

        if not expired_mutes:
            return

        total_count = len(expired_mutes)

        # Group mutes by guild_id to cache role lookups
        from collections import defaultdict
        mutes_by_guild: dict[int, list] = defaultdict(list)
        for mute in expired_mutes:
            mutes_by_guild[mute["guild_id"]].append(mute)

        # Track outcomes for detailed logging
        success_count = 0
        skipped_guild = 0
        skipped_role = 0
        failed_count = 0

        # Process each guild's mutes with cached role
        batch_size = 25
        for guild_id, guild_mutes in mutes_by_guild.items():
            guild = self.bot.get_guild(guild_id)

            # Handle guild not accessible (bot removed) - cleanup all mutes for this guild
            if not guild:
                logger.warning("Guild Not Accessible", [
                    ("Guild ID", str(guild_id)),
                    ("Affected Mutes", str(len(guild_mutes))),
                    ("Action", "Removing stale mute records"),
                ])
                for mute in guild_mutes:
                    self.db.remove_mute(
                        user_id=mute["user_id"],
                        guild_id=guild_id,
                        moderator_id=self.bot.user.id,
                        reason="Auto-unmute (guild not accessible)",
                    )
                skipped_guild += len(guild_mutes)
                continue

            muted_role = guild.get_role(self.config.muted_role_id)

            # Log warning once per guild if role not found
            if not muted_role:
                logger.warning("Muted Role Not Found", [
                    ("Guild", guild.name),
                    ("Role ID", str(self.config.muted_role_id)),
                    ("Affected Mutes", str(len(guild_mutes))),
                ])
                skipped_role += len(guild_mutes)

            for i in range(0, len(guild_mutes), batch_size):
                batch = guild_mutes[i:i + batch_size]
                tasks = [self._safe_auto_unmute(mute, guild, muted_role) for mute in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        failed_count += 1
                    else:
                        success_count += 1

        log_items = [
            ("Total Expired", str(total_count)),
            ("Guilds", str(len(mutes_by_guild))),
            ("Processed", str(success_count)),
        ]
        if skipped_guild > 0:
            log_items.append(("Skipped (Guild)", str(skipped_guild)))
        if skipped_role > 0:
            log_items.append(("Skipped (Role)", str(skipped_role)))
        if failed_count > 0:
            log_items.append(("Failed", str(failed_count)))

        logger.tree("EXPIRED MUTES PROCESSED", log_items, emoji="⏰")

    async def _safe_auto_unmute(
        self,
        mute: dict,
        guild: Optional[discord.Guild],
        muted_role: Optional[discord.Role],
    ) -> None:
        """Wrapper for _auto_unmute with error handling."""
        try:
            await self._auto_unmute(mute, guild, muted_role)
        except Exception as e:
            logger.error("Auto-Unmute Failed", [
                ("User ID", str(mute["user_id"])),
                ("Guild ID", str(mute["guild_id"])),
                ("Error", str(e)[:50]),
            ])

    async def _auto_unmute(
        self,
        mute: dict,
        guild: Optional[discord.Guild],
        muted_role: Optional[discord.Role],
    ) -> None:
        """
        Automatically unmute a user whose mute has expired.

        Args:
            mute: Mute record from database.
            guild: Cached guild object (or None if not accessible).
            muted_role: Cached muted role (or None if not found).
        """
        if not guild:
            # Guild not accessible, mark as unmuted anyway
            self.db.remove_mute(
                user_id=mute["user_id"],
                guild_id=mute["guild_id"],
                moderator_id=self.bot.user.id,
                reason="Auto-unmute (guild not accessible)",
            )
            return

        member = guild.get_member(mute["user_id"])
        if not member:
            # User left the server, mark as unmuted
            self.db.remove_mute(
                user_id=mute["user_id"],
                guild_id=mute["guild_id"],
                moderator_id=self.bot.user.id,
                reason="Auto-unmute (user left server)",
            )
            return

        if not muted_role:
            # Role doesn't exist, mark as unmuted (warning logged once per guild in caller)
            self.db.remove_mute(
                user_id=mute["user_id"],
                guild_id=mute["guild_id"],
                moderator_id=self.bot.user.id,
                reason="Auto-unmute (role not found)",
            )
            return

        # Remove the muted role
        if muted_role in member.roles:
            try:
                await member.remove_roles(muted_role, reason="Auto-unmute: Mute duration expired")
            except discord.Forbidden:
                logger.error("Auto-Unmute Permission Denied", [
                    ("User", str(member)),
                    ("Guild", guild.name),
                ])
                return
            except discord.HTTPException as e:
                logger.error("Auto-Unmute HTTP Error", [
                    ("User", str(member)),
                    ("Error", str(e)[:50]),
                ])
                return

        # Update database
        self.db.remove_mute(
            user_id=mute["user_id"],
            guild_id=mute["guild_id"],
            moderator_id=self.bot.user.id,
            reason="Auto-unmute: Mute duration expired",
        )

        logger.tree("AUTO-UNMUTE", [
            ("User", str(member)),
            ("User ID", str(member.id)),
            ("Guild", guild.name),
            ("Reason", "Mute duration expired"),
        ], emoji="⏰")

        # Log to case forum (includes guild_id for per-action case lookup)
        if self.bot.case_log_service:
            try:
                await asyncio.wait_for(
                    self.bot.case_log_service.log_mute_expired(
                        user_id=member.id,
                        display_name=member.display_name,
                        user_avatar_url=member.display_avatar.url,
                        guild_id=guild.id,
                    ),
                    timeout=CASE_LOG_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("Case Log Timeout", [
                    ("Action", "Mute Expired"),
                    ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                    ("ID", str(member.id)),
                ])
            except Exception as e:
                logger.error("Case Log Failed", [
                    ("Action", "Mute Expired"),
                    ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                    ("ID", str(member.id)),
                    ("Error", str(e)[:100]),
                ])

        # DM user (silent fail)
        try:
            dm_embed = discord.Embed(
                title="You have been unmuted",
                description=f"Your mute in **{guild.name}** has expired.",
                color=EmbedColors.SUCCESS,
                timestamp=datetime.now(NY_TZ),
            )
            set_footer(dm_embed)
            await member.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

        # Post to mod log
        await self._post_auto_unmute_log(member, guild)

    async def _post_auto_unmute_log(
        self,
        user: discord.Member,
        guild: discord.Guild,
    ) -> None:
        """
        Post auto-unmute to server logs via logging service.

        Args:
            user: User who was unmuted.
            guild: Guild where unmute occurred.
        """
        if not self.bot.logging_service:
            return

        try:
            await self.bot.logging_service.log_unmute(
                user=user,
                moderator=None,  # System/auto unmute
                reason="Mute duration expired",
            )
        except Exception as e:
            logger.debug(f"Auto-unmute log failed: {e}")

    # =========================================================================
    # State Synchronization
    # =========================================================================

    async def _sync_mute_state(self) -> None:
        """
        Sync database mute state with actual Discord role state.

        DESIGN:
            Called on startup to handle changes made while bot was offline.
            Groups mutes by guild to minimize lookups, then processes concurrently.
            Removes mute records for users who no longer have the role.
        """
        await self.bot.wait_until_ready()

        active_mutes = self.db.get_all_active_mutes()
        if not active_mutes:
            return

        # Group mutes by guild_id for efficient batch processing
        from collections import defaultdict
        mutes_by_guild: dict[int, list] = defaultdict(list)
        for mute in active_mutes:
            mutes_by_guild[mute["guild_id"]].append(mute)

        synced = 0
        # Track removal reasons for detailed logging
        removed_guild_inaccessible = 0
        removed_role_missing = 0
        removed_user_left = 0
        removed_role_removed = 0

        # Process each guild's mutes
        for guild_id, guild_mutes in mutes_by_guild.items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                # Guild not accessible - remove all mutes for this guild
                for mute in guild_mutes:
                    self.db.remove_mute(
                        user_id=mute["user_id"],
                        guild_id=guild_id,
                        moderator_id=self.bot.user.id,
                        reason="Sync: Guild not accessible",
                    )
                removed_guild_inaccessible += len(guild_mutes)
                continue

            # Get muted role once per guild
            muted_role = guild.get_role(self.config.muted_role_id)
            if not muted_role:
                # Role doesn't exist - remove all mutes for this guild
                logger.warning("Muted Role Not Found During Sync", [
                    ("Guild", guild.name),
                    ("Role ID", str(self.config.muted_role_id)),
                    ("Affected Mutes", str(len(guild_mutes))),
                    ("Action", "Removing all mute records"),
                ])
                for mute in guild_mutes:
                    self.db.remove_mute(
                        user_id=mute["user_id"],
                        guild_id=guild_id,
                        moderator_id=self.bot.user.id,
                        reason="Sync: Role not found",
                    )
                removed_role_missing += len(guild_mutes)
                continue

            # Process each mute in this guild
            for mute in guild_mutes:
                member = guild.get_member(mute["user_id"])
                if not member:
                    self.db.remove_mute(
                        user_id=mute["user_id"],
                        guild_id=guild_id,
                        moderator_id=self.bot.user.id,
                        reason="Sync: User left server",
                    )
                    removed_user_left += 1
                    continue

                if muted_role not in member.roles:
                    self.db.remove_mute(
                        user_id=mute["user_id"],
                        guild_id=guild_id,
                        moderator_id=self.bot.user.id,
                        reason="Sync: Role manually removed",
                    )
                    removed_role_removed += 1
                    continue

                synced += 1

        total_removed = removed_guild_inaccessible + removed_role_missing + removed_user_left + removed_role_removed

        if active_mutes:
            log_items = [
                ("Total Checked", str(len(active_mutes))),
                ("Guilds Processed", str(len(mutes_by_guild))),
                ("Still Active", str(synced)),
                ("Total Removed", str(total_removed)),
            ]
            # Add removal breakdown only if there were removals
            if total_removed > 0:
                if removed_user_left > 0:
                    log_items.append(("└ User Left", str(removed_user_left)))
                if removed_role_removed > 0:
                    log_items.append(("└ Role Removed", str(removed_role_removed)))
                if removed_guild_inaccessible > 0:
                    log_items.append(("└ Guild Gone", str(removed_guild_inaccessible)))
                if removed_role_missing > 0:
                    log_items.append(("└ Role Missing", str(removed_role_missing)))

            logger.tree("Mute State Synced", log_items, emoji="🔄")


    # =========================================================================
    # Channel Overwrites Scan
    # =========================================================================

    async def _run_startup_overwrites_scan(self) -> None:
        """Run muted role overwrites scan on startup (delayed)."""
        await self.bot.wait_until_ready()

        # Wait before scanning to not slow down startup
        await asyncio.sleep(BACKOFF_MIN)

        try:
            await self._scan_mute_role_overwrites()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Mute Overwrites Scan Error", [
                ("Error", str(e)[:LOG_TRUNCATE_MEDIUM]),
            ])

    async def _midnight_scan_loop(self) -> None:
        """Run muted role overwrites scan at midnight EST daily."""
        await self.bot.wait_until_ready()
        from datetime import timedelta

        backoff = STARTUP_SYNC_BACKOFF_MIN
        max_backoff = STARTUP_SYNC_BACKOFF_MAX

        while self.running:
            try:
                # Calculate time until midnight EST
                now = datetime.now(NY_TZ)
                target = now.replace(hour=0, minute=0, second=0, microsecond=0)

                # If past midnight, schedule for tomorrow
                if now >= target:
                    target = target + timedelta(days=1)

                seconds_until = (target - now).total_seconds()

                # Wait until midnight
                await asyncio.sleep(seconds_until)

                # Run the scan
                await self._scan_mute_role_overwrites()

                # Reset backoff on success
                backoff = STARTUP_SYNC_BACKOFF_MIN

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Mute Midnight Scan Error", [
                    ("Error", str(e)[:LOG_TRUNCATE_MEDIUM]),
                    ("Retry In", f"{backoff // SECONDS_PER_HOUR}h"),
                ])
                # Apply exponential backoff
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def _scan_mute_role_overwrites(self) -> None:
        """
        Scan all channels and ensure muted role has correct overwrites.

        For regular channels/categories:
            - send_messages = False
            - view_channel = False (prisoners can't see other channels)

        For prison channels:
            - send_messages = True
            - view_channel = True
        """
        logger.tree("Mute Role Overwrites Scan Started", [], emoji="🔍")

        total_fixed = 0

        for guild in self.bot.guilds:
            try:
                fixed = await self._scan_guild_mute_overwrites(guild)
                total_fixed += fixed
            except Exception as e:
                logger.debug(f"Mute overwrites scan error for {guild.name}: {e}")

        logger.tree("Mute Role Overwrites Scan Complete", [
            ("Guilds Scanned", str(len(self.bot.guilds))),
            ("Overwrites Fixed", str(total_fixed)),
        ], emoji="✅")

    async def _scan_guild_mute_overwrites(self, guild: discord.Guild) -> int:
        """Scan a single guild for missing mute role overwrites. Returns count of fixes."""
        fixed = 0

        muted_role = guild.get_role(self.config.muted_role_id)
        if not muted_role:
            return 0

        # Prison channels where muted users CAN talk and see
        prison_channel_ids = self.config.prison_channel_ids

        # Overwrites for regular channels (deny everything)
        deny_overwrite = discord.PermissionOverwrite(
            send_messages=False,
            view_channel=False,
            add_reactions=False,
            speak=False,
        )

        # Overwrites for prison channels (allow)
        allow_overwrite = discord.PermissionOverwrite(
            send_messages=True,
            view_channel=True,
        )

        for channel in guild.channels:
            try:
                is_prison = channel.id in prison_channel_ids

                # Get parent category - if parent is prison, children should be too
                if hasattr(channel, 'category') and channel.category:
                    if channel.category.id in prison_channel_ids:
                        is_prison = True

                current = channel.overwrites_for(muted_role)
                needs_fix = False

                if is_prison:
                    # Prison channel - should allow
                    if current.send_messages is not True or current.view_channel is not True:
                        needs_fix = True
                        await channel.set_permissions(
                            muted_role,
                            overwrite=allow_overwrite,
                            reason="Mute system: prison channel fix"
                        )
                else:
                    # Regular channel - should deny
                    if (current.send_messages is not False or
                        current.view_channel is not False):
                        needs_fix = True
                        await channel.set_permissions(
                            muted_role,
                            overwrite=deny_overwrite,
                            reason="Mute system: overwrites fix"
                        )

                if needs_fix:
                    fixed += 1
                    # Use rate limiter for permission changes
                    await rate_limit("role_modify")

            except (discord.Forbidden, discord.HTTPException):
                continue

        return fixed


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["MuteScheduler"]
