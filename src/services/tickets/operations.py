"""
AzabBot - Operations Mixin
==========================

Core ticket operations: create, close, reopen, claim, transfer, etc.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import TYPE_CHECKING, Optional, Tuple

import discord

from src.core.logger import logger
from src.core.constants import TICKET_CATEGORY_COOLDOWN, CLOSE_REQUEST_COOLDOWN
from src.utils.retry import safe_send

from .constants import TICKET_CATEGORIES, MAX_OPEN_TICKETS_PER_USER, TRANSCRIPT_EMOJI
from .embeds import (
    build_welcome_embed,
    build_claim_notification,
    build_close_notification,
    build_reopen_notification,
    build_user_added_notification,
    build_transfer_notification,
    build_close_request_embed,
    build_ticket_closed_dm,
    build_ticket_claimed_dm,
    build_control_panel_embed,
)
from .views import TicketControlPanelView, CloseRequestView
from .buttons import UserAddedView, TransferNotificationView
from .transcript import (
    collect_transcript_messages,
    generate_html_transcript,
    create_transcript_file,
    build_json_transcript,
)

if TYPE_CHECKING:
    from .service import TicketService


class OperationsMixin:
    """Mixin for core ticket operations."""

    # =========================================================================
    # Create Ticket
    # =========================================================================

    async def create_ticket(
        self: "TicketService",
        user: discord.Member,
        category: str,
        subject: str,
        description: str,
        case_id: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Create a new support ticket.

        Args:
            user: The user creating the ticket.
            category: Ticket category.
            subject: Ticket subject.
            description: Ticket description.
            case_id: Optional case ID (for appeal tickets).

        Returns:
            Tuple of (success, message, ticket_id).
        """
        if not self.enabled:
            return (False, "Ticket system is not enabled.", None)

        # Check per-category cooldown (skip for staff)
        # Cooldown starts when a ticket is CLOSED, not when created.
        # This prevents trolls from spamming tickets while allowing users
        # to open new tickets after their issues are resolved.
        if not self.has_staff_permission(user):
            now = time.time()
            last_closed_time = self.db.get_user_last_closed_ticket_by_category(
                user.id, user.guild.id, category
            )
            if last_closed_time:
                remaining = TICKET_CATEGORY_COOLDOWN - (now - last_closed_time)
                if remaining > 0:
                    hours = int(remaining // 3600)
                    mins = int((remaining % 3600) // 60)
                    cat_info = TICKET_CATEGORIES.get(category, TICKET_CATEGORIES["support"])
                    if hours > 0:
                        time_str = f"{hours}h {mins}m"
                    else:
                        time_str = f"{mins}m"
                    logger.tree("Ticket Creation Blocked (Category Cooldown)", [
                        ("User", f"{user.name} ({user.id})"),
                        ("Category", cat_info["label"]),
                        ("Remaining", time_str),
                        ("Last Closed", f"{int((now - last_closed_time) // 3600)}h ago"),
                    ], emoji="⏳")
                    return (
                        False,
                        f"You can only open one {cat_info['label'].lower()} ticket every 24 hours. "
                        f"Please wait {time_str} before creating another {cat_info['label'].lower()} ticket.",
                        None,
                    )

        # Check open ticket limit
        open_count = self.db.get_user_open_ticket_count(user.id, user.guild.id)
        if open_count >= MAX_OPEN_TICKETS_PER_USER:
            logger.tree("Ticket Creation Blocked (Open Limit)", [
                ("User", f"{user.name} ({user.id})"),
                ("Open Tickets", str(open_count)),
                ("Max Allowed", str(MAX_OPEN_TICKETS_PER_USER)),
            ], emoji="🚫")
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

        # Get ticket category for channel creation
        category_channel = await self._get_ticket_category(user.guild)
        if not category_channel:
            return (False, "Ticket category not found.", None)

        # Generate ticket ID
        ticket_id = self.db.generate_ticket_id()

        # Create channel name (max 100 chars)
        username = user.display_name[:20]
        cat_info = TICKET_CATEGORIES.get(category, TICKET_CATEGORIES["support"])
        channel_name = f"{ticket_id}-{cat_info['label'].lower()}-{username}".replace(" ", "-")
        if len(channel_name) > 100:
            channel_name = channel_name[:97] + "..."

        # Create channel topic with Discord timestamp
        created_timestamp = int(time.time())
        channel_topic = f"Created: <t:{created_timestamp}:f> • {cat_info['label']} ticket by {user.display_name}"

        try:
            # Build permission overwrites (person-specific only, no role-based)
            overwrites = {
                # @everyone - hidden by default
                user.guild.default_role: discord.PermissionOverwrite(
                    view_channel=False,
                ),
                # Ticket creator - can view and send messages, no reactions
                user: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True,
                    add_reactions=False,
                ),
                # Bot - full permissions
                user.guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_channels=True,
                    manage_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True,
                    add_reactions=True,
                ),
            }

            # Create the ticket channel
            ticket_channel = await user.guild.create_text_channel(
                name=channel_name,
                category=category_channel,
                overwrites=overwrites,
                topic=channel_topic,
                reason=f"Ticket {ticket_id} created by {user.name}",
            )

            # Save to database first (needed for control panel)
            # Note: thread_id field stores channel ID for backward compatibility
            self.db.create_ticket(
                ticket_id=ticket_id,
                user_id=user.id,
                guild_id=user.guild.id,
                thread_id=ticket_channel.id,
                category=category,
                subject=subject,
                case_id=case_id,
            )

            # Build and send control panel
            ticket_data = self.db.get_ticket(ticket_id)
            user_ticket_count = self.db.get_user_ticket_count(user.id, user.guild.id)
            control_embed = build_control_panel_embed(ticket_data, user, user_ticket_count=user_ticket_count)
            control_view = TicketControlPanelView.from_ticket(ticket_data)
            control_msg = await ticket_channel.send(embed=control_embed, view=control_view)

            # Save control panel message ID
            self.db.set_control_panel_message(ticket_id, control_msg.id)

            # Add permissions for assigned staff
            assigned_user_id = None
            if category == "partnership" and self.config.ticket_partnership_user_id:
                assigned_text = f"This ticket has been assigned to <@{self.config.ticket_partnership_user_id}>."
                ping_content = f"<@{self.config.ticket_partnership_user_id}>"
                assigned_user_id = self.config.ticket_partnership_user_id
            elif category == "suggestion" and self.config.ticket_suggestion_user_id:
                assigned_text = f"This ticket has been assigned to <@{self.config.ticket_suggestion_user_id}>."
                ping_content = f"<@{self.config.ticket_suggestion_user_id}>"
                assigned_user_id = self.config.ticket_suggestion_user_id
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
                # Add permissions for all support users
                for uid in self.config.ticket_support_user_ids:
                    try:
                        support_member = user.guild.get_member(uid)
                        if support_member:
                            await ticket_channel.set_permissions(
                                support_member,
                                view_channel=True,
                                send_messages=True,
                                manage_messages=True,
                                attach_files=True,
                                embed_links=True,
                                read_message_history=True,
                                add_reactions=True,
                            )
                    except discord.HTTPException as e:
                        logger.warning("Failed to add support user permissions", [
                            ("Ticket ID", ticket_id),
                            ("User ID", str(uid)),
                            ("Error", str(e)),
                        ])
            else:
                assigned_text = "A staff member will be with you shortly."
                ping_content = None

            # Add permission for specifically assigned user (partnership/suggestion)
            if assigned_user_id:
                try:
                    assigned_member = user.guild.get_member(assigned_user_id)
                    if assigned_member:
                        await ticket_channel.set_permissions(
                            assigned_member,
                            view_channel=True,
                            send_messages=True,
                            manage_messages=True,
                            attach_files=True,
                            embed_links=True,
                            read_message_history=True,
                            add_reactions=True,
                        )
                except discord.HTTPException as e:
                    logger.warning("Failed to add assigned user permissions", [
                        ("Ticket ID", ticket_id),
                        ("User ID", str(assigned_user_id)),
                        ("Error", str(e)),
                    ])

            # Get estimated wait time
            wait_time_text = self._get_estimated_wait_time(user.guild.id, ticket_id)

            # Try AI-powered greeting first
            ai_greeting = None
            if hasattr(self.bot, "ai_service") and self.bot.ai_service and self.bot.ai_service.enabled:
                ai_greeting = await self.bot.ai_service.generate_ticket_greeting(
                    ticket_id=ticket_id,
                    category=category,
                    subject=subject,
                    description=description,
                )

            if ai_greeting:
                # Send AI greeting as regular message with user mention
                greeting_content = f"{user.mention}\n\n{ai_greeting}"
                if ping_content:
                    # Include staff ping if applicable
                    greeting_content = f"{ping_content}\n\n{greeting_content}"
                await ticket_channel.send(content=greeting_content)
            else:
                # Fallback to static welcome embed
                welcome_embed = build_welcome_embed(
                    user=user,
                    category=category,
                    subject=subject,
                    assigned_text=assigned_text,
                    wait_time_text=wait_time_text,
                )

                if ping_content:
                    await ticket_channel.send(content=ping_content, embed=welcome_embed)
                else:
                    await ticket_channel.send(embed=welcome_embed)

            logger.tree("Ticket Created", [
                ("Ticket ID", ticket_id),
                ("Category", category),
                ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                ("ID", str(user.id)),
                ("Channel", str(ticket_channel.id)),
            ], emoji="🎫")

            # Log to server logs
            if hasattr(self.bot, "logging_service") and self.bot.logging_service:
                await self.bot.logging_service.log_ticket_created(
                    ticket_id=ticket_id,
                    user=user,
                    category=category,
                    subject=subject,
                    thread_id=ticket_channel.id,
                    guild_id=user.guild.id,
                )

            return (True, f"Ticket {ticket_id} created! Check {ticket_channel.mention}", ticket_id)

        except discord.HTTPException as e:
            logger.error("Ticket Creation Failed", [
                ("Error", str(e)),
                ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                ("ID", str(user.id)),
            ])
            return (False, f"Failed to create ticket: {e}", None)

    # =========================================================================
    # Close Ticket
    # =========================================================================

    async def close_ticket(
        self: "TicketService",
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

        # Clear claim reminder cooldowns (no longer needed)
        await self.clear_claim_reminder_cooldowns(ticket_id)

        # End AI conversation (ticket is closing)
        if hasattr(self.bot, "ai_service") and self.bot.ai_service:
            await self.bot.ai_service.end_conversation(ticket_id)

        # Fetch ticket user
        try:
            ticket_user = await self.bot.fetch_user(ticket["user_id"])
        except Exception:
            ticket_user = None

        # Fetch claimed_by member if available
        claimed_by_member = None
        if ticket.get("claimed_by") and closed_by.guild:
            try:
                claimed_by_member = closed_by.guild.get_member(ticket["claimed_by"])
                if not claimed_by_member:
                    claimed_by_member = await closed_by.guild.fetch_member(ticket["claimed_by"])
            except Exception:
                pass

        # Get ticket channel
        channel = await self._get_ticket_channel(ticket["thread_id"])
        transcript_messages = []
        mention_map = {}

        if channel:
            # Collect transcript with mention map
            transcript_messages, mention_map = await collect_transcript_messages(channel, self.bot)

            # Save transcript to database (both HTML and JSON)
            if transcript_messages and ticket_user:
                try:
                    # Save HTML transcript
                    html_content = generate_html_transcript(
                        ticket=ticket,
                        messages=transcript_messages,
                        user=ticket_user,
                        closed_by=closed_by,
                        mention_map=mention_map,
                    )
                    self.db.save_ticket_transcript(ticket_id, html_content)

                    # Build and save JSON transcript for web viewer
                    json_transcript = await build_json_transcript(
                        thread=channel,
                        ticket=ticket,
                        bot=self.bot,
                        user=ticket_user,
                        claimed_by=claimed_by_member,
                        closed_by=closed_by,
                    )
                    if json_transcript:
                        self.db.save_ticket_transcript_json(ticket_id, json_transcript.to_json())

                    logger.tree("Transcript Saved", [
                        ("Ticket ID", ticket_id),
                        ("Messages", str(len(transcript_messages))),
                        ("JSON", "Yes" if json_transcript else "No"),
                    ], emoji="📜")
                except Exception as e:
                    logger.error("Failed to save transcript", [("Error", str(e))])

            # Update control panel embed with closed_by for thumbnail
            await self._update_control_panel(ticket_id, channel, closed_by, ticket_user=ticket_user)

            # Revoke send_messages for ticket opener and any added users
            await self._lock_ticket_on_close(channel, ticket, closed_by.guild)

            # Get staff stats (after close, so count includes this ticket)
            staff_stats = self.db.get_staff_ticket_stats(closed_by.id, closed_by.guild.id)

            # Send close notification with staff stats and ping ticket owner
            close_embed = build_close_notification(closed_by, reason, stats=staff_stats)
            close_content = f"<@{ticket['user_id']}>" if ticket.get("user_id") else None
            await safe_send(channel, content=close_content, embed=close_embed)

            # Schedule channel deletion (no archive/lock for text channels)
            await self._schedule_channel_deletion(ticket_id, channel.id)

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
                    logger.tree("Ticket Transcript Logged", [
                        ("Ticket ID", ticket_id),
                        ("User", ticket_user.name),
                        ("Closed By", closed_by.name),
                    ], emoji="📜")
            except Exception as e:
                logger.error("Failed to log ticket close", [("Error", str(e))])

        return (True, f"Ticket {ticket_id} closed.")

    # =========================================================================
    # Reopen Ticket
    # =========================================================================

    async def reopen_ticket(
        self: "TicketService",
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
        await self._cancel_channel_deletion(ticket_id)

        # Get ticket user for control panel and logging
        try:
            ticket_user = await self.bot.fetch_user(ticket["user_id"])
        except Exception:
            ticket_user = None

        # Get ticket channel
        channel = await self._get_ticket_channel(ticket["thread_id"])
        if channel:
            # Restore staff access (ticket is now unclaimed)
            await self._restore_staff_access(channel, ticket_id, ticket)

            # Update control panel
            await self._update_control_panel(ticket_id, channel, ticket_user=ticket_user)

            # Get staff stats
            staff_stats = self.db.get_staff_ticket_stats(reopened_by.id, reopened_by.guild.id)

            # Send reopen notification with staff stats
            reopen_embed = build_reopen_notification(reopened_by, stats=staff_stats)
            await safe_send(channel, embed=reopen_embed)

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

    # =========================================================================
    # Claim Ticket
    # =========================================================================

    async def claim_ticket(
        self: "TicketService",
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

        # Clear claim reminder cooldowns (no longer needed)
        await self.clear_claim_reminder_cooldowns(ticket_id)

        # Generate AI summary before ending conversation (for staff)
        ai_summary = None
        if hasattr(self.bot, "ai_service") and self.bot.ai_service and self.bot.ai_service.enabled:
            ai_summary = await self.bot.ai_service.generate_ticket_summary(ticket_id)
            # End AI conversation (staff is taking over)
            await self.bot.ai_service.end_conversation(ticket_id)

        # Get ticket user for notification and control panel
        try:
            ticket_user = await self.bot.fetch_user(ticket["user_id"])
        except Exception:
            ticket_user = None

        channel = await self._get_ticket_channel(ticket["thread_id"])
        if channel:
            # Add claimer permissions to channel (staff can react)
            try:
                await channel.set_permissions(
                    staff,
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True,
                    add_reactions=True,
                )
            except discord.HTTPException as e:
                logger.warning("Failed to add staff permissions on claim", [
                    ("Ticket ID", ticket_id),
                    ("Staff ID", str(staff.id)),
                    ("Error", str(e)),
                ])

            # Lock out other staff (can view but not send)
            await self._lock_out_other_staff(channel, staff, ticket_id, ticket)

            # Update control panel
            await self._update_control_panel(ticket_id, channel, ticket_user=ticket_user)

            # Get staff ticket stats
            staff_stats = self.db.get_staff_ticket_stats(staff.id, staff.guild.id)

            # Send claim notification with user ping outside embed
            claim_embed = build_claim_notification(staff, stats=staff_stats)
            if ticket_user:
                await safe_send(channel, content=ticket_user.mention, embed=claim_embed)
            else:
                await safe_send(channel, embed=claim_embed)

            # Send AI summary for staff (if available) - ping the mod with a human summary
            if ai_summary:
                summary_content = f"{staff.mention} {ai_summary}"
                await safe_send(channel, content=summary_content)
                logger.tree("AI Summary Sent", [
                    ("Ticket ID", ticket_id),
                    ("Staff", f"{staff.name} ({staff.id})"),
                ], emoji="🤖")

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

    # =========================================================================
    # Add User to Ticket
    # =========================================================================

    async def add_user_to_ticket(
        self: "TicketService",
        ticket_id: str,
        user: discord.Member,
        added_by: discord.Member,
        ticket: Optional[dict] = None,
    ) -> Tuple[bool, str]:
        """Add a user to a ticket channel via permission overwrite."""
        if ticket is None:
            ticket = self.db.get_ticket(ticket_id)
        if not ticket:
            return (False, "Ticket not found.")

        if ticket["status"] == "closed":
            return (False, "Cannot add users to a closed ticket.")

        # Get ticket channel
        channel = await self._get_ticket_channel(ticket["thread_id"])
        if not channel:
            return (False, "Ticket channel not found.")

        # Add user permissions to channel (no reactions for regular users)
        try:
            await channel.set_permissions(
                user,
                view_channel=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                read_message_history=True,
                add_reactions=False,
            )
        except discord.HTTPException as e:
            return (False, f"Failed to add user: {e}")

        # Send notification with remove button
        add_embed = build_user_added_notification(added_by, user)
        add_view = UserAddedView(ticket_id, user.id)
        await safe_send(channel, embed=add_embed, view=add_view)

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
                    thread_id=channel.id,
                    guild_id=added_by.guild.id,
                )
            except Exception as e:
                logger.error("Failed to log user added", [("Error", str(e))])

        return (True, f"Added {user.mention} to the ticket.")

    # =========================================================================
    # Transfer Ticket
    # =========================================================================

    async def transfer_ticket(
        self: "TicketService",
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

        # Get ticket channel
        channel = await self._get_ticket_channel(ticket["thread_id"])
        if channel:
            # Add new staff permissions to channel
            try:
                await channel.set_permissions(
                    new_staff,
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True,
                )
            except discord.HTTPException as e:
                logger.warning("Failed to add staff permissions on transfer", [
                    ("Ticket ID", ticket_id),
                    ("New Staff ID", str(new_staff.id)),
                    ("Error", str(e)),
                ])

            # Lock out other staff (including old claimer)
            await self._lock_out_other_staff(channel, new_staff, ticket_id, ticket)

            # Lock out the old claimer specifically (if they're not in support users list)
            if original_claimer_id and original_claimer_id != new_staff.id:
                try:
                    old_claimer = transferred_by.guild.get_member(original_claimer_id)
                    if old_claimer:
                        await channel.set_permissions(
                            old_claimer,
                            view_channel=True,
                            send_messages=False,
                            attach_files=False,
                            embed_links=False,
                            read_message_history=True,
                        )
                except discord.HTTPException as e:
                    logger.warning("Failed to lock out old claimer on transfer", [
                        ("Ticket ID", ticket_id),
                        ("Old Claimer ID", str(original_claimer_id)),
                        ("Error", str(e)),
                    ])

            # Update control panel
            await self._update_control_panel(ticket_id, channel, ticket_user=ticket_user)

            # Get new staff stats
            new_staff_stats = self.db.get_staff_ticket_stats(new_staff.id, new_staff.guild.id)

            # Send transfer notification with new staff ping, stats, and revert button
            transfer_embed = build_transfer_notification(new_staff, transferred_by, stats=new_staff_stats)
            if original_claimer_id:
                transfer_view = TransferNotificationView(ticket_id, original_claimer_id)
                await safe_send(channel, content=new_staff.mention, embed=transfer_embed, view=transfer_view)
            else:
                await safe_send(channel, content=new_staff.mention, embed=transfer_embed)

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

    # =========================================================================
    # Request Close
    # =========================================================================

    async def request_close(
        self: "TicketService",
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

        # Get ticket channel
        channel = await self._get_ticket_channel(ticket["thread_id"])
        if not channel:
            return (False, "Ticket channel not found.")

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
        await channel.send(content=ping_content, embed=request_embed, view=request_view)

        return (True, "Close request sent. A staff member will review it.")

    # =========================================================================
    # Generate Transcript
    # =========================================================================

    async def generate_transcript(
        self: "TicketService",
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
        channel = await self._get_ticket_channel(ticket["thread_id"])
        if not channel:
            return (False, "Ticket channel not found.", None)

        try:
            ticket_user = await self.bot.fetch_user(ticket["user_id"])
        except Exception:
            return (False, "Could not fetch ticket user.", None)

        messages, mention_map = await collect_transcript_messages(channel, self.bot)
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


__all__ = ["OperationsMixin"]
