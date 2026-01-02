"""
Ticket Service
==============

Core service logic for the ticket system.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict, Tuple

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.core.constants import (
    TICKET_CREATION_COOLDOWN,
    AUTO_CLOSE_CHECK_INTERVAL,
    THREAD_DELETE_DELAY,
    CLOSE_REQUEST_COOLDOWN,
)
from src.utils.footer import set_footer
from src.utils.retry import safe_fetch_channel, safe_send
from src.utils.async_utils import create_safe_task

from .constants import (
    TICKET_CATEGORIES,
    MAX_OPEN_TICKETS_PER_USER,
    INACTIVE_WARNING_DAYS,
    INACTIVE_CLOSE_DAYS,
    DELETE_AFTER_CLOSE_DAYS,
    TRANSCRIPT_EMOJI,
)
from .embeds import (
    build_control_panel_embed,
    build_welcome_embed,
    build_claim_notification,
    build_close_notification,
    build_reopen_notification,
    build_user_added_notification,
    build_transfer_notification,
    build_inactivity_warning,
    build_close_request_embed,
    build_ticket_closed_dm,
    build_ticket_claimed_dm,
    build_panel_embed,
)
from .views import (
    TicketPanelView,
    TicketControlPanelView,
    CloseRequestView,
)
from .buttons import UserAddedView, TransferNotificationView
from .transcript import (
    collect_transcript_messages,
    generate_html_transcript,
    create_transcript_file,
)

if TYPE_CHECKING:
    from src.bot import AzabBot


class TicketService:
    """
    Service for managing support tickets.

    DESIGN:
        Tickets are created as threads in a dedicated text channel.
        Each ticket gets its own thread with sequential ID (T001, T002, etc.).
        All operations via buttons - no slash commands.

        Single Control Panel Pattern:
        - One embed per ticket that updates in place
        - Buttons change based on ticket status
        - Simple notification messages (no buttons) for actions
    """

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
        self._creation_cooldowns: Dict[int, float] = {}
        self._close_request_cooldowns: Dict[str, float] = {}
        self._pending_deletions: Dict[str, asyncio.Task] = {}
        self._cache_lookup_count: int = 0  # Counter for periodic cache cleanup
        # Locks for thread-safe dict access
        self._cooldowns_lock = asyncio.Lock()
        self._deletions_lock = asyncio.Lock()

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
        logger.tree("Ticket Service Started", [
            ("Auto-close", f"Enabled (warn: {INACTIVE_WARNING_DAYS}d, close: {INACTIVE_CLOSE_DAYS}d)"),
            ("Auto-delete", f"Enabled ({DELETE_AFTER_CLOSE_DAYS}d after close)"),
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

        # Cancel pending deletions
        async with self._deletions_lock:
            for task in self._pending_deletions.values():
                if not task.done():
                    task.cancel()
            self._pending_deletions.clear()

        logger.debug("Ticket Service Stopped")

    # =========================================================================
    # Auto-close Logic
    # =========================================================================

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
        """Check and handle inactive tickets."""
        if not self.config.logging_guild_id:
            return

        guild_id = self.config.logging_guild_id
        now = time.time()
        warning_threshold = now - (INACTIVE_WARNING_DAYS * 86400)
        close_threshold = now - (INACTIVE_CLOSE_DAYS * 86400)
        delete_threshold = now - (DELETE_AFTER_CLOSE_DAYS * 86400)

        # Get tickets that need warning
        unwarned_tickets = self.db.get_unwarned_inactive_tickets(
            guild_id, warning_threshold
        )
        for ticket in unwarned_tickets:
            await self._send_inactivity_warning(ticket)

        # Get tickets that need closing
        warned_tickets = self.db.get_warned_tickets_ready_to_close(
            guild_id, close_threshold
        )
        for ticket in warned_tickets:
            await self._auto_close_ticket(ticket)

        # Get closed tickets that need deletion
        closed_tickets = self.db.get_closed_tickets_ready_to_delete(
            guild_id, delete_threshold
        )
        for ticket in closed_tickets:
            await self._auto_delete_ticket(ticket)

    async def _send_inactivity_warning(self, ticket: dict) -> None:
        """Send inactivity warning to ticket thread."""
        thread = await self._get_ticket_thread(ticket["thread_id"])
        if not thread:
            return

        days_inactive = INACTIVE_WARNING_DAYS
        days_until_close = INACTIVE_CLOSE_DAYS - INACTIVE_WARNING_DAYS

        embed = build_inactivity_warning(
            user_id=ticket["user_id"],
            days_inactive=days_inactive,
            days_until_close=days_until_close,
        )

        try:
            await thread.send(embed=embed)
            self.db.mark_ticket_warned(ticket["ticket_id"])
            logger.tree("Inactivity Warning Sent", [
                ("Ticket ID", ticket["ticket_id"]),
                ("Days Inactive", str(days_inactive)),
            ], emoji="⚠️")
        except discord.HTTPException as e:
            logger.error("Failed to send inactivity warning", [
                ("Ticket ID", ticket["ticket_id"]),
                ("Error", str(e)),
            ])

    async def _auto_close_ticket(self, ticket: dict) -> None:
        """Auto-close an inactive ticket."""
        # Use bot as closer
        guild = self.bot.get_guild(self.config.logging_guild_id)
        if not guild:
            return

        bot_member = guild.get_member(self.bot.user.id)
        if not bot_member:
            return

        success, _ = await self.close_ticket(
            ticket_id=ticket["ticket_id"],
            closed_by=bot_member,
            reason=f"Automatically closed after {INACTIVE_CLOSE_DAYS} days of inactivity",
        )

        if success:
            logger.tree("Ticket Auto-Closed", [
                ("Ticket ID", ticket["ticket_id"]),
                ("Reason", "Inactivity"),
            ], emoji="🔒")

    async def _auto_delete_ticket(self, ticket: dict) -> None:
        """Auto-delete a closed ticket thread after retention period."""
        ticket_id = ticket["ticket_id"]
        thread_id = ticket["thread_id"]

        # Delete the thread
        thread = await self._get_ticket_thread(thread_id)
        if thread:
            try:
                await thread.delete()
            except discord.NotFound:
                pass  # Already deleted
            except discord.HTTPException as e:
                logger.error("Failed to delete ticket thread", [
                    ("Ticket ID", ticket_id),
                    ("Error", str(e)),
                ])
                return

        # Delete from database
        self.db.delete_ticket(ticket_id)

        logger.tree("Ticket Auto-Deleted", [
            ("Ticket ID", ticket_id),
            ("Days After Close", str(DELETE_AFTER_CLOSE_DAYS)),
        ], emoji="🗑️")

    # =========================================================================
    # Activity Tracking
    # =========================================================================

    async def track_ticket_activity(self, thread_id: int) -> None:
        """Track activity in a ticket thread."""
        ticket = self.db.get_ticket_by_thread(thread_id)
        if not ticket:
            return

        if ticket["status"] == "closed":
            return

        self.db.update_ticket_activity(ticket["ticket_id"])

        # Clear warning flag if ticket becomes active again
        if ticket.get("warned"):
            self.db.clear_ticket_warning(ticket["ticket_id"])

    # =========================================================================
    # Channel/Thread Helpers
    # =========================================================================

    async def _get_channel(self) -> Optional[discord.TextChannel]:
        """Get the ticket channel with caching."""
        if not self.config.ticket_channel_id:
            return None

        # Check cache
        if self._channel and self._channel_cache_time:
            if datetime.now() - self._channel_cache_time < self.THREAD_CACHE_TTL:
                return self._channel

        # Fetch channel
        channel = await safe_fetch_channel(self.bot, self.config.ticket_channel_id)
        if channel and isinstance(channel, discord.TextChannel):
            self._channel = channel
            self._channel_cache_time = datetime.now()
            return channel

        return None

    async def _get_ticket_thread(self, thread_id: int) -> Optional[discord.Thread]:
        """Get a ticket thread with caching."""
        now = datetime.now()

        # Periodic cache cleanup (every 50 lookups or when cache is large)
        self._cache_lookup_count += 1
        if self._cache_lookup_count >= 50 or len(self._thread_cache) > 100:
            self._cleanup_thread_cache(now)
            self._cache_lookup_count = 0

        # Check cache
        if thread_id in self._thread_cache:
            thread, cached_at = self._thread_cache[thread_id]
            if now - cached_at < self.THREAD_CACHE_TTL:
                return thread
            # Expired entry, remove it
            self._thread_cache.pop(thread_id, None)

        # Fetch thread
        try:
            thread = await self.bot.fetch_channel(thread_id)
            if isinstance(thread, discord.Thread):
                self._thread_cache[thread_id] = (thread, now)
                return thread
        except discord.NotFound:
            # Thread deleted, remove from cache
            self._thread_cache.pop(thread_id, None)
        except discord.HTTPException:
            pass

        return None

    def _cleanup_thread_cache(self, now: Optional[datetime] = None) -> None:
        """Remove expired entries from thread cache."""
        if now is None:
            now = datetime.now()

        expired_keys = [
            thread_id for thread_id, (_, cached_at) in self._thread_cache.items()
            if now - cached_at >= self.THREAD_CACHE_TTL
        ]
        for key in expired_keys:
            self._thread_cache.pop(key, None)

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired thread cache entries")

    def has_staff_permission(self, member: discord.Member) -> bool:
        """Check if a member has staff permissions."""
        return member.guild_permissions.manage_messages

    # =========================================================================
    # Core Ticket Operations
    # =========================================================================

    async def create_ticket(
        self,
        user: discord.Member,
        category: str,
        subject: str,
        description: str,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Create a new support ticket.

        Returns:
            Tuple of (success, message, ticket_id).
        """
        if not self.enabled:
            return (False, "Ticket system is not enabled.", None)

        # Check cooldown (skip for staff) - atomic check-and-set to prevent race condition
        if not self.has_staff_permission(user):
            async with self._cooldowns_lock:
                now = time.time()
                last_created = self._creation_cooldowns.get(user.id, 0)
                remaining = TICKET_CREATION_COOLDOWN - (now - last_created)
                if remaining > 0:
                    mins = int(remaining // 60)
                    secs = int(remaining % 60)
                    return (
                        False,
                        f"Please wait {mins}m {secs}s before creating another ticket.",
                        None,
                    )
                # Set cooldown immediately to prevent race condition
                self._creation_cooldowns[user.id] = now

        # Check open ticket limit
        open_count = self.db.get_user_open_ticket_count(user.id, user.guild.id)
        if open_count >= MAX_OPEN_TICKETS_PER_USER:
            if open_count == 1:
                return (
                    False,
                    "You already have an open ticket. Please wait for it to be resolved.",
                    None,
                )
            return (
                False,
                f"You already have {open_count} open tickets. Please wait for them to be resolved.",
                None,
            )

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

        try:
            # Create thread
            thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                auto_archive_duration=10080,  # 7 days
            )

            # Save to database first (needed for control panel)
            self.db.create_ticket(
                ticket_id=ticket_id,
                user_id=user.id,
                guild_id=user.guild.id,
                thread_id=thread.id,
                category=category,
                subject=subject,
            )

            # Build and send control panel
            ticket_data = self.db.get_ticket(ticket_id)
            control_embed = build_control_panel_embed(ticket_data, user)
            control_view = TicketControlPanelView.from_ticket(ticket_data)
            control_msg = await thread.send(embed=control_embed, view=control_view)

            # Save control panel message ID
            self.db.set_control_panel_message(ticket_id, control_msg.id)

            # Add user to thread
            await thread.add_user(user)

            # Determine who to assign
            if category == "partnership" and self.config.ticket_partnership_user_id:
                assigned_text = f"This ticket has been assigned to <@{self.config.ticket_partnership_user_id}>."
                ping_content = f"<@{self.config.ticket_partnership_user_id}>"
            elif category == "suggestion" and self.config.ticket_suggestion_user_id:
                assigned_text = f"This ticket has been assigned to <@{self.config.ticket_suggestion_user_id}>."
                ping_content = f"<@{self.config.ticket_suggestion_user_id}>"
            elif self.config.ticket_support_user_ids:
                user_mentions = " and ".join(
                    f"<@{uid}>" for uid in self.config.ticket_support_user_ids
                )
                ping_mentions = " ".join(
                    f"<@{uid}>" for uid in self.config.ticket_support_user_ids
                )
                if len(self.config.ticket_support_user_ids) > 1:
                    assigned_text = f"This ticket has been assigned to {user_mentions}.\nPlease wait for one of them to claim your ticket."
                else:
                    assigned_text = f"This ticket has been assigned to {user_mentions}."
                ping_content = ping_mentions
            else:
                assigned_text = "A staff member will be with you shortly."
                ping_content = None

            # Get estimated wait time
            wait_time_text = self._get_estimated_wait_time(user.guild.id, ticket_id)

            # Send welcome message
            welcome_embed = build_welcome_embed(
                user=user,
                category=category,
                subject=subject,
                assigned_text=assigned_text,
                wait_time_text=wait_time_text,
            )

            if ping_content:
                await thread.send(content=ping_content, embed=welcome_embed)
            else:
                await thread.send(embed=welcome_embed)

            logger.tree("Ticket Created", [
                ("Ticket ID", ticket_id),
                ("Category", category),
                ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                ("ID", str(user.id)),
                ("Thread", str(thread.id)),
            ], emoji="🎫")

            # Log to server logs
            if hasattr(self.bot, "logging_service") and self.bot.logging_service:
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
                ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                ("ID", str(user.id)),
            ])
            return (False, f"Failed to create ticket: {e}", None)

    async def close_ticket(
        self,
        ticket_id: str,
        closed_by: discord.Member,
        reason: Optional[str] = None,
        ticket: Optional[dict] = None,
    ) -> Tuple[bool, str]:
        """Close a ticket."""
        if ticket is None:
            ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.")

        if ticket["status"] == "closed":
            return (False, "Ticket is already closed.")

        # Close in database
        if not self.db.close_ticket(ticket_id, closed_by.id, reason):
            return (False, "Failed to close ticket.")

        # Fetch ticket user
        try:
            ticket_user = await self.bot.fetch_user(ticket["user_id"])
        except Exception:
            ticket_user = None

        # Get thread
        thread = await self._get_ticket_thread(ticket["thread_id"])
        transcript_messages = []
        mention_map = {}

        if thread:
            # Collect transcript with mention map
            transcript_messages, mention_map = await collect_transcript_messages(thread, self.bot)

            # Save transcript to database
            if transcript_messages and ticket_user:
                try:
                    html_content = generate_html_transcript(
                        ticket=ticket,
                        messages=transcript_messages,
                        user=ticket_user,
                        closed_by=closed_by,
                        mention_map=mention_map,
                    )
                    self.db.save_ticket_transcript(ticket_id, html_content)
                    logger.tree("Transcript Saved", [
                        ("Ticket ID", ticket_id),
                        ("Messages", str(len(transcript_messages))),
                    ], emoji="📜")
                except Exception as e:
                    logger.error("Failed to save transcript", [("Error", str(e))])

            # Update control panel embed with closed_by for thumbnail
            await self._update_control_panel(ticket_id, thread, closed_by, ticket_user=ticket_user)

            # Get staff stats (after close, so count includes this ticket)
            staff_stats = self.db.get_staff_ticket_stats(closed_by.id, closed_by.guild.id)

            # Send close notification with staff stats and ping ticket owner
            close_embed = build_close_notification(closed_by, reason, stats=staff_stats)
            close_content = f"<@{ticket['user_id']}>" if ticket.get("user_id") else None
            await safe_send(thread, content=close_content, embed=close_embed)

            # Archive and lock thread
            try:
                await thread.edit(archived=True, locked=True)
            except discord.HTTPException:
                pass

            # Schedule thread deletion
            await self._schedule_thread_deletion(ticket_id, thread.id)

        # DM the user
        if ticket_user:
            try:
                dm_embed = build_ticket_closed_dm(
                    ticket_id=ticket_id,
                    category=ticket["category"],
                    close_reason=reason,
                    closed_by=closed_by,
                    guild_name=closed_by.guild.name if closed_by.guild else "Server",
                )
                if self.config.transcript_base_url:
                    dm_view = discord.ui.View()
                    dm_view.add_item(discord.ui.Button(
                        label="Transcript",
                        style=discord.ButtonStyle.link,
                        url=f"{self.config.transcript_base_url}/{ticket_id}",
                        emoji=TRANSCRIPT_EMOJI,
                    ))
                    await ticket_user.send(embed=dm_embed, view=dm_view)
                else:
                    await ticket_user.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

        logger.tree("Ticket Closed", [
            ("Ticket ID", ticket_id),
            ("Closed By", f"{closed_by.name} ({closed_by.nick})" if hasattr(closed_by, 'nick') and closed_by.nick else closed_by.name),
            ("Staff ID", str(closed_by.id)),
            ("Reason", reason or "None"),
        ], emoji="🔒")

        # Log to server logs
        if hasattr(self.bot, "logging_service") and self.bot.logging_service:
            try:
                await self.bot.logging_service.log_ticket_closed(
                    ticket_id=ticket_id,
                    user=ticket_user,
                    closed_by=closed_by,
                    category=ticket["category"],
                    reason=reason,
                    thread_id=ticket["thread_id"],
                    guild_id=closed_by.guild.id,
                )
                if transcript_messages:
                    await self.bot.logging_service.log_ticket_transcript(
                        ticket_id=ticket_id,
                        user=ticket_user,
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
        ticket: Optional[dict] = None,
    ) -> Tuple[bool, str]:
        """Reopen a closed ticket."""
        if ticket is None:
            ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.")

        if ticket["status"] != "closed":
            return (False, "Ticket is not closed.")

        # Reopen in database
        if not self.db.reopen_ticket(ticket_id):
            return (False, "Failed to reopen ticket.")

        # Cancel pending deletion
        await self._cancel_thread_deletion(ticket_id)

        # Get ticket user for control panel and logging
        try:
            ticket_user = await self.bot.fetch_user(ticket["user_id"])
        except Exception:
            ticket_user = None

        # Get thread
        thread = await self._get_ticket_thread(ticket["thread_id"])
        if thread:
            # Unarchive and unlock
            try:
                await thread.edit(archived=False, locked=False)
            except discord.HTTPException:
                pass

            # Update control panel
            await self._update_control_panel(ticket_id, thread, ticket_user=ticket_user)

            # Get staff stats
            staff_stats = self.db.get_staff_ticket_stats(reopened_by.id, reopened_by.guild.id)

            # Send reopen notification with staff stats
            reopen_embed = build_reopen_notification(reopened_by, stats=staff_stats)
            await safe_send(thread, embed=reopen_embed)

        logger.tree("Ticket Reopened", [
            ("Ticket ID", ticket_id),
            ("Reopened By", f"{reopened_by} ({reopened_by.id})"),
        ], emoji="🔓")

        # Log to server logs
        if hasattr(self.bot, "logging_service") and self.bot.logging_service and ticket_user:
            try:
                await self.bot.logging_service.log_ticket_reopened(
                    ticket_id=ticket_id,
                    user=ticket_user,
                    reopened_by=reopened_by,
                    category=ticket["category"],
                    thread_id=ticket["thread_id"],
                    guild_id=reopened_by.guild.id,
                )
            except Exception as e:
                logger.error("Failed to log ticket reopen", [("Error", str(e))])

        return (True, f"Ticket {ticket_id} reopened.")

    async def claim_ticket(
        self,
        ticket_id: str,
        staff: discord.Member,
        ticket: Optional[dict] = None,
    ) -> Tuple[bool, str]:
        """Claim a ticket."""
        if ticket is None:
            ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.")

        if ticket["status"] == "closed":
            return (False, "Cannot claim a closed ticket.")

        if ticket["status"] == "claimed":
            if ticket["claimed_by"] == staff.id:
                return (False, "You already claimed this ticket.")
            return (False, f"This ticket is already claimed by <@{ticket['claimed_by']}>.")

        # Claim in database
        if not self.db.claim_ticket(ticket_id, staff.id):
            return (False, "Failed to claim ticket.")

        # Get ticket user for notification and control panel
        try:
            ticket_user = await self.bot.fetch_user(ticket["user_id"])
        except Exception:
            ticket_user = None

        thread = await self._get_ticket_thread(ticket["thread_id"])
        if thread:
            # Update control panel
            await self._update_control_panel(ticket_id, thread, ticket_user=ticket_user)

            # Get staff ticket stats
            staff_stats = self.db.get_staff_ticket_stats(staff.id, staff.guild.id)

            # Send claim notification with user ping outside embed
            claim_embed = build_claim_notification(staff, stats=staff_stats)
            if ticket_user:
                await safe_send(thread, content=ticket_user.mention, embed=claim_embed)
            else:
                await safe_send(thread, embed=claim_embed)

            # DM user
            if ticket_user:
                try:
                    dm_embed = build_ticket_claimed_dm(
                        ticket_id=ticket_id,
                        staff=staff,
                        guild_name=staff.guild.name if staff.guild else "Server",
                    )
                    await ticket_user.send(embed=dm_embed)
                except (discord.Forbidden, discord.HTTPException):
                    pass

        logger.tree("Ticket Claimed", [
            ("Ticket ID", ticket_id),
            ("Claimed By", f"{staff.name} ({staff.nick})" if hasattr(staff, 'nick') and staff.nick else staff.name),
            ("Staff ID", str(staff.id)),
        ], emoji="✋")

        # Log to server logs
        if hasattr(self.bot, "logging_service") and self.bot.logging_service:
            try:
                await self.bot.logging_service.log_ticket_claimed(
                    ticket_id=ticket_id,
                    user=ticket_user,
                    staff=staff,
                    category=ticket["category"],
                    thread_id=ticket["thread_id"],
                    guild_id=staff.guild.id,
                    created_at=ticket["created_at"],
                )
            except Exception as e:
                logger.error("Failed to log ticket claim", [("Error", str(e))])

        return (True, f"You claimed ticket {ticket_id}.")

    async def add_user_to_ticket(
        self,
        ticket_id: str,
        user: discord.Member,
        added_by: discord.Member,
        ticket: Optional[dict] = None,
    ) -> Tuple[bool, str]:
        """Add a user to a ticket thread."""
        if ticket is None:
            ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.")

        if ticket["status"] == "closed":
            return (False, "Cannot add users to a closed ticket.")

        # Get thread
        thread = await self._get_ticket_thread(ticket["thread_id"])
        if not thread:
            return (False, "Ticket thread not found.")

        # Add user to thread
        try:
            await thread.add_user(user)
        except discord.HTTPException as e:
            return (False, f"Failed to add user: {e}")

        # Send notification with remove button
        add_embed = build_user_added_notification(added_by, user)
        add_view = UserAddedView(ticket_id, user.id)
        await safe_send(thread, embed=add_embed, view=add_view)

        logger.tree("User Added to Ticket", [
            ("Ticket ID", ticket_id),
            ("Added User", f"{user} ({user.id})"),
            ("Added By", f"{added_by} ({added_by.id})"),
        ], emoji="👤")

        # Log to server logs
        if hasattr(self.bot, "logging_service") and self.bot.logging_service:
            try:
                ticket_user = await self.bot.fetch_user(ticket["user_id"])
                await self.bot.logging_service.log_ticket_user_added(
                    ticket_id=ticket_id,
                    ticket_user=ticket_user,
                    added_user=user,
                    added_by=added_by,
                    thread_id=thread.id,
                    guild_id=added_by.guild.id,
                )
            except Exception as e:
                logger.error("Failed to log user added", [("Error", str(e))])

        return (True, f"Added {user.mention} to the ticket.")

    async def transfer_ticket(
        self,
        ticket_id: str,
        new_staff: discord.Member,
        transferred_by: discord.Member,
        ticket: Optional[dict] = None,
    ) -> Tuple[bool, str]:
        """Transfer a ticket to another staff member."""
        if ticket is None:
            ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.")

        if ticket["status"] == "closed":
            return (False, "Cannot transfer a closed ticket.")

        # Store original claimer for revert button
        original_claimer_id = ticket.get("claimed_by")

        # Update claimed_by in database (use transfer_ticket, not claim_ticket)
        if not self.db.transfer_ticket(ticket_id, new_staff.id):
            return (False, "Failed to transfer ticket.")

        # Get ticket user for control panel and logging
        try:
            ticket_user = await self.bot.fetch_user(ticket["user_id"])
        except Exception:
            ticket_user = None

        # Get thread
        thread = await self._get_ticket_thread(ticket["thread_id"])
        if thread:
            # Add new staff to thread
            try:
                await thread.add_user(new_staff)
            except discord.HTTPException:
                pass

            # Update control panel
            await self._update_control_panel(ticket_id, thread, ticket_user=ticket_user)

            # Get new staff stats
            new_staff_stats = self.db.get_staff_ticket_stats(new_staff.id, new_staff.guild.id)

            # Send transfer notification with new staff ping, stats, and revert button
            transfer_embed = build_transfer_notification(new_staff, transferred_by, stats=new_staff_stats)
            if original_claimer_id:
                transfer_view = TransferNotificationView(ticket_id, original_claimer_id)
                await safe_send(thread, content=new_staff.mention, embed=transfer_embed, view=transfer_view)
            else:
                await safe_send(thread, content=new_staff.mention, embed=transfer_embed)

        logger.tree("Ticket Transferred", [
            ("Ticket ID", ticket_id),
            ("New Staff", f"{new_staff} ({new_staff.id})"),
            ("Transferred By", f"{transferred_by} ({transferred_by.id})"),
        ], emoji="↔️")

        # Log to server logs
        if hasattr(self.bot, "logging_service") and self.bot.logging_service and ticket_user:
            try:
                await self.bot.logging_service.log_ticket_transferred(
                    ticket_id=ticket_id,
                    ticket_user=ticket_user,
                    new_staff=new_staff,
                    transferred_by=transferred_by,
                    category=ticket["category"],
                    thread_id=ticket["thread_id"],
                    guild_id=transferred_by.guild.id,
                )
            except Exception as e:
                logger.error("Failed to log ticket transfer", [("Error", str(e))])

        return (True, f"Ticket transferred to {new_staff.mention}.")

    async def request_close(
        self,
        ticket_id: str,
        requester: discord.Member,
        ticket: Optional[dict] = None,
    ) -> Tuple[bool, str]:
        """Request to close a ticket (for ticket owner)."""
        if ticket is None:
            ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.")

        if ticket["status"] == "closed":
            return (False, "Ticket is already closed.")

        # Check cooldown - atomic check-and-set to prevent race condition
        async with self._cooldowns_lock:
            now = time.time()
            last_request = self._close_request_cooldowns.get(ticket_id, 0)
            remaining = CLOSE_REQUEST_COOLDOWN - (now - last_request)
            if remaining > 0:
                mins = int(remaining // 60)
                return (False, f"Please wait {mins} minutes before requesting again.")
            # Set cooldown immediately to prevent race condition
            self._close_request_cooldowns[ticket_id] = now

        # Get thread
        thread = await self._get_ticket_thread(ticket["thread_id"])
        if not thread:
            return (False, "Ticket thread not found.")

        # Determine who to ping
        # Priority: claimed_by > category-specific > support staff
        if ticket.get("claimed_by"):
            ping_content = f"<@{ticket['claimed_by']}>"
        else:
            category = ticket.get("category", "support")
            if category == "partnership" and self.config.ticket_partnership_user_id:
                ping_content = f"<@{self.config.ticket_partnership_user_id}>"
            elif category == "suggestion" and self.config.ticket_suggestion_user_id:
                ping_content = f"<@{self.config.ticket_suggestion_user_id}>"
            elif self.config.ticket_support_user_ids:
                ping_content = " ".join(
                    f"<@{uid}>" for uid in self.config.ticket_support_user_ids
                )
            else:
                ping_content = None

        # Send close request embed with approve/deny buttons
        request_embed = build_close_request_embed(requester)
        request_view = CloseRequestView(ticket_id)
        await thread.send(content=ping_content, embed=request_embed, view=request_view)

        return (True, "Close request sent. A staff member will review it.")

    async def generate_transcript(
        self,
        ticket_id: str,
    ) -> Tuple[bool, str, Optional[discord.File]]:
        """Generate transcript for a ticket."""
        ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.", None)

        # Try to get from database first
        saved_transcript = self.db.get_ticket_transcript(ticket_id)
        if saved_transcript:
            file = create_transcript_file(ticket_id, saved_transcript)
            return (True, "Transcript retrieved.", file)

        # Generate fresh transcript
        thread = await self._get_ticket_thread(ticket["thread_id"])
        if not thread:
            return (False, "Ticket thread not found.", None)

        try:
            ticket_user = await self.bot.fetch_user(ticket["user_id"])
        except Exception:
            return (False, "Could not fetch ticket user.", None)

        messages, mention_map = await collect_transcript_messages(thread, self.bot)
        if not messages:
            return (False, "No messages found in ticket.", None)

        html_content = generate_html_transcript(
            ticket=ticket,
            messages=messages,
            user=ticket_user,
            mention_map=mention_map,
        )

        file = create_transcript_file(ticket_id, html_content)
        return (True, "Transcript generated.", file)

    # =========================================================================
    # Control Panel Management
    # =========================================================================

    async def _update_control_panel(
        self,
        ticket_id: str,
        thread: discord.Thread,
        closed_by: Optional[discord.Member] = None,
        ticket: Optional[dict] = None,
        ticket_user: Optional[discord.User] = None,
    ) -> None:
        """Update the control panel embed in a ticket thread."""
        if ticket is None:
            ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return

        # Get ticket user if not passed
        if ticket_user is None:
            try:
                ticket_user = await self.bot.fetch_user(ticket["user_id"])
            except Exception:
                ticket_user = None

        # Get closed_by member if ticket is closed and not passed
        if ticket["status"] == "closed" and not closed_by and ticket.get("closed_by"):
            try:
                guild = thread.guild or self.bot.get_guild(self.config.logging_guild_id)
                if guild:
                    closed_by = guild.get_member(ticket["closed_by"])
            except Exception:
                pass

        # Build new embed and view
        new_embed = build_control_panel_embed(ticket, ticket_user, closed_by)
        new_view = TicketControlPanelView.from_ticket(ticket)

        # Try to edit existing control panel message
        control_msg_id = ticket.get("control_panel_message_id")
        if control_msg_id:
            try:
                message = await thread.fetch_message(control_msg_id)
                await message.edit(embed=new_embed, view=new_view)
                return
            except discord.NotFound:
                pass
            except discord.HTTPException as e:
                logger.warning(f"Failed to edit control panel: {e}")

        # Fallback: find first embed message
        try:
            async for message in thread.history(limit=5, oldest_first=True):
                if message.embeds and "Control Panel" in str(message.embeds[0].title):
                    await message.edit(embed=new_embed, view=new_view)
                    # Update stored message ID
                    self.db.set_control_panel_message(ticket_id, message.id)
                    return
        except discord.HTTPException:
            pass

    # =========================================================================
    # Panel Management
    # =========================================================================

    async def send_panel(
        self,
        channel: discord.TextChannel,
    ) -> Optional[discord.Message]:
        """Send the ticket creation panel to a channel."""
        embed = build_panel_embed()
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
    # Thread Deletion
    # =========================================================================

    async def _schedule_thread_deletion(self, ticket_id: str, thread_id: int) -> None:
        """Schedule a thread for deletion after delay."""
        await self._cancel_thread_deletion(ticket_id)

        async def delete_after_delay():
            await asyncio.sleep(THREAD_DELETE_DELAY)
            try:
                thread = await self.bot.fetch_channel(thread_id)
                if isinstance(thread, discord.Thread):
                    await thread.delete()
                    logger.debug(f"Deleted thread for ticket {ticket_id}")
            except discord.NotFound:
                pass
            except Exception as e:
                logger.error(f"Failed to delete thread: {e}")
            finally:
                async with self._deletions_lock:
                    self._pending_deletions.pop(ticket_id, None)

        task = create_safe_task(delete_after_delay(), f"Delete thread {ticket_id}")
        async with self._deletions_lock:
            self._pending_deletions[ticket_id] = task

    async def _cancel_thread_deletion(self, ticket_id: str) -> None:
        """Cancel a scheduled thread deletion."""
        async with self._deletions_lock:
            task = self._pending_deletions.pop(ticket_id, None)
        if task and not task.done():
            task.cancel()

    # =========================================================================
    # Helpers
    # =========================================================================

    def _get_estimated_wait_time(self, guild_id: int, ticket_id: str) -> str:
        """Get estimated wait time text."""
        avg_response = self.db.get_average_response_time(guild_id)
        if avg_response:
            position = self.db.get_open_ticket_position(ticket_id, guild_id)
            if position and position > 1:
                return f"\n\n*Estimated wait: ~{int(avg_response / 60)} minutes (Queue position: #{position})*"
            return f"\n\n*Average response time: ~{int(avg_response / 60)} minutes*"
        return ""
