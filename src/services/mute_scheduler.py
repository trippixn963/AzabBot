"""
Azab Discord Bot - Mute Scheduler Service
==========================================

Background service for automatic unmuting of expired mutes.

DESIGN:
    Runs as a background task checking for expired mutes every 30 seconds.
    On bot startup, syncs database with actual role state to handle
    cases where roles were manually removed while bot was offline.

    Key responsibilities:
    - Check for expired mutes and remove muted role
    - Log automatic unmutes to mod log channel
    - Handle edge cases (user left, role deleted, etc.)

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
from src.utils.views import CASE_EMOJI

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Mute Scheduler Service
# =============================================================================

class MuteScheduler:
    """
    Background service for automatic mute expiration.

    DESIGN:
        Runs a loop every 30 seconds checking for expired mutes.
        Uses database as source of truth, syncs with Discord state.
        Gracefully handles errors without crashing the loop.

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
        self.task = asyncio.create_task(self._scheduler_loop())

        # Sync mute state on startup
        await self._sync_mute_state()

        logger.tree("Mute Scheduler Started", [
            ("Check Interval", "30 seconds"),
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
        """
        await self.bot.wait_until_ready()

        while self.running:
            try:
                await self._process_expired_mutes()
                await asyncio.sleep(self.config.mute_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Mute Scheduler Error", [
                    ("Error", str(e)[:100]),
                ])
                await asyncio.sleep(self.config.mute_check_interval)

    # =========================================================================
    # Mute Processing
    # =========================================================================

    async def _process_expired_mutes(self) -> None:
        """
        Process all expired mutes and unmute users concurrently.

        DESIGN:
            Fetches expired mutes from database.
            Processes up to 25 mutes concurrently using asyncio.gather.
            Groups by guild to minimize role lookups.
        """
        expired_mutes = self.db.get_expired_mutes()

        if not expired_mutes:
            return

        total_count = len(expired_mutes)

        # Process in batches of 25 concurrently
        batch_size = 25
        for i in range(0, len(expired_mutes), batch_size):
            batch = expired_mutes[i:i + batch_size]
            tasks = [self._safe_auto_unmute(mute) for mute in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.tree("EXPIRED MUTES PROCESSED", [
            ("Total", str(total_count)),
            ("Batches", str((total_count + batch_size - 1) // batch_size)),
        ], emoji="⏰")

    async def _safe_auto_unmute(self, mute: dict) -> None:
        """Wrapper for _auto_unmute with error handling."""
        try:
            await self._auto_unmute(mute)
        except Exception as e:
            logger.error("Auto-Unmute Failed", [
                ("User ID", str(mute["user_id"])),
                ("Guild ID", str(mute["guild_id"])),
                ("Error", str(e)[:50]),
            ])

    async def _auto_unmute(self, mute: dict) -> None:
        """
        Automatically unmute a user whose mute has expired.

        Args:
            mute: Mute record from database.
        """
        guild = self.bot.get_guild(mute["guild_id"])
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

        muted_role = guild.get_role(self.config.muted_role_id)
        if not muted_role:
            # Role doesn't exist, mark as unmuted
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

        # Log to case forum
        if self.bot.case_log_service:
            await self.bot.case_log_service.log_mute_expired(
                user_id=member.id,
                display_name=member.display_name,
                user_avatar_url=member.display_avatar.url,
            )

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
        Post auto-unmute to mod log channel.

        Args:
            user: User who was unmuted.
            guild: Guild where unmute occurred.
        """
        log_channel = self.bot.get_channel(self.config.logs_channel_id)
        if not log_channel:
            return

        embed = discord.Embed(
            title="🔊 Auto-Unmute",
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ),
        )

        embed.add_field(name="User", value=f"{user.mention}\n`{user.name}`", inline=True)
        embed.add_field(name="Moderator", value=f"{self.bot.user.mention}\n`Auto`", inline=True)
        embed.add_field(name="Reason", value="```Mute duration expired```", inline=False)

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"Unmute • ID: {user.id}")

        try:
            # Add Case button if user has an open case
            view = None
            case = self.db.get_case_log(user.id)
            if case:
                view = discord.ui.View(timeout=None)
                case_url = f"https://discord.com/channels/{guild.id}/{case['thread_id']}"
                view.add_item(discord.ui.Button(
                    label="Case",
                    url=case_url,
                    style=discord.ButtonStyle.link,
                    emoji=CASE_EMOJI,
                ))

            await log_channel.send(embed=embed, view=view)
        except (discord.Forbidden, discord.HTTPException):
            pass

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
        removed = 0

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
                removed += len(guild_mutes)
                continue

            # Get muted role once per guild
            muted_role = guild.get_role(self.config.muted_role_id)
            if not muted_role:
                # Role doesn't exist - remove all mutes for this guild
                for mute in guild_mutes:
                    self.db.remove_mute(
                        user_id=mute["user_id"],
                        guild_id=guild_id,
                        moderator_id=self.bot.user.id,
                        reason="Sync: Role not found",
                    )
                removed += len(guild_mutes)
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
                    removed += 1
                    continue

                if muted_role not in member.roles:
                    self.db.remove_mute(
                        user_id=mute["user_id"],
                        guild_id=guild_id,
                        moderator_id=self.bot.user.id,
                        reason="Sync: Role manually removed",
                    )
                    removed += 1
                    continue

                synced += 1

        if active_mutes:
            logger.tree("Mute State Synced", [
                ("Active Mutes", str(synced)),
                ("Removed Stale", str(removed)),
                ("Total Checked", str(len(active_mutes))),
                ("Guilds Processed", str(len(mutes_by_guild))),
            ], emoji="🔄")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["MuteScheduler"]
