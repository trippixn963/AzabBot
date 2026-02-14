"""
AzabBot - Queue Mixin
=====================

Priority queue system for mod tracker messages.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
import asyncio
import heapq

import discord

from src.core.logger import logger
from src.core.config import NY_TZ
from src.utils.rate_limiter import rate_limit
from src.utils.async_utils import create_safe_task
from src.utils.discord_rate_limit import log_http_error

from .constants import (
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_NORMAL,
    PRIORITY_LOW,
    QUEUE_PROCESS_INTERVAL,
    QUEUE_BATCH_SIZE,
    QUEUE_MAX_SIZE,
    CACHE_CLEANUP_INTERVAL)
from .helpers import QueueItem

if TYPE_CHECKING:
    from .service import ModTrackerService


class QueueMixin:
    """Mixin for priority queue system."""

    def start_queue_processor(self: "ModTrackerService") -> None:
        """Start the background queue processor task."""
        if self._queue_processor_task is None or self._queue_processor_task.done():
            self._queue_running = True
            self._queue_processor_task = create_safe_task(
                self._process_queue(), "Mod Tracker Queue Processor"
            )
            logger.debug("Mod Tracker: Queue processor started")

    async def stop_queue_processor(
        self: "ModTrackerService",
        drain_timeout: float = 10.0
    ) -> int:
        """
        Gracefully stop the queue processor, draining remaining items.

        Args:
            drain_timeout: Max seconds to wait for queue to drain.

        Returns:
            Number of items that were still in queue (0 = fully drained).
        """
        self._queue_running = False
        remaining = len(self._message_queue)

        if remaining > 0:
            logger.info("Mod Tracker Draining Queue", [("Items", str(remaining))])
            start = asyncio.get_event_loop().time()

            # Process remaining items with timeout
            while self._message_queue and (asyncio.get_event_loop().time() - start) < drain_timeout:
                async with self._queue_lock:
                    if self._message_queue:
                        item = heapq.heappop(self._message_queue)
                        await self._send_queued_item(item)
                        await rate_limit("mod_tracker")  # Brief delay between sends

            remaining = len(self._message_queue)
            if remaining > 0:
                logger.warning("Mod Tracker Queue Lost", [("Items", str(remaining)), ("Reason", "Timeout")])
            else:
                logger.info("Mod Tracker: Queue fully drained")

        if self._queue_processor_task and not self._queue_processor_task.done():
            self._queue_processor_task.cancel()
            try:
                await self._queue_processor_task
            except asyncio.CancelledError:
                pass

        logger.debug("Mod Tracker: Queue processor stopped")
        return remaining

    async def _enqueue(
        self: "ModTrackerService",
        thread_id: int,
        embed: discord.Embed,
        priority: int = PRIORITY_NORMAL,
        content: Optional[str] = None,
        view: Optional[discord.ui.View] = None,
        is_alert: bool = False) -> None:
        """
        Add a message to the priority queue.

        Args:
            thread_id: Thread ID to send to.
            embed: Embed to send.
            priority: Priority level (lower = higher priority).
            content: Optional text content (for pings).
            view: Optional view with buttons.
            is_alert: Whether this is a security alert.
        """
        async with self._queue_lock:
            # Check queue size and drop low priority if full
            if len(self._message_queue) >= QUEUE_MAX_SIZE:
                # Remove lowest priority items (highest number)
                if priority < PRIORITY_LOW:
                    # Drop a low priority item to make room
                    self._message_queue = [
                        item for item in self._message_queue
                        if item.priority < PRIORITY_LOW
                    ][:QUEUE_MAX_SIZE - 1]
                    heapq.heapify(self._message_queue)
                else:
                    # This is low priority and queue is full, drop it
                    logger.warning("Mod Tracker: Queue full, dropping low priority item")
                    return

            item = QueueItem(
                priority=priority.timestamp(),
                thread_id=thread_id,
                content=content,
                embed=embed,
                view=view,
                is_alert=is_alert)
            heapq.heappush(self._message_queue, item)

        # Ensure processor is running
        self.start_queue_processor()

    async def _process_queue(self: "ModTrackerService") -> None:
        """Background task to process the message queue with priority."""
        last_cleanup = datetime.now(NY_TZ)

        while self._queue_running:
            try:
                items_to_send: List[QueueItem] = []

                async with self._queue_lock:
                    # Get up to QUEUE_BATCH_SIZE items, prioritizing alerts
                    for _ in range(min(QUEUE_BATCH_SIZE, len(self._message_queue))):
                        if self._message_queue:
                            items_to_send.append(heapq.heappop(self._message_queue))

                if items_to_send:
                    for item in items_to_send:
                        await self._send_queued_item(item)
                        # Small delay between sends to avoid rate limits
                        await rate_limit("mod_tracker")

                # Periodic cache cleanup
                now = datetime.now(NY_TZ)
                if (now - last_cleanup).total_seconds() >= CACHE_CLEANUP_INTERVAL:
                    self._cleanup_caches()
                    last_cleanup = now

                # Wait before next batch
                await asyncio.sleep(QUEUE_PROCESS_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Mod Tracker: Queue processor error", [
                    ("Error", str(e)[:100]),
                ])
                await asyncio.sleep(QUEUE_PROCESS_INTERVAL)

    async def _send_queued_item(self: "ModTrackerService", item: "QueueItem") -> bool:
        """Send a single queued item to Discord."""
        try:
            thread = await self._get_mod_thread(item.thread_id)
            if not thread:
                return False

            # Unarchive if needed
            if thread.archived:
                try:
                    await thread.edit(archived=False)
                    await rate_limit("thread_edit")
                except discord.HTTPException:
                    pass

            await thread.send(
                content=item.content,
                embed=item.embed,
                view=item.view)

            if item.is_alert:
                logger.tree("Mod Tracker: Priority Alert Sent", [
                    ("Thread", str(item.thread_id)),
                    ("Priority", str(item.priority)),
                ], emoji="🚨")

            return True

        except Exception as e:
            logger.error("Mod Tracker: Failed to send queued item", [
                ("Thread", str(item.thread_id)),
                ("Error", str(e)[:50]),
            ])
            return False

    def get_queue_status(self: "ModTrackerService") -> Dict[str, Any]:
        """Get current queue status for monitoring."""
        priority_counts = {
            "critical": 0,
            "high": 0,
            "normal": 0,
            "low": 0,
        }
        for item in self._message_queue:
            if item.priority == PRIORITY_CRITICAL:
                priority_counts["critical"] += 1
            elif item.priority == PRIORITY_HIGH:
                priority_counts["high"] += 1
            elif item.priority == PRIORITY_NORMAL:
                priority_counts["normal"] += 1
            else:
                priority_counts["low"] += 1

        return {
            "total": len(self._message_queue),
            "running": self._queue_running,
            "by_priority": priority_counts,
        }


__all__ = ["QueueMixin"]
