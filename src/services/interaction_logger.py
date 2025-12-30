"""
Azab Discord Bot - Interaction Logger Service
==============================================

Logs all button interactions to a Discord webhook in the mods server.

Features:
- Embed batching (up to 10 embeds per request)
- Automatic flush on timeout or batch full
- Centralized colors from EmbedColors
- Timestamps on all embeds

Tracked interactions:
- Ticket actions (create, claim, close, reopen, transcript)
- Appeal actions (approve, deny, contact user)
- Modmail actions (close)
- All button/select menu clicks

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import aiohttp
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Batch settings
MAX_EMBEDS_PER_REQUEST = 10  # Discord limit
BATCH_FLUSH_INTERVAL = 2.0   # Seconds to wait before flushing partial batch

# Rate limit retry settings
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds


# =============================================================================
# Interaction Logger Service
# =============================================================================

class InteractionLogger:
    """Logs bot button interactions via webhook with batching and rate limit handling."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self._embed_queue: List[dict] = []
        self._flush_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    @property
    def webhook_url(self) -> Optional[str]:
        """Get webhook URL from config."""
        return self.config.interaction_webhook_url

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get shared HTTP session from bot."""
        return await self.bot.get_http_session()

    async def _send_with_retry(self, payload: dict) -> bool:
        """Send webhook with rate limit retry and exponential backoff."""
        session = await self._get_session()
        backoff = INITIAL_BACKOFF

        for attempt in range(MAX_RETRIES):
            try:
                async with session.post(self.webhook_url, json=payload) as resp:
                    if resp.status in (200, 204):
                        return True
                    elif resp.status == 429:
                        # Rate limited - get retry-after from headers or use backoff
                        retry_after = float(resp.headers.get("Retry-After", backoff))
                        logger.warning("Interaction Webhook Rate Limited", [
                            ("Retry After", f"{retry_after}s"),
                            ("Attempt", f"{attempt + 1}/{MAX_RETRIES}"),
                        ])
                        await asyncio.sleep(retry_after)
                        backoff *= 2  # Exponential backoff
                    else:
                        logger.warning("Interaction Webhook Error", [
                            ("Status", str(resp.status)),
                            ("Attempt", f"{attempt + 1}/{MAX_RETRIES}"),
                        ])
                        return False
            except Exception as e:
                logger.warning("Interaction Webhook Failed", [
                    ("Error", str(e)[:100]),
                    ("Attempt", f"{attempt + 1}/{MAX_RETRIES}"),
                ])
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(backoff)
                    backoff *= 2

        return False

    async def verify_webhook(self) -> bool:
        """Send a startup verification message to confirm webhook is working."""
        if not self.webhook_url:
            logger.warning("Interaction Logger", [
                ("Status", "No webhook URL configured"),
            ])
            return False

        try:
            embed = discord.Embed(
                title="🔔 Interaction Logger Online",
                description="Webhook verification successful. All button interactions will be logged here.",
                color=EmbedColors.SUCCESS,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(name="Time", value=f"`{self._get_time_str()}`", inline=True)
            embed.add_field(name="Bot", value=f"`{self.bot.user.name if self.bot.user else 'AzabBot'}`", inline=True)
            embed.set_footer(text="AzabBot Interaction Logger")

            payload = {"embeds": [embed.to_dict()]}

            success = await self._send_with_retry(payload)
            if success:
                logger.info("Interaction Logger", [
                    ("Status", "Webhook verified"),
                ])
                return True
            else:
                logger.warning("Interaction Logger", [
                    ("Status", "Webhook verification failed"),
                ])
                return False
        except Exception as e:
            logger.error("Interaction Logger", [
                ("Status", "Webhook verification error"),
                ("Error", str(e)[:100]),
            ])
            return False

    async def _queue_embed(self, embed: discord.Embed) -> None:
        """Add embed to queue and flush if full."""
        if not self.webhook_url:
            return

        async with self._lock:
            self._embed_queue.append(embed.to_dict())

            # Flush immediately if batch is full
            if len(self._embed_queue) >= MAX_EMBEDS_PER_REQUEST:
                await self._flush_queue()
            else:
                # Schedule delayed flush for partial batches
                self._schedule_flush()

    def _schedule_flush(self) -> None:
        """Schedule a delayed flush for partial batches."""
        if self._flush_task and not self._flush_task.done():
            return  # Already scheduled

        self._flush_task = asyncio.create_task(self._delayed_flush())

    async def _delayed_flush(self) -> None:
        """Wait and then flush the queue."""
        await asyncio.sleep(BATCH_FLUSH_INTERVAL)
        async with self._lock:
            if self._embed_queue:
                await self._flush_queue()

    async def _flush_queue(self) -> None:
        """Send all queued embeds to webhook with retry."""
        if not self._embed_queue or not self.webhook_url:
            return

        embeds_to_send = self._embed_queue[:MAX_EMBEDS_PER_REQUEST]
        self._embed_queue = self._embed_queue[MAX_EMBEDS_PER_REQUEST:]

        payload = {"embeds": embeds_to_send}
        await self._send_with_retry(payload)

    async def flush(self) -> None:
        """Force flush all queued embeds (call on shutdown)."""
        async with self._lock:
            while self._embed_queue:
                await self._flush_queue()

    async def close(self) -> None:
        """Flush queue (session is managed by bot)."""
        await self.flush()

    def _get_time_str(self) -> str:
        """Get formatted time string in EST."""
        now_est = datetime.now(NY_TZ)
        return now_est.strftime("%I:%M %p EST")

    def _create_embed(self, title: str, color: int) -> discord.Embed:
        """Create a standardized embed with timestamp and footer."""
        embed = discord.Embed(
            title=title,
            color=color,
            timestamp=datetime.now(NY_TZ),
        )
        embed.set_footer(text="AzabBot")
        return embed

    # =========================================================================
    # Ticket Events
    # =========================================================================

    async def log_ticket_created(
        self,
        user: discord.User,
        ticket_id: str,
        category: str,
        subject: str,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log when a ticket is created."""
        embed = self._create_embed("🎫 Ticket Created", EmbedColors.TICKET)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=f"`{category.title()}`", inline=True)
        embed.add_field(name="Subject", value=f"`{subject[:50]}{'...' if len(subject) > 50 else ''}`", inline=False)

        thread_link = f"https://discord.com/channels/{guild_id}/{thread_id}"
        embed.add_field(name="Thread", value=f"[Open Thread]({thread_link})", inline=True)

        await self._queue_embed(embed)

    async def log_ticket_claimed(
        self,
        staff: discord.Member,
        ticket_id: str,
        user: discord.User,
    ) -> None:
        """Log when a ticket is claimed."""
        embed = self._create_embed("✋ Ticket Claimed", EmbedColors.PRIORITY_HIGH)
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Staff", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Ticket Owner", value=f"{user.mention}", inline=True)

        await self._queue_embed(embed)

    async def log_ticket_unclaimed(
        self,
        staff: discord.Member,
        ticket_id: str,
    ) -> None:
        """Log when a ticket is unclaimed."""
        embed = self._create_embed("👐 Ticket Unclaimed", EmbedColors.BLURPLE)
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Staff", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)

        await self._queue_embed(embed)

    async def log_ticket_closed(
        self,
        staff: discord.Member,
        ticket_id: str,
        user: discord.User,
        reason: Optional[str] = None,
    ) -> None:
        """Log when a ticket is closed."""
        embed = self._create_embed("🔒 Ticket Closed", EmbedColors.LOG_NEGATIVE)
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Closed By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Ticket Owner", value=f"{user.mention}", inline=True)
        if reason:
            embed.add_field(name="Reason", value=f"`{reason[:100]}`", inline=False)

        await self._queue_embed(embed)

    async def log_ticket_reopened(
        self,
        staff: discord.Member,
        ticket_id: str,
        user: discord.User,
    ) -> None:
        """Log when a ticket is reopened."""
        embed = self._create_embed("🔓 Ticket Reopened", EmbedColors.SUCCESS)
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Reopened By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Ticket Owner", value=f"{user.mention}", inline=True)

        await self._queue_embed(embed)

    async def log_ticket_priority(
        self,
        staff: discord.Member,
        ticket_id: str,
        priority: str,
    ) -> None:
        """Log when ticket priority is changed."""
        priority_colors = {
            "low": EmbedColors.PRIORITY_LOW,
            "normal": EmbedColors.PRIORITY_NORMAL,
            "high": EmbedColors.PRIORITY_HIGH,
            "urgent": EmbedColors.PRIORITY_URGENT,
        }

        embed = self._create_embed("🏷️ Priority Changed", priority_colors.get(priority, EmbedColors.BLURPLE))
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Changed By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Priority", value=f"`{priority.upper()}`", inline=True)

        await self._queue_embed(embed)

    async def log_ticket_assigned(
        self,
        staff: discord.Member,
        ticket_id: str,
        assigned_to: discord.Member,
    ) -> None:
        """Log when a ticket is assigned."""
        embed = self._create_embed("👤 Ticket Assigned", EmbedColors.BLURPLE)
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Assigned By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Assigned To", value=f"{assigned_to.mention}", inline=True)

        await self._queue_embed(embed)

    async def log_ticket_user_added(
        self,
        staff: discord.Member,
        ticket_id: str,
        added_user: discord.User,
    ) -> None:
        """Log when a user is added to a ticket."""
        embed = self._create_embed("➕ User Added to Ticket", EmbedColors.SUCCESS)
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Added By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="User Added", value=f"{added_user.mention} `[{added_user.id}]`", inline=True)

        await self._queue_embed(embed)

    async def log_ticket_transcript(
        self,
        staff: discord.Member,
        ticket_id: str,
    ) -> None:
        """Log when a ticket transcript is requested."""
        embed = self._create_embed("📜 Transcript Requested", EmbedColors.BLURPLE)
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Requested By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)

        await self._queue_embed(embed)

    # =========================================================================
    # Appeal Events
    # =========================================================================

    async def log_appeal_approved(
        self,
        staff: discord.Member,
        appeal_id: str,
        case_id: str,
        user_id: int,
        action_type: str,
    ) -> None:
        """Log when an appeal is approved."""
        embed = self._create_embed("✅ Appeal Approved", EmbedColors.SUCCESS)
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Approved By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Appeal", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Case", value=f"`{case_id}`", inline=True)
        embed.add_field(name="Type", value=f"`{action_type.title()}`", inline=True)
        embed.add_field(name="User", value=f"<@{user_id}> `[{user_id}]`", inline=True)

        await self._queue_embed(embed)

    async def log_appeal_denied(
        self,
        staff: discord.Member,
        appeal_id: str,
        case_id: str,
        user_id: int,
        action_type: str,
    ) -> None:
        """Log when an appeal is denied."""
        embed = self._create_embed("❌ Appeal Denied", EmbedColors.LOG_NEGATIVE)
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Denied By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Appeal", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Case", value=f"`{case_id}`", inline=True)
        embed.add_field(name="Type", value=f"`{action_type.title()}`", inline=True)
        embed.add_field(name="User", value=f"<@{user_id}> `[{user_id}]`", inline=True)

        await self._queue_embed(embed)

    async def log_appeal_contact(
        self,
        staff: discord.Member,
        appeal_id: str,
        user: discord.User,
    ) -> None:
        """Log when staff contacts a banned user about their appeal."""
        embed = self._create_embed("📬 Appeal Contact Initiated", EmbedColors.APPEAL)
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Staff", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Appeal", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="User Contacted", value=f"{user.mention} `[{user.id}]`", inline=True)

        await self._queue_embed(embed)

    async def log_appeal_ticket_opened(
        self,
        staff: discord.Member,
        appeal_id: str,
        ticket_id: str,
        user: discord.User,
    ) -> None:
        """Log when a ticket is opened for appeal discussion."""
        embed = self._create_embed("🎫 Appeal Ticket Opened", EmbedColors.APPEAL)
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Staff", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="Appeal", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)

        await self._queue_embed(embed)

    # =========================================================================
    # Modmail Events
    # =========================================================================

    async def log_modmail_created(
        self,
        user: discord.User,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log when a modmail thread is created."""
        embed = self._create_embed("📬 Modmail Created", EmbedColors.MODMAIL)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Status", value="`Banned User`", inline=True)

        thread_link = f"https://discord.com/channels/{guild_id}/{thread_id}"
        embed.add_field(name="Thread", value=f"[Open Thread]({thread_link})", inline=True)

        await self._queue_embed(embed)

    async def log_modmail_closed(
        self,
        staff: discord.Member,
        user: discord.User,
        thread_id: int,
    ) -> None:
        """Log when a modmail thread is closed."""
        embed = self._create_embed("🔒 Modmail Closed", EmbedColors.LOG_NEGATIVE)
        embed.set_thumbnail(url=staff.display_avatar.url)
        embed.add_field(name="Closed By", value=f"{staff.mention} `[{staff.id}]`", inline=True)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=True)

        await self._queue_embed(embed)

    # =========================================================================
    # Generic Events
    # =========================================================================

    async def log_button_interaction(
        self,
        user: discord.User,
        button_name: str,
        success: bool = True,
        details: Optional[str] = None,
        **fields
    ) -> None:
        """Log a generic button interaction."""
        color = EmbedColors.SUCCESS if success else EmbedColors.LOG_NEGATIVE
        status = "✅" if success else "❌"

        embed = self._create_embed(f"{status} {button_name}", color)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} `[{user.id}]`", inline=True)

        if details:
            embed.add_field(name="Details", value=f"`{details[:100]}`", inline=False)

        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=True)

        await self._queue_embed(embed)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["InteractionLogger"]
