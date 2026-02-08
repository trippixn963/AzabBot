"""
AzabBot - Ticket Service
========================

Core service logic for the ticket system.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict, List, Any

import discord

from src.core.logger import logger
from src.core.config import get_config
from src.core.database import get_db
from src.core.constants import (
    AUTO_CLOSE_CHECK_INTERVAL,
    THREAD_DELETE_DELAY,
    CLOSE_REQUEST_COOLDOWN,
)
from src.utils.async_utils import create_safe_task
from src.utils.discord_rate_limit import log_http_error

from .constants import (
    INACTIVE_WARNING_DAYS,
    INACTIVE_CLOSE_DAYS,
    DELETE_AFTER_CLOSE_DAYS,
    CLAIM_REMINDER_COOLDOWN,
)
from .buttons.helpers import _is_ticket_staff

# Import mixins
from .auto_close import AutoCloseMixin
from .ticket_helpers import HelpersMixin
from .operations import OperationsMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


class TicketService(AutoCloseMixin, HelpersMixin, OperationsMixin):
    """
    Service for managing support tickets.

    DESIGN:
        Tickets are created as private text channels with permission overwrites.
        Each ticket gets its own channel with sequential ID (T001, T002, etc.).
        All operations via buttons - no slash commands.

        Single Control Panel Pattern:
        - One embed per ticket that updates in place
        - Buttons change based on ticket status
        - Simple notification messages (no buttons) for actions
    """

    CHANNEL_CACHE_TTL = timedelta(minutes=5)

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()
        self._channel: Optional[discord.TextChannel] = None
        self._channel_cache_time: Optional[datetime] = None
        self._channel_cache_map: Dict[int, tuple] = {}  # ticket channel cache {channel_id: (channel, datetime)}
        self._auto_close_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._creation_cooldowns: Dict[int, float] = {}
        self._close_request_cooldowns: Dict[str, float] = {}
        self._pending_deletions: Dict[str, asyncio.Task] = {}
        self._claim_reminder_cooldowns: Dict[str, float] = {}  # "ticket_id:user_id" -> timestamp
        self._cache_lookup_count: int = 0  # Counter for periodic cache cleanup
        # Locks for thread-safe dict access
        self._cooldowns_lock = asyncio.Lock()
        self._deletions_lock = asyncio.Lock()

        if self.enabled:
            logger.tree("Ticket Service Initialized", [
                ("Channel ID", str(self.config.ticket_channel_id)),
                ("Auto-Close", f"{INACTIVE_CLOSE_DAYS} days"),
            ], emoji="🎫")
        else:
            logger.debug("Ticket Service Disabled (no channel configured)")

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Check if ticket system is enabled."""
        return self.config.ticket_channel_id is not None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the ticket service and auto-close scheduler."""
        if not self.enabled:
            logger.info("Ticket service disabled (no channel configured)")
            return

        self._running = True
        self._auto_close_task = create_safe_task(
            self._auto_close_loop(), "Ticket Auto-Close Loop"
        )

        # Verify ticket panel exists (resend if deleted)
        await self.verify_panel()

        # Recover pending deletions from before restart
        recovered = await self._recover_pending_deletions()

        logger.tree("Ticket Service Started", [
            ("Auto-close", f"Enabled (warn: {INACTIVE_WARNING_DAYS}d, close: {INACTIVE_CLOSE_DAYS}d)"),
            ("Auto-delete", f"Enabled ({DELETE_AFTER_CLOSE_DAYS}d after close)"),
            ("Check interval", f"{AUTO_CLOSE_CHECK_INTERVAL}s"),
            ("Recovered deletions", str(recovered)),
        ], emoji="🎫")

    async def stop(self) -> None:
        """Stop the ticket service and cleanup."""
        self._running = False
        if self._auto_close_task and not self._auto_close_task.done():
            self._auto_close_task.cancel()
            try:
                await self._auto_close_task
            except asyncio.CancelledError:
                pass

        # Cancel pending deletions
        async with self._deletions_lock:
            for task in self._pending_deletions.values():
                if not task.done():
                    task.cancel()
            self._pending_deletions.clear()

        logger.debug("Ticket Service Stopped")

    async def _recover_pending_deletions(self) -> int:
        """
        Recover pending ticket deletions after bot restart.

        Checks for closed tickets that should have been deleted (closed_at + delay < now)
        and deletes their channels immediately.

        Returns:
            Number of tickets recovered (channels deleted).
        """
        if not self.config.logging_guild_id:
            return 0

        now = time.time()
        # Tickets closed before this threshold should have been deleted already
        deletion_threshold = now - THREAD_DELETE_DELAY
        recovered = 0

        # Get closed tickets that were closed before the threshold
        # (reuse existing method that filters by closed_at)
        closed_tickets = self.db.get_closed_tickets_ready_to_delete(
            self.config.logging_guild_id, deletion_threshold
        )

        for ticket in closed_tickets:
            ticket_id = ticket["ticket_id"]
            channel_id = ticket["thread_id"]

            # Safety check: only delete if ticket was manually closed by someone
            # This prevents deleting channels for tickets incorrectly marked as closed
            # (e.g., false orphan detection during bot restarts)
            if not ticket.get("closed_by"):
                logger.debug("Skipping Recovery (No Closer)", [
                    ("Ticket", ticket_id),
                    ("Reason", ticket.get("close_reason", "Unknown")),
                ])
                continue

            # Check if channel still exists and delete it
            try:
                channel = await self._get_ticket_channel(channel_id)
                if channel:
                    await channel.delete()
                    logger.debug("Ticket Deletion Recovered", [("Ticket", ticket_id)])
                    recovered += 1
            except Exception as e:
                logger.warning("Failed to recover ticket deletion", [
                    ("Ticket ID", ticket_id),
                    ("Error", str(e)),
                ])

        return recovered

    # =========================================================================
    # Activity Tracking & Message Storage
    # =========================================================================

    async def track_ticket_activity(self, thread_id: int) -> None:
        """
        Track activity in a ticket thread (legacy method for compatibility).

        Use handle_ticket_message() for full message storage.
        """
        ticket = self.db.get_ticket_by_thread(thread_id)
        if not ticket:
            return

        if ticket["status"] == "closed":
            return

        self.db.update_ticket_activity(ticket["ticket_id"])

        # Clear warning flag if ticket becomes active again
        if ticket.get("warned"):
            self.db.clear_ticket_warning(ticket["ticket_id"])

    async def handle_ticket_message(self, message: discord.Message) -> None:
        """
        Handle a new message in a ticket channel.

        DESIGN: Incremental storage approach for real-time transcripts.
        - Stores each message individually (fast INSERT)
        - Transcript is generated on-demand when viewed
        - No regeneration overhead on every message

        Args:
            message: The Discord message sent in the ticket channel
        """
        # Get ticket from channel ID
        ticket = self.db.get_ticket_by_thread(message.channel.id)
        if not ticket:
            return

        if ticket["status"] == "closed":
            return

        # Update activity timestamp
        self.db.update_ticket_activity(ticket["ticket_id"])

        # Clear warning flag if ticket becomes active again
        if ticket.get("warned"):
            self.db.clear_ticket_warning(ticket["ticket_id"])

        # Store message incrementally
        self._store_message(ticket["ticket_id"], message)

        # Check if staff member is typing in unclaimed ticket (remind to claim)
        await self._check_claim_reminder(message, ticket)

        # AI follow-up response for unclaimed tickets (ticket OP only)
        await self._check_ai_followup(message, ticket)

    def _store_message(self, ticket_id: str, message: discord.Message) -> None:
        """
        Store a single message for incremental transcript building.

        Args:
            ticket_id: The ticket ID
            message: The Discord message to store
        """
        # Build attachments list
        attachments = []
        for att in message.attachments:
            attachments.append({
                "filename": att.filename,
                "url": att.url,
                "content_type": att.content_type,
                "size": att.size,
            })

        # Build embeds list
        embeds = []
        for embed in message.embeds:
            embed_data = {
                "title": embed.title,
                "description": embed.description,
                "url": embed.url,
                "color": embed.color.value if embed.color else None,
                "timestamp": embed.timestamp.isoformat() if embed.timestamp else None,
            }
            # Author
            if embed.author:
                embed_data["author"] = {
                    "name": embed.author.name,
                    "url": embed.author.url,
                    "icon_url": embed.author.icon_url,
                }
            # Footer
            if embed.footer:
                embed_data["footer"] = {
                    "text": embed.footer.text,
                    "icon_url": embed.footer.icon_url,
                }
            # Image
            if embed.image:
                embed_data["image"] = {"url": embed.image.url}
            # Thumbnail
            if embed.thumbnail:
                embed_data["thumbnail"] = {"url": embed.thumbnail.url}
            # Fields
            if embed.fields:
                embed_data["fields"] = [
                    {"name": f.name, "value": f.value, "inline": f.inline}
                    for f in embed.fields
                ]
            embeds.append(embed_data)

        # Check if author is staff (has manage_messages permission)
        is_staff = False
        if hasattr(message.author, 'guild_permissions'):
            is_staff = message.author.guild_permissions.manage_messages

        # Store in database
        self.db.store_ticket_message(
            ticket_id=ticket_id,
            message_id=message.id,
            author_id=message.author.id,
            author_name=message.author.name,
            author_display_name=message.author.display_name,
            author_avatar_url=str(message.author.display_avatar.url) if message.author.display_avatar else None,
            content=message.content,
            timestamp=message.created_at.timestamp(),
            is_bot=message.author.bot,
            is_staff=is_staff,
            attachments=attachments if attachments else None,
            embeds=embeds if embeds else None,
        )

    async def _check_claim_reminder(self, message: discord.Message, ticket: dict) -> None:
        """
        Check if a staff member is messaging in an unclaimed ticket and remind them to claim it.

        Conditions for reminder:
        - Author is ticket staff (not the OP)
        - Author is NOT the ticket owner (OP can't claim)
        - Ticket is unclaimed (status "open" and no claimed_by)
        - Author is not a bot
        - Cooldown not active for this staff member on this ticket

        Args:
            message: The Discord message sent in the ticket channel
            ticket: The ticket dict from database
        """
        # Skip bot messages
        if message.author.bot:
            return

        # Skip if ticket is already claimed
        if ticket.get("claimed_by"):
            return

        # Skip if ticket is not in "open" status
        if ticket.get("status") != "open":
            return

        # Skip if author is the ticket owner (they can't claim anyway)
        if message.author.id == ticket.get("user_id"):
            return

        # Check if author is ticket staff
        if not isinstance(message.author, discord.Member):
            return

        if not _is_ticket_staff(message.author):
            return

        # Check cooldown (per ticket per user)
        cooldown_key = f"{ticket['ticket_id']}:{message.author.id}"
        now = time.time()

        async with self._cooldowns_lock:
            last_reminder = self._claim_reminder_cooldowns.get(cooldown_key, 0)
            if now - last_reminder < CLAIM_REMINDER_COOLDOWN:
                return  # Still on cooldown

            # Set cooldown before sending (to avoid race conditions)
            self._claim_reminder_cooldowns[cooldown_key] = now

        # All conditions met - send reminder (reply to their message)
        try:
            await message.reply(
                f"Hey {message.author.mention}, don't forget to **claim** this ticket before helping!",
                mention_author=False,
            )
            logger.tree("Claim Reminder Sent", [
                ("Ticket ID", ticket["ticket_id"]),
                ("Staff", f"{message.author.name} ({message.author.id})"),
                ("Channel", f"#{message.channel.name}"),
            ], emoji="🔔")
        except discord.HTTPException as e:
            log_http_error(e, "Send Claim Reminder", [
                ("Ticket ID", ticket["ticket_id"]),
            ])

    async def clear_claim_reminder_cooldowns(self, ticket_id: str) -> int:
        """
        Clear all claim reminder cooldowns for a ticket.

        Called when a ticket is claimed or closed to prevent memory leaks.

        Args:
            ticket_id: The ticket ID to clear cooldowns for.

        Returns:
            Number of entries cleared.
        """
        prefix = f"{ticket_id}:"
        cleared = 0

        async with self._cooldowns_lock:
            keys_to_remove = [k for k in self._claim_reminder_cooldowns if k.startswith(prefix)]
            for key in keys_to_remove:
                del self._claim_reminder_cooldowns[key]
                cleared += 1

        if cleared > 0:
            logger.debug("Claim Cooldowns Cleared", [("Ticket", ticket_id), ("Cleared", str(cleared))])

        return cleared

    async def _check_ai_followup(self, message: discord.Message, ticket: dict) -> None:
        """
        Check if AI should respond to a ticket message.

        Conditions for AI response:
        - Author is the ticket owner (OP)
        - Ticket is unclaimed (no staff has claimed it yet)
        - AI service is enabled and has responses remaining
        - Message is not from a bot

        Args:
            message: The Discord message sent in the ticket channel
            ticket: The ticket dict from database
        """
        # Skip bot messages
        if message.author.bot:
            return

        # Only respond to ticket owner (OP)
        if message.author.id != ticket.get("user_id"):
            return

        # Skip if ticket is already claimed (staff is handling)
        if ticket.get("claimed_by"):
            return

        # Skip if ticket is not in "open" status
        if ticket.get("status") != "open":
            return

        # Check if AI service is available and can respond
        if not hasattr(self.bot, "ai_service") or not self.bot.ai_service:
            return

        if not self.bot.ai_service.enabled:
            return

        # Handle attachment-only messages
        if (not message.content or not message.content.strip()) and message.attachments:
            # Acknowledge attachments
            ack_message = self.bot.ai_service.get_attachment_acknowledgment(len(message.attachments))
            try:
                await message.reply(ack_message, mention_author=False)
                logger.tree("AI Attachment Acknowledged", [
                    ("Ticket ID", ticket["ticket_id"]),
                    ("Attachments", str(len(message.attachments))),
                ], emoji="🤖")
            except discord.HTTPException:
                pass
            return

        # Skip empty messages with no attachments
        if not message.content or not message.content.strip():
            return

        # Check if we can still respond to this ticket
        can_respond = await self.bot.ai_service.can_respond_to_ticket(ticket["ticket_id"])
        if not can_respond:
            return

        # Show typing indicator while generating response
        try:
            async with message.channel.typing():
                # Generate AI follow-up response
                ai_response = await self.bot.ai_service.generate_followup_response(
                    ticket_id=ticket["ticket_id"],
                    user_message=message.content,
                )
        except discord.HTTPException:
            # Typing failed, still try to generate response
            ai_response = await self.bot.ai_service.generate_followup_response(
                ticket_id=ticket["ticket_id"],
                user_message=message.content,
            )

        if ai_response:
            try:
                # Send as a reply to the user's message
                await message.reply(ai_response, mention_author=False)
                logger.tree("AI Follow-up Sent", [
                    ("Ticket ID", ticket["ticket_id"]),
                    ("User", f"{message.author.name} ({message.author.id})"),
                    ("Channel", f"#{message.channel.name}"),
                ], emoji="🤖")
            except discord.HTTPException as e:
                log_http_error(e, "Send AI Follow-up", [
                    ("Ticket ID", ticket["ticket_id"]),
                ])
