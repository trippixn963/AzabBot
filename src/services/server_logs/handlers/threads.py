"""
Server Logs - Threads Handler
=============================

Handles thread activity logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors

if TYPE_CHECKING:
    from ..service import LoggingService


class ThreadsLogsMixin:
    """Mixin for thread activity logging."""

    async def log_thread_create(
        self: "LoggingService",
        thread: discord.Thread,
        creator: Optional[discord.Member] = None,
    ) -> None:
        """Log a thread being created."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🧵 Thread Created", EmbedColors.SUCCESS, category="Thread Create")
        embed.add_field(name="Thread", value=f"#{thread.name}" if thread.name else "#unknown-thread", inline=True)
        if thread.parent:
            embed.add_field(name="Parent", value=self._format_channel(thread.parent), inline=True)
        if creator:
            embed.add_field(name="By", value=self._format_user_field(creator), inline=True)

        await self._send_log(LogCategory.THREADS, embed)

    async def log_thread_delete(
        self: "LoggingService",
        thread_name: str,
        parent_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a thread being deleted."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🧵 Thread Deleted", EmbedColors.LOG_NEGATIVE, category="Thread Delete")
        embed.add_field(name="Thread", value=f"`{thread_name}`", inline=True)
        embed.add_field(name="Parent", value=f"`{parent_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.THREADS, embed)

    async def log_thread_archive(
        self: "LoggingService",
        thread: discord.Thread,
        archived: bool,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a thread being archived/unarchived."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        if archived:
            embed = self._create_embed("🧵 Thread Archived", EmbedColors.WARNING, category="Thread Archive")
        else:
            embed = self._create_embed("🧵 Thread Unarchived", EmbedColors.SUCCESS, category="Thread Unarchive")

        embed.add_field(name="Thread", value=f"#{thread.name}" if thread.name else "#unknown-thread", inline=True)
        if thread.parent:
            embed.add_field(name="Parent", value=self._format_channel(thread.parent), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.THREADS, embed)

    async def log_thread_lock(
        self: "LoggingService",
        thread: discord.Thread,
        locked: bool,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a thread being locked/unlocked."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        if locked:
            embed = self._create_embed("🔒 Thread Locked", EmbedColors.WARNING, category="Thread Lock")
        else:
            embed = self._create_embed("🔓 Thread Unlocked", EmbedColors.SUCCESS, category="Thread Unlock")

        embed.add_field(name="Thread", value=f"<#{thread.id}>", inline=True)
        if thread.parent:
            embed.add_field(name="Parent", value=self._format_channel(thread.parent), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.THREADS, embed)

    async def log_thread_member_add(
        self: "LoggingService",
        thread: discord.Thread,
        member: discord.Member,
        added_by: Optional[discord.Member] = None,
    ) -> None:
        """Log a member being added to a thread."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        user_id = member.id if member else None
        embed = self._create_embed("🧵 Member Added to Thread", EmbedColors.SUCCESS, category="Thread Member Add", user_id=user_id)
        embed.add_field(name="Thread", value=f"<#{thread.id}>", inline=True)
        embed.add_field(name="Member", value=self._format_user_field(member), inline=True)
        if added_by:
            embed.add_field(name="Added By", value=self._format_user_field(added_by), inline=True)

        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.THREADS, embed, user_id=user_id)

    async def log_thread_member_remove(
        self: "LoggingService",
        thread: discord.Thread,
        member: discord.Member,
        removed_by: Optional[discord.Member] = None,
    ) -> None:
        """Log a member being removed from a thread."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        user_id = member.id if member else None
        embed = self._create_embed("🧵 Member Removed from Thread", EmbedColors.LOG_NEGATIVE, category="Thread Member Remove", user_id=user_id)
        embed.add_field(name="Thread", value=f"<#{thread.id}>", inline=True)
        embed.add_field(name="Member", value=self._format_user_field(member), inline=True)
        if removed_by:
            embed.add_field(name="Removed By", value=self._format_user_field(removed_by), inline=True)

        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.THREADS, embed, user_id=user_id)


__all__ = ["ThreadsLogsMixin"]
