"""
AzabBot - Base Presence Handler
===============================

Base presence handler with rotating status and hourly promo.
Subclass and implement get_status_messages() for bot-specific stats.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from zoneinfo import ZoneInfo

import discord

from src.utils.async_utils import create_safe_task

if TYPE_CHECKING:
    from discord import Client


# =============================================================================
# Constants
# =============================================================================

DEFAULT_PROMO_DURATION_MINUTES = 10
DEFAULT_UPDATE_INTERVAL = 60  # seconds


# =============================================================================
# Base Presence Handler
# =============================================================================

class BasePresenceHandler(ABC):
    """
    Base class for Discord presence management.

    Features:
    - Rotating status messages (bot-specific stats)
    - Hourly promotional presence window
    - Graceful start/stop lifecycle

    Subclasses must implement:
    - get_status_messages() -> List[str]
    - get_promo_text() -> str
    - get_timezone() -> timezone object
    """

    def __init__(
        self,
        bot: "Client",
        *,
        update_interval: int = DEFAULT_UPDATE_INTERVAL,
        promo_duration_minutes: int = DEFAULT_PROMO_DURATION_MINUTES,
    ) -> None:
        """
        Initialize the presence handler.

        Args:
            bot: The Discord bot instance.
            update_interval: Seconds between status rotations.
            promo_duration_minutes: Minutes to show promo each hour.
        """
        self.bot = bot
        self.update_interval = update_interval
        self.promo_duration_minutes = promo_duration_minutes

        # Background tasks
        self._rotation_task: Optional[asyncio.Task] = None
        self._promo_task: Optional[asyncio.Task] = None

        # State tracking
        self._current_index: int = 0
        self._is_promo_active: bool = False
        self._running: bool = False

    # =========================================================================
    # Abstract Methods (must be implemented by subclasses)
    # =========================================================================

    @abstractmethod
    def get_status_messages(self) -> List[str]:
        """
        Get list of status messages to rotate through.

        Returns:
            List of formatted status strings (e.g., ["🔒 500 prisoners", "📋 1K cases"]).
            Return empty list to use promo text as fallback.
        """
        pass

    @abstractmethod
    def get_promo_text(self) -> str:
        """
        Get the promotional text to display at top of each hour.

        Returns:
            Promo string (e.g., "🌐 trippixn.com/azab").
        """
        pass

    @abstractmethod
    def get_timezone(self) -> ZoneInfo:
        """
        Get the timezone for promo scheduling.

        Returns:
            A timezone object (e.g., ZoneInfo).
        """
        pass

    # =========================================================================
    # Optional Hooks (can be overridden)
    # =========================================================================

    def on_rotation_start(self) -> None:
        """Called when rotation loop starts. Override for logging."""
        pass

    def on_promo_start(self) -> None:
        """Called when promo loop starts. Override for logging."""
        pass

    def on_promo_activated(self) -> None:
        """Called when promo presence is shown. Override for logging."""
        pass

    def on_promo_ended(self) -> None:
        """Called when promo ends and rotation resumes. Override for logging."""
        pass

    def on_handler_ready(self) -> None:
        """Called when handler is fully started. Override for logging."""
        pass

    def on_handler_stopped(self) -> None:
        """Called when handler is stopped. Override for logging."""
        pass

    def on_error(self, context: str, error: Exception) -> None:
        """Called on errors. Override for custom error logging."""
        pass

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the presence handler tasks."""
        if self._running:
            return

        self._running = True

        # Start rotation task with safe task wrapper
        self._rotation_task = create_safe_task(self._rotation_loop(), name="presence_rotation")

        # Start promo task with safe task wrapper
        self._promo_task = create_safe_task(self._promo_loop(), name="presence_promo")

        self.on_handler_ready()

    async def stop(self) -> None:
        """Stop the presence handler tasks."""
        self._running = False

        if self._rotation_task:
            self._rotation_task.cancel()
            try:
                await self._rotation_task
            except asyncio.CancelledError:
                pass
            self._rotation_task = None

        if self._promo_task:
            self._promo_task.cancel()
            try:
                await self._promo_task
            except asyncio.CancelledError:
                pass
            self._promo_task = None

        self.on_handler_stopped()

    # =========================================================================
    # Rotation Loop
    # =========================================================================

    async def _rotation_loop(self) -> None:
        """Background task that rotates presence every interval."""
        await self.bot.wait_until_ready()

        self.on_rotation_start()

        while self._running:
            try:
                await asyncio.sleep(self.update_interval)

                # Skip if promo is active
                if self._is_promo_active:
                    continue

                await self._update_rotating_presence()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.on_error("Rotation Loop", e)
                await asyncio.sleep(self.update_interval)

    async def _update_rotating_presence(self) -> None:
        """Update presence with rotating status messages."""
        # Double-check promo isn't active
        if self._is_promo_active:
            return

        try:
            messages = self.get_status_messages()

            if not messages:
                # Fallback to promo text
                status_text = self.get_promo_text()
            else:
                self._current_index = self._current_index % len(messages)
                status_text = messages[self._current_index]
                self._current_index += 1

            await self.bot.change_presence(
                activity=discord.CustomActivity(name=status_text)
            )

        except Exception as e:
            self.on_error("Presence Update", e)

    # =========================================================================
    # Promo Loop
    # =========================================================================

    async def _promo_loop(self) -> None:
        """Background task that shows promo at the top of each hour."""
        await self.bot.wait_until_ready()

        self.on_promo_start()

        while self._running:
            try:
                # Calculate time until next hour
                now = datetime.now(self.get_timezone())
                minutes_until_hour = 60 - now.minute
                seconds_until_hour = (minutes_until_hour * 60) - now.second

                if seconds_until_hour > 0:
                    await asyncio.sleep(seconds_until_hour)

                # Show promo
                await self._show_promo_presence()

                # Wait for promo duration
                await asyncio.sleep(self.promo_duration_minutes * 60)

                # End promo
                await self._restore_normal_presence()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._is_promo_active = False
                self.on_error("Promo Loop", e)
                await asyncio.sleep(60)

    async def _show_promo_presence(self) -> None:
        """Show promotional presence."""
        try:
            self._is_promo_active = True

            await self.bot.change_presence(
                activity=discord.CustomActivity(name=self.get_promo_text())
            )

            self.on_promo_activated()

        except Exception as e:
            self.on_error("Show Promo", e)
            self._is_promo_active = False

    async def _restore_normal_presence(self) -> None:
        """Restore normal presence after promo ends."""
        try:
            self._is_promo_active = False
            await self._update_rotating_presence()
            self.on_promo_ended()

        except Exception as e:
            self.on_error("Restore Presence", e)
            self._is_promo_active = False

    # =========================================================================
    # Public API
    # =========================================================================

    @property
    def is_promo_active(self) -> bool:
        """Check if promo is currently showing."""
        return self._is_promo_active

    async def force_update(self) -> None:
        """Force an immediate presence update (respects promo state)."""
        if not self._is_promo_active:
            await self._update_rotating_presence()


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "BasePresenceHandler",
    "DEFAULT_PROMO_DURATION_MINUTES",
    "DEFAULT_UPDATE_INTERVAL",
]
