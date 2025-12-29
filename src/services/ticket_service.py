"""
Azab Discord Bot - Ticket Service
==================================

Service for handling support tickets.

Features:
    - Create tickets via panel buttons (Support, Partnership, Suggestion, Staff)
    - Tickets create forum threads
    - Staff controls: Claim, Close, Reopen, Priority, Assign
    - All operations via buttons (no slash commands)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.retry import safe_fetch_channel, safe_send, safe_edit
from src.utils.views import APPROVE_EMOJI, DENY_EMOJI, HistoryButton

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Custom emojis
TICKET_EMOJI = discord.PartialEmoji(name="ticket", id=1455177168098295983)
PARTNERSHIP_EMOJI = discord.PartialEmoji(name="appeal", id=1454788569594859726)
SUGGESTION_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon22", id=1455178213771972608)
STAFF_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon23", id=1455178387927732381)

# Category configurations
TICKET_CATEGORIES = {
    "support": {
        "label": "Support",
        "emoji": TICKET_EMOJI,
        "description": "General support requests",
        "color": EmbedColors.GREEN,
    },
    "partnership": {
        "label": "Partnership",
        "emoji": PARTNERSHIP_EMOJI,
        "description": "Partnership inquiries",
        "color": EmbedColors.GREEN,
    },
    "suggestion": {
        "label": "Suggestion",
        "emoji": SUGGESTION_EMOJI,
        "description": "Server suggestions",
        "color": EmbedColors.GOLD,
    },
}

# Priority configurations
PRIORITY_CONFIG = {
    "low": {"emoji": "⬜", "color": 0x808080},  # Gray
    "normal": {"emoji": "🟦", "color": EmbedColors.BLUE},
    "high": {"emoji": "🟧", "color": 0xFFA500},  # Orange
    "urgent": {"emoji": "🟥", "color": EmbedColors.RED},
}

# Max open tickets per user
MAX_OPEN_TICKETS_PER_USER = 3

# Auto-close settings
INACTIVE_WARNING_DAYS = 3  # Warn after 3 days of inactivity
INACTIVE_CLOSE_DAYS = 5    # Close after 5 days of inactivity
AUTO_CLOSE_CHECK_INTERVAL = 3600  # Check every hour


# =============================================================================
# Ticket Service
# =============================================================================

class TicketService:
    """
    Service for managing support tickets.

    DESIGN:
        Tickets are created as threads in a dedicated text channel.
        Each ticket gets its own thread with sequential ID (T001, T002, etc.).
        All operations via buttons - no slash commands.
    """

    # Thread cache TTL
    THREAD_CACHE_TTL = timedelta(minutes=5)

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()
        self._channel: Optional[discord.TextChannel] = None
        self._channel_cache_time: Optional[datetime] = None
        self._thread_cache: Dict[int, tuple[discord.Thread, datetime]] = {}
        self._auto_close_task: Optional[asyncio.Task] = None
        self._running: bool = False

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
        self._auto_close_task = asyncio.create_task(self._auto_close_loop())
        logger.tree("Ticket Service Started", [
            ("Auto-close", f"Enabled (warn: {INACTIVE_WARNING_DAYS}d, close: {INACTIVE_CLOSE_DAYS}d)"),
            ("Check interval", f"{AUTO_CLOSE_CHECK_INTERVAL}s"),
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
        logger.debug("Ticket Service Stopped")

    async def _auto_close_loop(self) -> None:
        """Background task to check for inactive tickets."""
        await self.bot.wait_until_ready()

        while self._running:
            try:
                await self._check_inactive_tickets()
            except Exception as e:
                logger.error("Auto-close check failed", [("Error", str(e))])

            await asyncio.sleep(AUTO_CLOSE_CHECK_INTERVAL)

    async def _check_inactive_tickets(self) -> None:
        """Check for inactive tickets and send warnings or auto-close."""
        if not self.enabled:
            return

        # Get the primary guild
        channel = await self._get_channel()
        if not channel:
            return
        guild_id = channel.guild.id

        now = time.time()
        warning_threshold = now - (INACTIVE_WARNING_DAYS * 24 * 60 * 60)
        close_threshold = now - ((INACTIVE_CLOSE_DAYS - INACTIVE_WARNING_DAYS) * 24 * 60 * 60)

        # Step 1: Send warnings to tickets inactive for INACTIVE_WARNING_DAYS
        unwarned_tickets = self.db.get_unwarned_inactive_tickets(guild_id, warning_threshold)
        for ticket in unwarned_tickets:
            await self._send_inactivity_warning(ticket)

        # Step 2: Auto-close tickets that were warned and still inactive
        warned_tickets = self.db.get_warned_tickets_ready_to_close(guild_id, close_threshold)
        for ticket in warned_tickets:
            await self._auto_close_ticket(ticket)

    async def _send_inactivity_warning(self, ticket: dict) -> None:
        """Send an inactivity warning to a ticket thread."""
        thread = await self._get_ticket_thread(ticket["thread_id"])
        if not thread:
            return

        try:
            days_until_close = INACTIVE_CLOSE_DAYS - INACTIVE_WARNING_DAYS

            warning_embed = discord.Embed(
                title="⚠️ Inactivity Warning",
                description=(
                    f"This ticket has been inactive for **{INACTIVE_WARNING_DAYS} days**.\n\n"
                    f"If there is no response within **{days_until_close} day(s)**, "
                    f"this ticket will be automatically closed.\n\n"
                    f"Please reply to keep this ticket open."
                ),
                color=0xFFA500,  # Orange
            )
            set_footer(warning_embed)
            await safe_send(thread, embed=warning_embed)

            # Mark as warned
            self.db.mark_ticket_warned(ticket["ticket_id"])

            logger.tree("Ticket Warning Sent", [
                ("Ticket ID", ticket["ticket_id"]),
                ("Days inactive", str(INACTIVE_WARNING_DAYS)),
            ], emoji="⚠️")

        except Exception as e:
            logger.error("Failed to send warning", [
                ("Ticket ID", ticket["ticket_id"]),
                ("Error", str(e)),
            ])

    async def _auto_close_ticket(self, ticket: dict) -> None:
        """Automatically close an inactive ticket."""
        try:
            # Get bot member for closing
            channel = await self._get_channel()
            if not channel:
                return
            bot_member = channel.guild.me

            # Close the ticket
            success, _ = await self.close_ticket(
                ticket_id=ticket["ticket_id"],
                closed_by=bot_member,
                reason=f"Auto-closed due to {INACTIVE_CLOSE_DAYS} days of inactivity",
            )

            if success:
                logger.tree("Ticket Auto-Closed", [
                    ("Ticket ID", ticket["ticket_id"]),
                    ("Days inactive", str(INACTIVE_CLOSE_DAYS)),
                ], emoji="⏰")

        except Exception as e:
            logger.error("Failed to auto-close ticket", [
                ("Ticket ID", ticket["ticket_id"]),
                ("Error", str(e)),
            ])

    async def track_ticket_activity(self, thread_id: int) -> None:
        """
        Track activity in a ticket thread.
        Call this when a message is sent in a ticket thread.

        Args:
            thread_id: The thread ID where activity occurred.
        """
        ticket = self.db.get_ticket_by_thread(thread_id)
        if not ticket:
            return

        # Skip if ticket is closed
        if ticket["status"] == "closed":
            return

        # Update last activity
        self.db.update_ticket_activity(ticket["ticket_id"])

        # Clear any warning if user responded
        if ticket.get("warned_at"):
            self.db.clear_ticket_warning(ticket["ticket_id"])
            logger.debug(f"Cleared inactivity warning for ticket {ticket['ticket_id']}")

    # =========================================================================
    # Channel Access
    # =========================================================================

    async def _get_channel(self) -> Optional[discord.TextChannel]:
        """Get the ticket channel with caching."""
        if not self.config.ticket_channel_id:
            return None

        now = datetime.now(NY_TZ)

        # Check cache
        if self._channel is not None and self._channel_cache_time is not None:
            if now - self._channel_cache_time < self.THREAD_CACHE_TTL:
                return self._channel

        # Fetch channel
        channel = await safe_fetch_channel(self.bot, self.config.ticket_channel_id)
        if channel is None:
            logger.warning(f"Ticket Channel Not Found: {self.config.ticket_channel_id}")
            return None

        if isinstance(channel, discord.TextChannel):
            self._channel = channel
            self._channel_cache_time = now
            return self._channel

        logger.warning(f"Channel {self.config.ticket_channel_id} is not a TextChannel")
        return None

    async def _get_ticket_thread(self, thread_id: int) -> Optional[discord.Thread]:
        """Get a ticket thread by ID with caching."""
        now = datetime.now(NY_TZ)

        # Check cache
        if thread_id in self._thread_cache:
            cached_thread, cached_at = self._thread_cache[thread_id]
            if now - cached_at < self.THREAD_CACHE_TTL:
                return cached_thread
            else:
                del self._thread_cache[thread_id]

        # Fetch thread
        channel = await safe_fetch_channel(self.bot, thread_id)
        if channel is None:
            return None

        if isinstance(channel, discord.Thread):
            self._thread_cache[thread_id] = (channel, now)
            if len(self._thread_cache) > 50:
                oldest = min(self._thread_cache.keys(), key=lambda k: self._thread_cache[k][1])
                del self._thread_cache[oldest]
            return channel

        return None

    # =========================================================================
    # Permission Checks
    # =========================================================================

    def has_staff_permission(self, member: discord.Member) -> bool:
        """Check if member has permission to manage tickets."""
        # Developer always has access
        if member.id == self.config.developer_id:
            return True

        # Check for administrator
        if member.guild_permissions.administrator:
            return True

        # Check for moderate_members
        if member.guild_permissions.moderate_members:
            return True

        # Check for ticket staff role
        if self.config.ticket_staff_role_id:
            for role in member.roles:
                if role.id == self.config.ticket_staff_role_id:
                    return True

        return False

    # =========================================================================
    # Ticket Operations
    # =========================================================================

    async def create_ticket(
        self,
        user: discord.Member,
        category: str,
        subject: str,
        description: str,
    ) -> tuple[bool, str, Optional[str]]:
        """
        Create a new support ticket.

        Args:
            user: User creating the ticket.
            category: Ticket category.
            subject: Ticket subject.
            description: Initial description.

        Returns:
            Tuple of (success, message, ticket_id).
        """
        if not self.enabled:
            return (False, "Ticket system is not enabled.", None)

        # Check open ticket limit
        open_count = self.db.get_user_open_ticket_count(user.id, user.guild.id)
        if open_count >= MAX_OPEN_TICKETS_PER_USER:
            return (False, f"You already have {open_count} open ticket(s). Please wait for them to be resolved.", None)

        # Get ticket channel
        channel = await self._get_channel()
        if not channel:
            return (False, "Ticket channel not found.", None)

        # Generate ticket ID
        ticket_id = self.db.generate_ticket_id()

        # Create thread name (max 100 chars)
        username = user.display_name[:20]
        cat_info = TICKET_CATEGORIES.get(category, TICKET_CATEGORIES["support"])
        thread_name = f"[{ticket_id}] | {cat_info['label']} | {username}"
        if len(thread_name) > 100:
            thread_name = thread_name[:97] + "..."

        # Build initial embed
        embed = await self._build_ticket_embed(
            ticket_id=ticket_id,
            user=user,
            category=category,
            subject=subject,
            description=description,
            status="open",
            priority="normal",
        )

        # Create view with action buttons
        view = TicketActionView(ticket_id, user_id=user.id, guild_id=user.guild.id)

        try:
            # Create thread in channel
            thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                auto_archive_duration=10080,  # 7 days
            )

            # Send initial embed with action buttons
            await thread.send(embed=embed, view=view)

            # Save to database
            self.db.create_ticket(
                ticket_id=ticket_id,
                user_id=user.id,
                guild_id=user.guild.id,
                thread_id=thread.id,
                category=category,
                subject=subject,
            )

            # Add user to thread
            await thread.add_user(user)

            # Determine who to assign based on category
            if category == "partnership" and self.config.ticket_partnership_user_id:
                assigned_text = f"This ticket has been assigned to <@{self.config.ticket_partnership_user_id}>."
                ping_content = f"<@{self.config.ticket_partnership_user_id}>"
            elif category == "suggestion" and self.config.ticket_suggestion_user_id:
                assigned_text = f"This ticket has been assigned to <@{self.config.ticket_suggestion_user_id}>."
                ping_content = f"<@{self.config.ticket_suggestion_user_id}>"
            elif self.config.ticket_support_user_ids:
                # Support tickets - multiple assignees
                user_mentions = " and ".join(f"<@{uid}>" for uid in self.config.ticket_support_user_ids)
                ping_mentions = " ".join(f"<@{uid}>" for uid in self.config.ticket_support_user_ids)
                if len(self.config.ticket_support_user_ids) > 1:
                    assigned_text = f"This ticket has been assigned to {user_mentions}.\nPlease wait for one of them to claim your ticket."
                else:
                    assigned_text = f"This ticket has been assigned to {user_mentions}."
                ping_content = ping_mentions
            else:
                assigned_text = "A staff member will be with you shortly."
                ping_content = None

            # Send welcome message with assignment
            welcome_embed = discord.Embed(
                description=(
                    f"Welcome {user.mention}!\n\n"
                    f"{assigned_text}\n"
                    f"Please describe your issue in detail.\n\n"
                    f"**Subject:** {subject}"
                ),
                color=cat_info["color"],
            )
            set_footer(welcome_embed)
            await thread.send(embed=welcome_embed)

            # Ping staff (auto-delete)
            if ping_content:
                await thread.send(ping_content, delete_after=1)

            logger.tree("Ticket Created", [
                ("Ticket ID", ticket_id),
                ("Category", category),
                ("User", f"{user} ({user.id})"),
                ("Thread", str(thread.id)),
            ], emoji="🎫")

            # Log to server logs
            if hasattr(self.bot, 'logging_service') and self.bot.logging_service:
                await self.bot.logging_service.log_ticket_created(
                    ticket_id=ticket_id,
                    user=user,
                    category=category,
                    subject=subject,
                    thread_id=thread.id,
                    guild_id=user.guild.id,
                )

            return (True, f"Ticket {ticket_id} created! Check {thread.mention}", ticket_id)

        except discord.HTTPException as e:
            logger.error("Ticket Creation Failed", [
                ("Error", str(e)),
                ("User", f"{user} ({user.id})"),
            ])
            return (False, f"Failed to create ticket: {e}", None)

    async def close_ticket(
        self,
        ticket_id: str,
        closed_by: discord.Member,
        reason: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Close a ticket.

        Args:
            ticket_id: Ticket ID to close.
            closed_by: Staff member closing the ticket.
            reason: Optional close reason.

        Returns:
            Tuple of (success, message).
        """
        ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.")

        if ticket["status"] == "closed":
            return (False, "Ticket is already closed.")

        # Close in database
        if not self.db.close_ticket(ticket_id, closed_by.id, reason):
            return (False, "Failed to close ticket.")

        # Get thread and update
        thread = await self._get_ticket_thread(ticket["thread_id"])
        transcript_messages = []
        if thread:
            # Collect transcript before closing
            try:
                async for message in thread.history(limit=500, oldest_first=True):
                    # Skip the initial embed message
                    if message.embeds and not message.content:
                        continue
                    transcript_messages.append({
                        "author": str(message.author),
                        "author_id": str(message.author.id),
                        "content": message.content,
                        "timestamp": message.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "attachments": [att.url for att in message.attachments],
                    })
            except Exception as e:
                logger.error("Failed to collect transcript", [("Error", str(e))])

            # Update embed
            try:
                async for message in thread.history(limit=1, oldest_first=True):
                    if message.embeds:
                        user = await self.bot.fetch_user(ticket["user_id"])
                        embed = await self._build_ticket_embed(
                            ticket_id=ticket_id,
                            user=user,
                            category=ticket["category"],
                            subject=ticket["subject"],
                            description="",
                            status="closed",
                            priority=ticket.get("priority", "normal"),
                            claimed_by=ticket.get("claimed_by"),
                            closed_by=closed_by.id,
                            close_reason=reason,
                        )
                        view = TicketClosedView(ticket_id)
                        await message.edit(embed=embed, view=view)
                    break
            except Exception as e:
                logger.error("Failed to update ticket embed", [("Error", str(e))])

            # Send close message
            close_embed = discord.Embed(
                title="🔒 Ticket Closed",
                description=(
                    f"This ticket has been closed by {closed_by.mention}.\n\n"
                    f"**Reason:** {reason or 'No reason provided'}"
                ),
                color=EmbedColors.RED,
            )
            set_footer(close_embed)
            await safe_send(thread, embed=close_embed)

            # Archive thread
            try:
                await thread.edit(archived=True, locked=True)
            except discord.HTTPException:
                pass

        # DM the user
        try:
            user = await self.bot.fetch_user(ticket["user_id"])
            dm_embed = discord.Embed(
                title="🔒 Ticket Closed",
                description=(
                    f"Your ticket **{ticket_id}** has been closed.\n\n"
                    f"**Category:** {ticket['category'].title()}\n"
                    f"**Subject:** {ticket['subject']}\n"
                    f"**Closed By:** {closed_by.display_name}\n"
                    f"**Reason:** {reason or 'No reason provided'}\n\n"
                    f"Thank you for contacting us!"
                ),
                color=EmbedColors.GOLD,
            )
            set_footer(dm_embed)
            await user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass  # User has DMs disabled

        logger.tree("Ticket Closed", [
            ("Ticket ID", ticket_id),
            ("Closed By", f"{closed_by} ({closed_by.id})"),
            ("Reason", reason or "None"),
        ], emoji="🔒")

        # Log to server logs
        if hasattr(self.bot, 'logging_service') and self.bot.logging_service:
            try:
                user = await self.bot.fetch_user(ticket["user_id"])
                # Log ticket closed
                await self.bot.logging_service.log_ticket_closed(
                    ticket_id=ticket_id,
                    user=user,
                    closed_by=closed_by,
                    category=ticket["category"],
                    reason=reason,
                )
                # Log transcript
                import time
                await self.bot.logging_service.log_ticket_transcript(
                    ticket_id=ticket_id,
                    user=user,
                    category=ticket["category"],
                    subject=ticket["subject"],
                    messages=transcript_messages,
                    closed_by=closed_by,
                    created_at=ticket["created_at"],
                    closed_at=time.time(),
                )
            except Exception as e:
                logger.error("Failed to log ticket close", [("Error", str(e))])

        return (True, f"Ticket {ticket_id} closed.")

    async def reopen_ticket(
        self,
        ticket_id: str,
        reopened_by: discord.Member,
    ) -> tuple[bool, str]:
        """
        Reopen a closed ticket.

        Args:
            ticket_id: Ticket ID to reopen.
            reopened_by: Staff member reopening the ticket.

        Returns:
            Tuple of (success, message).
        """
        ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.")

        if ticket["status"] != "closed":
            return (False, "Ticket is not closed.")

        # Reopen in database
        if not self.db.reopen_ticket(ticket_id):
            return (False, "Failed to reopen ticket.")

        # Get thread and update
        thread = await self._get_ticket_thread(ticket["thread_id"])
        if thread:
            # Unarchive thread
            try:
                await thread.edit(archived=False, locked=False)
            except discord.HTTPException:
                pass

            # Update embed
            try:
                async for message in thread.history(limit=1, oldest_first=True):
                    if message.embeds:
                        user = await self.bot.fetch_user(ticket["user_id"])
                        embed = await self._build_ticket_embed(
                            ticket_id=ticket_id,
                            user=user,
                            category=ticket["category"],
                            subject=ticket["subject"],
                            description="",
                            status="open",
                            priority=ticket.get("priority", "normal"),
                        )
                        view = TicketActionView(ticket_id, user_id=ticket["user_id"], guild_id=ticket["guild_id"])
                        await message.edit(embed=embed, view=view)
                    break
            except Exception as e:
                logger.error("Failed to update ticket embed", [("Error", str(e))])

            # Send reopen message
            reopen_embed = discord.Embed(
                title="🔓 Ticket Reopened",
                description=f"This ticket has been reopened by {reopened_by.mention}.",
                color=EmbedColors.GREEN,
            )
            set_footer(reopen_embed)
            await safe_send(thread, embed=reopen_embed)

        logger.tree("Ticket Reopened", [
            ("Ticket ID", ticket_id),
            ("Reopened By", f"{reopened_by} ({reopened_by.id})"),
        ], emoji="🔓")

        # Log to server logs
        if hasattr(self.bot, 'logging_service') and self.bot.logging_service:
            try:
                user = await self.bot.fetch_user(ticket["user_id"])
                await self.bot.logging_service.log_ticket_reopened(
                    ticket_id=ticket_id,
                    user=user,
                    reopened_by=reopened_by,
                    category=ticket["category"],
                )
            except Exception as e:
                logger.error("Failed to log ticket reopen", [("Error", str(e))])

        return (True, f"Ticket {ticket_id} reopened.")

    async def claim_ticket(
        self,
        ticket_id: str,
        staff: discord.Member,
    ) -> tuple[bool, str]:
        """
        Claim a ticket.

        Args:
            ticket_id: Ticket ID to claim.
            staff: Staff member claiming the ticket.

        Returns:
            Tuple of (success, message).
        """
        ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.")

        if ticket["status"] == "closed":
            return (False, "Cannot claim a closed ticket.")

        if ticket["status"] == "claimed":
            if ticket["claimed_by"] == staff.id:
                return (False, "You already claimed this ticket.")
            return (False, "Ticket is already claimed by another staff member.")

        # Claim in database
        if not self.db.claim_ticket(ticket_id, staff.id):
            return (False, "Failed to claim ticket.")

        # Get thread and update
        thread = await self._get_ticket_thread(ticket["thread_id"])
        if thread:
            # Update embed
            try:
                async for message in thread.history(limit=1, oldest_first=True):
                    if message.embeds:
                        user = await self.bot.fetch_user(ticket["user_id"])
                        embed = await self._build_ticket_embed(
                            ticket_id=ticket_id,
                            user=user,
                            category=ticket["category"],
                            subject=ticket["subject"],
                            description="",
                            status="claimed",
                            priority=ticket.get("priority", "normal"),
                            claimed_by=staff.id,
                        )
                        view = TicketActionView(ticket_id, user_id=ticket["user_id"], guild_id=ticket["guild_id"])
                        await message.edit(embed=embed, view=view)
                    break
            except Exception as e:
                logger.error("Failed to update ticket embed", [("Error", str(e))])

            # Send claim message
            claim_embed = discord.Embed(
                description=f"✋ {staff.mention} has claimed this ticket.",
                color=EmbedColors.BLUE,
            )
            await safe_send(thread, embed=claim_embed)

        # DM the user
        try:
            user = await self.bot.fetch_user(ticket["user_id"])
            dm_embed = discord.Embed(
                title="🎫 Ticket Update",
                description=(
                    f"Your ticket **{ticket_id}** has been claimed!\n\n"
                    f"**Staff Member:** {staff.display_name}\n"
                    f"**Category:** {ticket['category'].title()}\n\n"
                    f"A staff member is now reviewing your ticket."
                ),
                color=EmbedColors.GREEN,
            )
            set_footer(dm_embed)
            await user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass  # User has DMs disabled

        logger.tree("Ticket Claimed", [
            ("Ticket ID", ticket_id),
            ("Claimed By", f"{staff} ({staff.id})"),
        ], emoji="✋")

        # Log to server logs
        if hasattr(self.bot, 'logging_service') and self.bot.logging_service:
            try:
                user = await self.bot.fetch_user(ticket["user_id"])
                await self.bot.logging_service.log_ticket_claimed(
                    ticket_id=ticket_id,
                    user=user,
                    staff=staff,
                    category=ticket["category"],
                )
            except Exception as e:
                logger.error("Failed to log ticket claim", [("Error", str(e))])

        return (True, f"You claimed ticket {ticket_id}.")

    async def set_priority(
        self,
        ticket_id: str,
        priority: str,
        set_by: discord.Member,
    ) -> tuple[bool, str]:
        """
        Set ticket priority.

        Args:
            ticket_id: Ticket ID.
            priority: New priority.
            set_by: Staff member setting priority.

        Returns:
            Tuple of (success, message).
        """
        ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.")

        if ticket["status"] == "closed":
            return (False, "Cannot change priority of a closed ticket.")

        # Set priority in database
        if not self.db.set_ticket_priority(ticket_id, priority):
            return (False, "Failed to set priority.")

        # Get thread and update
        thread = await self._get_ticket_thread(ticket["thread_id"])
        if thread:
            # Update embed
            try:
                async for message in thread.history(limit=1, oldest_first=True):
                    if message.embeds:
                        user = await self.bot.fetch_user(ticket["user_id"])
                        embed = await self._build_ticket_embed(
                            ticket_id=ticket_id,
                            user=user,
                            category=ticket["category"],
                            subject=ticket["subject"],
                            description="",
                            status=ticket["status"],
                            priority=priority,
                            claimed_by=ticket.get("claimed_by"),
                        )
                        view = TicketActionView(ticket_id, user_id=ticket["user_id"], guild_id=ticket["guild_id"])
                        await message.edit(embed=embed, view=view)
                    break
            except Exception as e:
                logger.error("Failed to update ticket embed", [("Error", str(e))])

            # Send priority change message
            priority_config = PRIORITY_CONFIG.get(priority, PRIORITY_CONFIG["normal"])
            priority_embed = discord.Embed(
                description=f"{priority_config['emoji']} Priority set to **{priority.upper()}** by {set_by.mention}.",
                color=priority_config["color"],
            )
            await safe_send(thread, embed=priority_embed)

        logger.tree("Ticket Priority Set", [
            ("Ticket ID", ticket_id),
            ("Priority", priority),
            ("Set By", f"{set_by} ({set_by.id})"),
        ], emoji="🔔")

        return (True, f"Priority set to {priority}.")

    async def assign_ticket(
        self,
        ticket_id: str,
        assigned_to: discord.Member,
        assigned_by: discord.Member,
    ) -> tuple[bool, str]:
        """
        Assign a ticket to a staff member.

        Args:
            ticket_id: Ticket ID.
            assigned_to: Staff member to assign to.
            assigned_by: Staff member making the assignment.

        Returns:
            Tuple of (success, message).
        """
        ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.")

        if ticket["status"] == "closed":
            return (False, "Cannot assign a closed ticket.")

        # Assign in database
        if not self.db.assign_ticket(ticket_id, assigned_to.id):
            return (False, "Failed to assign ticket.")

        # Get thread and notify
        thread = await self._get_ticket_thread(ticket["thread_id"])
        if thread:
            # Add assigned staff to thread
            try:
                await thread.add_user(assigned_to)
            except discord.HTTPException:
                pass

            # Send assignment message
            assign_embed = discord.Embed(
                description=f"👤 Ticket assigned to {assigned_to.mention} by {assigned_by.mention}.",
                color=EmbedColors.BLUE,
            )
            await safe_send(thread, embed=assign_embed)

        logger.tree("Ticket Assigned", [
            ("Ticket ID", ticket_id),
            ("Assigned To", f"{assigned_to} ({assigned_to.id})"),
            ("Assigned By", f"{assigned_by} ({assigned_by.id})"),
        ], emoji="👤")

        return (True, f"Ticket assigned to {assigned_to.display_name}.")

    async def add_user_to_ticket(
        self,
        ticket_id: str,
        user_id: int,
        added_by: discord.Member,
    ) -> tuple[bool, str]:
        """
        Add a user to a ticket thread.

        Args:
            ticket_id: Ticket ID.
            user_id: User ID to add.
            added_by: Staff member adding the user.

        Returns:
            Tuple of (success, message).
        """
        ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.")

        if ticket["status"] == "closed":
            return (False, "Cannot add users to a closed ticket.")

        # Get the thread
        thread = await self._get_ticket_thread(ticket["thread_id"])
        if not thread:
            return (False, "Ticket thread not found.")

        # Fetch the user to add
        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            return (False, "User not found.")
        except discord.HTTPException as e:
            return (False, f"Failed to fetch user: {e}")

        # Add user to thread
        try:
            await thread.add_user(user)
        except discord.HTTPException as e:
            return (False, f"Failed to add user to thread: {e}")

        # Send notification in thread
        add_embed = discord.Embed(
            description=f"👤 {user.mention} has been added to this ticket by {added_by.mention}.",
            color=EmbedColors.BLUE,
        )
        await safe_send(thread, embed=add_embed)

        logger.tree("User Added to Ticket", [
            ("Ticket ID", ticket_id),
            ("User Added", f"{user} ({user.id})"),
            ("Added By", f"{added_by} ({added_by.id})"),
        ], emoji="👤")

        # Log to server logs
        if hasattr(self.bot, 'logging_service') and self.bot.logging_service:
            try:
                ticket_user = await self.bot.fetch_user(ticket["user_id"])
                await self.bot.logging_service.log_ticket_user_added(
                    ticket_id=ticket_id,
                    ticket_user=ticket_user,
                    added_user=user,
                    added_by=added_by,
                )
            except Exception as e:
                logger.error("Failed to log ticket user add", [("Error", str(e))])

        return (True, f"{user.display_name} has been added to the ticket.")

    # =========================================================================
    # Panel
    # =========================================================================

    async def send_panel(self, channel: discord.TextChannel) -> Optional[discord.Message]:
        """
        Send the ticket creation panel to a channel.

        Args:
            channel: Channel to send the panel to.

        Returns:
            The panel message or None.
        """
        if not self.enabled:
            logger.warning("Cannot send panel - ticket system not enabled")
            return None

        # Get server banner
        guild = channel.guild
        banner_url = guild.banner.url if guild.banner else None

        embed = discord.Embed(
            description=(
                "\n"
                "## 📬  Support Tickets\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Need assistance? Open a ticket below and\n"
                "our staff team will respond shortly.\n\n"
                f"{TICKET_EMOJI}  **Support**\n"
                f"-# Questions, issues, or general help\n\n"
                f"{PARTNERSHIP_EMOJI}  **Partnership**\n"
                f"-# Business inquiries & collaborations\n\n"
                f"{SUGGESTION_EMOJI}  **Suggestion**\n"
                f"-# Ideas & feedback for the server\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=EmbedColors.GREEN,
        )

        if banner_url:
            embed.set_image(url=banner_url)

        set_footer(embed)

        view = TicketPanelView()

        try:
            message = await channel.send(embed=embed, view=view)
            logger.tree("Ticket Panel Sent", [
                ("Channel", f"{channel.name} ({channel.id})"),
            ], emoji="🎫")
            return message
        except discord.HTTPException as e:
            logger.error("Failed to send ticket panel", [("Error", str(e))])
            return None

    # =========================================================================
    # Embed Builders
    # =========================================================================

    async def _build_ticket_embed(
        self,
        ticket_id: str,
        user: discord.User,
        category: str,
        subject: str,
        description: str,
        status: str,
        priority: str,
        claimed_by: Optional[int] = None,
        assigned_to: Optional[int] = None,
        closed_by: Optional[int] = None,
        close_reason: Optional[str] = None,
    ) -> discord.Embed:
        """Build the main ticket embed."""
        cat_info = TICKET_CATEGORIES.get(category, TICKET_CATEGORIES["support"])

        # Status configuration
        status_config = {
            "open": {"emoji": "🟢", "label": "Open", "color": EmbedColors.GREEN},
            "claimed": {"emoji": "🟡", "label": "Claimed", "color": EmbedColors.GOLD},
            "closed": {"emoji": "🔴", "label": "Closed", "color": EmbedColors.RED},
        }
        status_info = status_config.get(status, status_config["open"])

        embed = discord.Embed(
            title=f"{status_info['emoji']} Ticket {ticket_id}",
            color=status_info["color"],
        )

        # Add user's avatar
        embed.set_thumbnail(url=user.display_avatar.url)

        # Add fields
        embed.add_field(
            name="Category",
            value=cat_info['label'],
            inline=True,
        )
        embed.add_field(
            name="Status",
            value=status_info['label'],
            inline=True,
        )
        embed.add_field(
            name="Opened By",
            value=user.mention,
            inline=True,
        )
        embed.add_field(
            name="Subject",
            value=subject[:1024] if subject else "No subject",
            inline=False,
        )

        # Add claimed by if applicable
        if claimed_by:
            try:
                claimer = await self.bot.fetch_user(claimed_by)
                embed.add_field(name="Claimed By", value=claimer.mention, inline=True)
            except discord.NotFound:
                embed.add_field(name="Claimed By", value=f"User {claimed_by}", inline=True)

        # Add assigned to if applicable
        if assigned_to:
            try:
                assignee = await self.bot.fetch_user(assigned_to)
                embed.add_field(name="Assigned To", value=assignee.mention, inline=True)
            except discord.NotFound:
                embed.add_field(name="Assigned To", value=f"User {assigned_to}", inline=True)

        # Add closed info if applicable
        if status == "closed" and closed_by:
            try:
                closer = await self.bot.fetch_user(closed_by)
                embed.add_field(name="Closed By", value=closer.mention, inline=True)
            except discord.NotFound:
                embed.add_field(name="Closed By", value=f"User {closed_by}", inline=True)

            if close_reason:
                embed.add_field(name="Close Reason", value=close_reason[:1024], inline=False)

        set_footer(embed)
        return embed

# =============================================================================
# Views
# =============================================================================

class TicketPanelView(discord.ui.View):
    """Persistent view for the ticket creation panel."""

    def __init__(self):
        super().__init__(timeout=None)

        # Add category buttons
        for category, info in TICKET_CATEGORIES.items():
            self.add_item(TicketCategoryButton(category))


class TicketActionView(discord.ui.View):
    """Persistent view for ticket action buttons."""

    def __init__(self, ticket_id: str, user_id: int = None, guild_id: int = None):
        super().__init__(timeout=None)
        self.add_item(TicketClaimButton(ticket_id))
        self.add_item(TicketCloseButton(ticket_id))
        self.add_item(TicketAddUserButton(ticket_id))
        self.add_item(TicketTranscriptButton(ticket_id))
        # Add history button if user_id and guild_id provided
        if user_id and guild_id:
            self.add_item(HistoryButton(user_id, guild_id))


class TicketClosedView(discord.ui.View):
    """Persistent view for closed tickets (reopen only)."""

    def __init__(self, ticket_id: str):
        super().__init__(timeout=None)
        self.add_item(TicketReopenButton(ticket_id))


# =============================================================================
# Dynamic Items (Persistent Buttons)
# =============================================================================

class TicketCategoryButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_cat:(?P<category>\w+)"):
    """Persistent button for ticket category selection on panel."""

    def __init__(self, category: str):
        info = TICKET_CATEGORIES.get(category, TICKET_CATEGORIES["support"])
        super().__init__(
            discord.ui.Button(
                label=info["label"],
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_cat:{category}",
                emoji=info["emoji"],
            )
        )
        self.category = category

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "TicketCategoryButton":
        return cls(match.group("category"))

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            # Show modal for ticket details
            modal = TicketCreateModal(self.category)
            await interaction.response.send_modal(modal)
        except Exception as e:
            logger.error("Failed to show ticket modal", [
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Category", self.category),
                ("Error", str(e)),
            ])
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"Failed to open ticket form: {str(e)[:100]}",
                        ephemeral=True,
                    )
            except Exception:
                pass


class TicketClaimButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_claim:(?P<ticket_id>T\d+)"):
    """Persistent button for claiming a ticket."""

    def __init__(self, ticket_id: str):
        super().__init__(
            discord.ui.Button(
                label="Claim",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_claim:{ticket_id}",
                emoji=discord.PartialEmoji(name="approve", id=1454788180485345341),
            )
        )
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "TicketClaimButton":
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            logger.warning("Ticket claim attempted but service unavailable")
            await interaction.response.send_message("Ticket system unavailable.", ephemeral=True)
            return

        # Check permission
        if not bot.ticket_service.has_staff_permission(interaction.user):
            logger.tree("Ticket Claim Denied", [
                ("Ticket ID", self.ticket_id),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Reason", "No permission"),
            ], emoji="🚫")
            await interaction.response.send_message(
                "You don't have permission to manage tickets.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        success, message = await bot.ticket_service.claim_ticket(self.ticket_id, interaction.user)
        if success:
            # Log to webhook
            ticket = bot.ticket_service.db.get_ticket(self.ticket_id)
            if ticket and hasattr(bot, "interaction_logger") and bot.interaction_logger:
                try:
                    user = await bot.fetch_user(ticket["user_id"])
                    await bot.interaction_logger.log_ticket_claimed(interaction.user, self.ticket_id, user)
                except Exception:
                    pass
        else:
            logger.tree("Ticket Claim Failed", [
                ("Ticket ID", self.ticket_id),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Reason", message),
            ], emoji="❌")
        await interaction.followup.send(message, ephemeral=True)


class TicketCloseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_close:(?P<ticket_id>T\d+)"):
    """Persistent button for closing a ticket."""

    def __init__(self, ticket_id: str):
        super().__init__(
            discord.ui.Button(
                label="Close",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_close:{ticket_id}",
                emoji=discord.PartialEmoji(name="lock", id=1455197454277546055),
            )
        )
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "TicketCloseButton":
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            logger.warning("Ticket close attempted but service unavailable")
            await interaction.response.send_message("Ticket system unavailable.", ephemeral=True)
            return

        # Check permission
        if not bot.ticket_service.has_staff_permission(interaction.user):
            logger.tree("Ticket Close Denied", [
                ("Ticket ID", self.ticket_id),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Reason", "No permission"),
            ], emoji="🚫")
            await interaction.response.send_message(
                "You don't have permission to manage tickets.",
                ephemeral=True,
            )
            return

        # Show modal for close reason
        modal = TicketCloseModal(self.ticket_id)
        await interaction.response.send_modal(modal)


class TicketReopenButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_reopen:(?P<ticket_id>T\d+)"):
    """Persistent button for reopening a closed ticket."""

    def __init__(self, ticket_id: str):
        super().__init__(
            discord.ui.Button(
                label="Reopen",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_reopen:{ticket_id}",
                emoji=discord.PartialEmoji(name="unlock", id=1455200891866190040),
            )
        )
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "TicketReopenButton":
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            logger.warning("Ticket reopen attempted but service unavailable")
            await interaction.response.send_message("Ticket system unavailable.", ephemeral=True)
            return

        # Check permission
        if not bot.ticket_service.has_staff_permission(interaction.user):
            logger.tree("Ticket Reopen Denied", [
                ("Ticket ID", self.ticket_id),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Reason", "No permission"),
            ], emoji="🚫")
            await interaction.response.send_message(
                "You don't have permission to manage tickets.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        success, message = await bot.ticket_service.reopen_ticket(self.ticket_id, interaction.user)
        if success:
            # Log to webhook
            ticket = bot.ticket_service.db.get_ticket(self.ticket_id)
            if ticket and hasattr(bot, "interaction_logger") and bot.interaction_logger:
                try:
                    user = await bot.fetch_user(ticket["user_id"])
                    await bot.interaction_logger.log_ticket_reopened(interaction.user, self.ticket_id, user)
                except Exception:
                    pass
        else:
            logger.tree("Ticket Reopen Failed", [
                ("Ticket ID", self.ticket_id),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Reason", message),
            ], emoji="❌")
        await interaction.followup.send(message, ephemeral=True)


class TicketAddUserButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_adduser:(?P<ticket_id>T\d+)"):
    """Persistent button for adding a user to a ticket thread."""

    def __init__(self, ticket_id: str):
        super().__init__(
            discord.ui.Button(
                label="Add User",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_adduser:{ticket_id}",
                emoji=discord.PartialEmoji(name="extend", id=1452963975150174410),
            )
        )
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "TicketAddUserButton":
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            logger.warning("Ticket add user attempted but service unavailable")
            await interaction.response.send_message("Ticket system unavailable.", ephemeral=True)
            return

        # Check permission
        if not bot.ticket_service.has_staff_permission(interaction.user):
            logger.tree("Ticket Add User Denied", [
                ("Ticket ID", self.ticket_id),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Reason", "No permission"),
            ], emoji="🚫")
            await interaction.response.send_message(
                "You don't have permission to manage tickets.",
                ephemeral=True,
            )
            return

        # Show modal for user input
        modal = TicketAddUserModal(self.ticket_id)
        await interaction.response.send_modal(modal)


class TicketTranscriptButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_transcript:(?P<ticket_id>T\d+)"):
    """Persistent button for generating a ticket transcript."""

    def __init__(self, ticket_id: str):
        super().__init__(
            discord.ui.Button(
                label="Transcript",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_transcript:{ticket_id}",
                emoji=discord.PartialEmoji(name="history", id=1452963786427469894),
            )
        )
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "TicketTranscriptButton":
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            logger.warning("Ticket transcript attempted but service unavailable")
            await interaction.response.send_message("Ticket system unavailable.", ephemeral=True)
            return

        # Check permission
        if not bot.ticket_service.has_staff_permission(interaction.user):
            logger.tree("Ticket Transcript Denied", [
                ("Ticket ID", self.ticket_id),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Reason", "No permission"),
            ], emoji="🚫")
            await interaction.response.send_message(
                "You don't have permission to manage tickets.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Get ticket
        ticket = bot.ticket_service.db.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.followup.send("Ticket not found.", ephemeral=True)
            return

        # Get thread and collect messages
        thread = await bot.ticket_service._get_ticket_thread(ticket["thread_id"])
        if not thread:
            await interaction.followup.send("Ticket thread not found.", ephemeral=True)
            return

        # Collect transcript
        transcript_messages = []
        try:
            async for message in thread.history(limit=500, oldest_first=True):
                # Skip the initial embed message
                if message.embeds and not message.content:
                    continue
                transcript_messages.append({
                    "author": str(message.author),
                    "author_id": str(message.author.id),
                    "content": message.content,
                    "timestamp": message.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "attachments": [att.url for att in message.attachments],
                })
        except Exception as e:
            logger.error("Failed to collect transcript", [("Error", str(e))])
            await interaction.followup.send(f"Failed to collect transcript: {e}", ephemeral=True)
            return

        # Get user info
        try:
            user = await bot.fetch_user(ticket["user_id"])
        except Exception:
            user = None

        # Build transcript
        import io
        from datetime import datetime
        from src.core.config import NY_TZ

        created_dt = datetime.fromtimestamp(ticket["created_at"], tz=NY_TZ)
        now_dt = datetime.now(NY_TZ)

        transcript_lines = [
            f"═══════════════════════════════════════════════════════════════",
            f"TICKET TRANSCRIPT: {self.ticket_id}",
            f"═══════════════════════════════════════════════════════════════",
            f"Category: {ticket['category'].title()}",
            f"Subject: {ticket['subject']}",
            f"Opened By: {user} ({ticket['user_id']})" if user else f"Opened By: {ticket['user_id']}",
            f"Status: {ticket['status'].title()}",
            f"Created: {created_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"Generated: {now_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"Total Messages: {len(transcript_messages)}",
            f"═══════════════════════════════════════════════════════════════",
            f"",
        ]

        for msg in transcript_messages:
            author = msg.get("author", "Unknown")
            author_id = msg.get("author_id", "0")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")
            attachments = msg.get("attachments", [])

            transcript_lines.append(f"[{timestamp}] {author} ({author_id}):")
            if content:
                transcript_lines.append(f"  {content}")
            for att in attachments:
                transcript_lines.append(f"  📎 Attachment: {att}")
            transcript_lines.append("")

        transcript_lines.append("═══════════════════════════════════════════════════════════════")
        transcript_lines.append("END OF TRANSCRIPT")
        transcript_lines.append("═══════════════════════════════════════════════════════════════")

        transcript_text = "\n".join(transcript_lines)
        transcript_file = discord.File(
            io.BytesIO(transcript_text.encode("utf-8")),
            filename=f"transcript_{self.ticket_id}.txt",
        )

        logger.tree("Ticket Transcript Generated", [
            ("Ticket ID", self.ticket_id),
            ("Generated By", f"{interaction.user} ({interaction.user.id})"),
            ("Messages", str(len(transcript_messages))),
        ], emoji="📜")

        # Log to webhook
        if hasattr(bot, "interaction_logger") and bot.interaction_logger:
            await bot.interaction_logger.log_ticket_transcript(interaction.user, self.ticket_id)

        await interaction.followup.send(
            f"📜 Transcript for **{self.ticket_id}** ({len(transcript_messages)} messages):",
            file=transcript_file,
            ephemeral=True,
        )


# =============================================================================
# Modals
# =============================================================================

class TicketCreateModal(discord.ui.Modal, title="Create Ticket"):
    """Modal for creating a new ticket."""

    def __init__(self, category: str):
        super().__init__()
        self.category = category

        cat_info = TICKET_CATEGORIES.get(category, TICKET_CATEGORIES["support"])

        self.subject = discord.ui.TextInput(
            label="Subject",
            style=discord.TextStyle.short,
            placeholder=f"Brief summary of your {cat_info['label'].lower()} request...",
            required=True,
            min_length=1,
            max_length=100,
        )
        self.add_item(self.subject)

        self.description = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            placeholder="Describe your issue or request in detail...",
            required=True,
            min_length=1,
            max_length=1000,
        )
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        logger.info(f"Ticket modal submitted by {interaction.user} for category {self.category}")
        try:
            logger.info("Deferring interaction response...")
            await interaction.response.defer(ephemeral=True)
            logger.info("Response deferred successfully")

            bot = interaction.client
            if not hasattr(bot, "ticket_service") or not bot.ticket_service:
                await interaction.followup.send(
                    "Ticket system is not available.",
                    ephemeral=True,
                )
                return

            success, message, ticket_id = await bot.ticket_service.create_ticket(
                user=interaction.user,
                category=self.category,
                subject=self.subject.value,
                description=self.description.value,
            )

            if success:
                # Log to webhook
                if hasattr(bot, "interaction_logger") and bot.interaction_logger and ticket_id:
                    # Get the ticket to get thread_id
                    ticket = bot.ticket_service.db.get_ticket(ticket_id)
                    thread_id = ticket["thread_id"] if ticket else 0
                    guild_id = interaction.guild.id if interaction.guild else 0
                    await bot.interaction_logger.log_ticket_created(
                        interaction.user, ticket_id, self.category, self.subject.value,
                        thread_id, guild_id
                    )
                await interaction.followup.send(f"✅ {message}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {message}", ephemeral=True)
        except Exception as e:
            logger.error("Ticket Creation Modal Failed", [
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Category", self.category),
                ("Error", str(e)),
            ])
            try:
                await interaction.followup.send(
                    f"❌ An error occurred while creating your ticket: {str(e)[:100]}",
                    ephemeral=True,
                )
            except Exception:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error("Ticket Modal Error", [
            ("User", f"{interaction.user} ({interaction.user.id})"),
            ("Error", str(error)),
        ])
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ An error occurred: {str(error)[:100]}",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"❌ An error occurred: {str(error)[:100]}",
                    ephemeral=True,
                )
        except Exception:
            pass


class TicketCloseModal(discord.ui.Modal, title="Close Ticket"):
    """Modal for closing a ticket with a reason."""

    def __init__(self, ticket_id: str):
        super().__init__()
        self.ticket_id = ticket_id

        self.reason = discord.ui.TextInput(
            label="Close Reason",
            style=discord.TextStyle.paragraph,
            placeholder="Why is this ticket being closed? (optional)",
            required=False,
            max_length=500,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        bot = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.followup.send(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Get ticket info before closing
        ticket = bot.ticket_service.db.get_ticket(self.ticket_id)
        ticket_user = None
        if ticket:
            try:
                ticket_user = await bot.fetch_user(ticket["user_id"])
            except Exception:
                pass

        success, message = await bot.ticket_service.close_ticket(
            ticket_id=self.ticket_id,
            closed_by=interaction.user,
            reason=self.reason.value or None,
        )

        if success:
            # Log to webhook
            if ticket_user and hasattr(bot, "interaction_logger") and bot.interaction_logger:
                await bot.interaction_logger.log_ticket_closed(
                    interaction.user, self.ticket_id, ticket_user, self.reason.value
                )
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


class TicketAddUserModal(discord.ui.Modal, title="Add User to Ticket"):
    """Modal for adding a user to a ticket thread."""

    def __init__(self, ticket_id: str):
        super().__init__()
        self.ticket_id = ticket_id

        self.user_input = discord.ui.TextInput(
            label="User ID or @Mention",
            style=discord.TextStyle.short,
            placeholder="Enter user ID (e.g., 123456789) or @mention",
            required=True,
            min_length=1,
            max_length=100,
        )
        self.add_item(self.user_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        bot = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.followup.send(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        # Parse user ID from input (handles raw ID or mention)
        user_input = self.user_input.value.strip()

        # Extract ID from mention format <@123456789> or <@!123456789>
        mention_match = re.match(r"<@!?(\d+)>", user_input)
        if mention_match:
            user_id = int(mention_match.group(1))
        elif user_input.isdigit():
            user_id = int(user_input)
        else:
            logger.tree("Ticket Add User Failed", [
                ("Ticket ID", self.ticket_id),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Input", user_input[:50]),
                ("Reason", "Invalid user format"),
            ], emoji="❌")
            await interaction.followup.send(
                "❌ Invalid user. Please enter a user ID or @mention.",
                ephemeral=True,
            )
            return

        success, message = await bot.ticket_service.add_user_to_ticket(
            ticket_id=self.ticket_id,
            user_id=user_id,
            added_by=interaction.user,
        )

        if success:
            # Log to webhook
            if hasattr(bot, "interaction_logger") and bot.interaction_logger:
                try:
                    added_user = await bot.fetch_user(user_id)
                    await bot.interaction_logger.log_ticket_user_added(
                        interaction.user, self.ticket_id, added_user
                    )
                except Exception:
                    pass
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        else:
            logger.tree("Ticket Add User Failed", [
                ("Ticket ID", self.ticket_id),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Target User ID", str(user_id)),
                ("Reason", message),
            ], emoji="❌")
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


# =============================================================================
# Setup Function (for persistent views)
# =============================================================================

def setup_ticket_views(bot: "AzabBot") -> None:
    """Register ticket dynamic items for persistence."""
    bot.add_dynamic_items(
        TicketCategoryButton,
        TicketClaimButton,
        TicketCloseButton,
        TicketReopenButton,
        TicketAddUserButton,
        TicketTranscriptButton,
    )
    logger.debug("Ticket Views Registered")


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "TicketService",
    "setup_ticket_views",
    "TicketPanelView",
    "TicketActionView",
    "TicketClosedView",
    "TICKET_CATEGORIES",
]
