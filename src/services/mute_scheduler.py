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
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Mute Scheduler Error", [
                    ("Error", str(e)[:100]),
                ])
                await asyncio.sleep(30)

    # =========================================================================
    # Mute Processing
    # =========================================================================

    async def _process_expired_mutes(self) -> None:
        """
        Process all expired mutes and unmute users.

        DESIGN:
            Fetches expired mutes from database.
            Attempts to remove role from each user.
            Logs to mod log channel on success.
        """
        expired_mutes = self.db.get_expired_mutes()

        for mute in expired_mutes:
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
            title="Moderation: Auto-Unmute",
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ),
        )

        embed.add_field(name="User", value=f"{user.mention} ({user})", inline=True)
        embed.add_field(name="Moderator", value=f"{self.bot.user.mention} (Auto)", inline=True)
        embed.add_field(name="Reason", value="Mute duration expired", inline=False)

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"User ID: {user.id}")

        try:
            await log_channel.send(embed=embed)
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
            Removes mute records for users who no longer have the role.
            Handles users who left the server.
        """
        await self.bot.wait_until_ready()

        active_mutes = self.db.get_all_active_mutes()
        synced = 0
        removed = 0

        for mute in active_mutes:
            guild = self.bot.get_guild(mute["guild_id"])
            if not guild:
                # Guild not accessible
                self.db.remove_mute(
                    user_id=mute["user_id"],
                    guild_id=mute["guild_id"],
                    moderator_id=self.bot.user.id,
                    reason="Sync: Guild not accessible",
                )
                removed += 1
                continue

            member = guild.get_member(mute["user_id"])
            if not member:
                # User left server
                self.db.remove_mute(
                    user_id=mute["user_id"],
                    guild_id=mute["guild_id"],
                    moderator_id=self.bot.user.id,
                    reason="Sync: User left server",
                )
                removed += 1
                continue

            muted_role = guild.get_role(self.config.muted_role_id)
            if not muted_role:
                # Role doesn't exist
                self.db.remove_mute(
                    user_id=mute["user_id"],
                    guild_id=mute["guild_id"],
                    moderator_id=self.bot.user.id,
                    reason="Sync: Role not found",
                )
                removed += 1
                continue

            # Check if user still has the role
            if muted_role not in member.roles:
                # Role was manually removed
                self.db.remove_mute(
                    user_id=mute["user_id"],
                    guild_id=mute["guild_id"],
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
            ], emoji="🔄")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["MuteScheduler"]
