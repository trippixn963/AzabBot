"""
AzabBot - Appeal Creation Mixin
===============================

Methods for creating new appeals.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from typing import TYPE_CHECKING, Dict, List, Optional

import discord

from src.core.logger import logger

from .constants import (
    APPEAL_COOLDOWN_SECONDS,
    MAX_APPEALS_PER_WEEK,
    APPEAL_RATE_LIMIT_SECONDS,
)

if TYPE_CHECKING:
    from .service import AppealService


class CreateMixin:
    """Mixin for appeal creation methods."""

    async def create_appeal(
        self: "AppealService",
        case_id: str,
        user: discord.User,
        reason: str,
        email: Optional[str] = None,
        attachments: Optional[List[Dict[str, str]]] = None,
    ) -> tuple[bool, str, Optional[str]]:
        """
        Create a new appeal for a case.

        Args:
            case_id: Case ID to appeal.
            user: User submitting the appeal.
            reason: User's appeal reason.
            email: Optional email for notifications.
            attachments: Optional list of attachments with name, type, and base64 data.

        Returns:
            Tuple of (success, message, appeal_id).
        """
        if not self.enabled:
            return (False, "Appeal system is not enabled", None)

        # Check eligibility (also returns case data to avoid redundant query)
        can_appeal_result, deny_reason, case = self.can_appeal(case_id)
        if not can_appeal_result:
            return (False, deny_reason, None)

        # case is already fetched by can_appeal
        if not case:
            return (False, "Case not found", None)

        # Verify user matches case
        if case["user_id"] != user.id:
            return (False, "You can only appeal your own cases", None)

        # Check cooldown (24h between appeals for same case)
        last_appeal_time = self.db.get_last_appeal_time(case_id)
        if last_appeal_time:
            time_since_last = time.time() - last_appeal_time
            if time_since_last < APPEAL_COOLDOWN_SECONDS:
                hours_remaining = int((APPEAL_COOLDOWN_SECONDS - time_since_last) / 3600)
                return (False, f"You must wait {hours_remaining}h before appealing this case again", None)

        # Check rate limit (max 3 appeals per week)
        week_ago = time.time() - APPEAL_RATE_LIMIT_SECONDS
        appeals_this_week = self.db.get_user_appeal_count_since(user.id, week_ago)
        if appeals_this_week >= MAX_APPEALS_PER_WEEK:
            return (False, f"You have reached the maximum of {MAX_APPEALS_PER_WEEK} appeals per week", None)

        try:
            # Use case_id as appeal_id (1:1 relationship)
            appeal_id = case_id
            action_type = case.get("action_type", "unknown")

            # Store in database (only store metadata, not the actual attachment data)
            attachment_metadata = None
            if attachments:
                attachment_metadata = [
                    {"name": att["name"], "type": att["type"]}
                    for att in attachments
                ]

            # Mute appeals create a ticket, ban appeals are web-only
            thread_id = None
            appeal_mode = "Web Dashboard"

            if action_type == "mute" and hasattr(self.bot, "ticket_service"):
                # Create a mute appeal ticket
                guild = self.bot.get_guild(case["guild_id"])
                if guild:
                    member = guild.get_member(user.id)
                    if member:
                        success, msg, ticket_id = await self.bot.ticket_service.create_ticket(
                            user=member,
                            category="appeal",
                            subject=f"Mute Appeal - Case {case_id}",
                            description=reason,
                            case_id=case_id,
                        )
                        if success and ticket_id:
                            # Get the thread_id from the ticket
                            ticket_data = self.db.get_ticket(ticket_id)
                            if ticket_data:
                                thread_id = ticket_data.get("thread_id")
                                appeal_mode = "Ticket"

            self.db.create_appeal(
                appeal_id=appeal_id,
                case_id=case_id,
                user_id=user.id,
                guild_id=case["guild_id"],
                action_type=action_type,
                reason=reason,
                email=email,
                attachments=attachment_metadata,
                thread_id=thread_id,
            )

            # Log
            prior_appeals = appeals_this_week  # Already calculated above
            logger.tree("APPEAL CREATED", [
                ("Appeal ID", appeal_id),
                ("Case ID", case_id),
                ("User", user.name),
                ("ID", str(user.id)),
                ("Action", action_type.title()),
                ("Prior Appeals", f"{prior_appeals} this week"),
                ("Mode", appeal_mode),
            ], emoji="📝")

            # Log to server logs
            await self._log_appeal_created(
                appeal_id=appeal_id,
                case_id=case_id,
                user=user,
                action_type=action_type,
                reason=reason,
            )

            return (True, f"Appeal submitted successfully. Appeal ID: `{appeal_id}`", appeal_id)

        except Exception as e:
            logger.error("Appeal Creation Failed", [
                ("Case ID", case_id),
                ("User ID", str(user.id)),
                ("Error", str(e)[:100]),
            ])
            return (False, "Failed to create appeal. Please try again.", None)

    async def submit_appeal(
        self: "AppealService",
        case_id: str,
        user_id: int,
        reason: str,
        email: Optional[str] = None,
        attachments: Optional[List[str]] = None,
        client_ip: Optional[str] = None,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Submit an appeal from the web form.

        This is a wrapper around create_appeal that fetches the user
        from Discord first.

        Args:
            case_id: Case ID to appeal.
            user_id: User ID submitting the appeal.
            reason: User's appeal reason.
            email: Optional email for notifications.
            attachments: Optional list of attachment URLs.
            client_ip: Client IP for logging.

        Returns:
            Tuple of (success, appeal_id, error_message).
        """
        try:
            # Fetch user from Discord
            user = await self.bot.fetch_user(user_id)
            if not user:
                return (False, None, "Could not verify your Discord account")

            # Convert URL attachments to the format create_appeal expects
            attachment_data = None
            if attachments:
                attachment_data = [
                    {"name": f"attachment_{i}.png", "type": "image/png", "url": url}
                    for i, url in enumerate(attachments)
                ]

            # Call create_appeal
            success, message, appeal_id = await self.create_appeal(
                case_id=case_id,
                user=user,
                reason=reason,
                email=email,
                attachments=attachment_data,
            )

            if success:
                logger.tree("Web Appeal Submitted", [
                    ("Appeal ID", appeal_id or "N/A"),
                    ("Case ID", case_id),
                    ("User", user.name),
                    ("Client IP", client_ip or "Unknown"),
                ], emoji="🌐")
                return (True, appeal_id, None)
            else:
                return (False, None, message)

        except Exception as e:
            logger.error("Web Appeal Submit Error", [
                ("Case ID", case_id),
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])
            return (False, None, "An unexpected error occurred")


__all__ = ["CreateMixin"]
