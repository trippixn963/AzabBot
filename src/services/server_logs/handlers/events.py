"""
Server Logs - Events Handler
============================

Handles scheduled event logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors

if TYPE_CHECKING:
    from ..service import LoggingService


class EventsLogsMixin:
    """Mixin for scheduled event logging."""

    async def log_event_create(
        self: "LoggingService",
        event: discord.ScheduledEvent,
        creator: Optional[discord.Member] = None,
    ) -> None:
        """Log a scheduled event creation."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("📅 Event Created", EmbedColors.SUCCESS, category="Event Create")
        embed.add_field(name="Event", value=f"`{event.name}`", inline=True)

        if event.start_time:
            start = int(event.start_time.timestamp())
            embed.add_field(name="Starts", value=f"<t:{start}:F>", inline=True)

        if event.location:
            embed.add_field(name="Location", value=f"`{event.location}`", inline=True)
        elif event.channel:
            embed.add_field(name="Channel", value=self._format_channel(event.channel), inline=True)

        if creator:
            embed.add_field(name="By", value=self._format_user_field(creator), inline=True)

        if event.description:
            desc = event.description[:200] if len(event.description) > 200 else event.description
            embed.add_field(name="Description", value=f"```{desc}```", inline=False)

        if event.cover_image:
            embed.set_image(url=event.cover_image.url)

        await self._send_log(LogCategory.EVENTS, embed)

    async def log_event_update(
        self: "LoggingService",
        event: discord.ScheduledEvent,
        changes: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a scheduled event update."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("📅 Event Updated", EmbedColors.WARNING, category="Event Update")
        embed.add_field(name="Event", value=f"`{event.name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Changes", value=f"```{changes}```", inline=False)

        await self._send_log(LogCategory.EVENTS, embed)

    async def log_event_delete(
        self: "LoggingService",
        event_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a scheduled event deletion."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("📅 Event Deleted", EmbedColors.LOG_NEGATIVE, category="Event Delete")
        embed.add_field(name="Event", value=f"`{event_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.EVENTS, embed)

    async def log_event_start(
        self: "LoggingService",
        event: discord.ScheduledEvent,
    ) -> None:
        """Log a scheduled event starting."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("📅 Event Started", EmbedColors.SUCCESS, category="Event Start")
        embed.add_field(name="Event", value=f"`{event.name}`", inline=True)

        if event.channel:
            embed.add_field(name="Channel", value=self._format_channel(event.channel), inline=True)
        elif event.location:
            embed.add_field(name="Location", value=f"`{event.location}`", inline=True)

        await self._send_log(LogCategory.EVENTS, embed)

    async def log_event_end(
        self: "LoggingService",
        event: discord.ScheduledEvent,
        user_count: Optional[int] = None,
    ) -> None:
        """Log a scheduled event ending."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("📅 Event Ended", EmbedColors.INFO, category="Event End")
        embed.add_field(name="Event", value=f"`{event.name}`", inline=True)

        if user_count is not None:
            embed.add_field(name="Attendees", value=f"`{user_count}`", inline=True)

        await self._send_log(LogCategory.EVENTS, embed)


__all__ = ["EventsLogsMixin"]
