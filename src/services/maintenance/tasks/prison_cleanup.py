"""
AzabBot - Prison Channel Cleanup Task
=====================================

Delete old messages from prison channels.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict

import discord

from src.core.logger import logger
from src.core.config import get_config
from src.core.constants import LOG_TRUNCATE_SHORT, QUERY_LIMIT_XXL, MAINTENANCE_RATE_LIMIT_DELAY
from src.utils.discord_rate_limit import log_http_error
from ..base import MaintenanceTask

if TYPE_CHECKING:
    from src.bot import AzabBot


class PrisonCleanupTask(MaintenanceTask):
    """
    Delete messages older than 14 days from prison channels.

    Discord's bulk delete only works on messages younger than 14 days,
    so we clean up messages that are approaching this limit.
    """

    name = "Prison Cleanup"

    def __init__(self, bot: "AzabBot") -> None:
        super().__init__(bot)
        self.config = get_config()

    async def should_run(self) -> bool:
        """Check if prison channels are configured."""
        return bool(self.config.prison_channel_ids)

    async def run(self) -> Dict[str, Any]:
        """Delete old messages from prison channels."""
        total_deleted = 0
        errors = 0

        for channel_id in self.config.prison_channel_ids:
            prison_channel = self.bot.get_channel(channel_id)
            if not prison_channel or not isinstance(prison_channel, discord.TextChannel):
                continue

            try:
                deleted = await self._cleanup_channel(prison_channel)
                total_deleted += deleted
            except Exception as e:
                errors += 1
                logger.error("Prison Cleanup Channel Error", [
                    ("Channel", prison_channel.name),
                    ("Error", str(e)[:LOG_TRUNCATE_SHORT]),
                ])

        if total_deleted > 0:
            logger.tree("Prison Cleanup Complete", [
                ("Channels", str(len(self.config.prison_channel_ids))),
                ("Deleted", str(total_deleted)),
            ], emoji="🧹")

        return {
            "success": errors == 0,
            "deleted": total_deleted,
            "errors": errors,
        }

    async def _cleanup_channel(self, channel: discord.TextChannel) -> int:
        """Clean up a single prison channel. Returns count of deleted messages."""
        deleted_count = 0
        two_weeks_ago = datetime.now(timezone.utc) - timedelta(days=14)

        while True:
            messages_to_delete = []
            async for message in channel.history(limit=QUERY_LIMIT_XXL):
                if message.created_at > two_weeks_ago:
                    messages_to_delete.append(message)

            if not messages_to_delete:
                break

            try:
                for i in range(0, len(messages_to_delete), 100):
                    batch = messages_to_delete[i:i + 100]
                    await channel.delete_messages(batch)
                    deleted_count += len(batch)
                    await asyncio.sleep(MAINTENANCE_RATE_LIMIT_DELAY)
            except discord.HTTPException:
                break

            await asyncio.sleep(MAINTENANCE_RATE_LIMIT_DELAY)

        return deleted_count

    def format_result(self, result: Dict[str, Any]) -> str:
        """Format result for summary."""
        deleted = result.get("deleted", 0)
        return f"{deleted} deleted" if deleted > 0 else "clean"


__all__ = ["PrisonCleanupTask"]
