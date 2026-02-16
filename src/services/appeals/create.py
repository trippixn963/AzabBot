"""
AzabBot - Appeal Creation Mixin
===============================

Methods for creating new appeals.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import base64
import io
import time
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.utils.discord_rate_limit import log_http_error

from .constants import (
    APPEAL_COOLDOWN_SECONDS,
    MAX_APPEALS_PER_WEEK,
    APPEAL_RATE_LIMIT_SECONDS,
)
from .views import AppealActionView

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
            # Get forum
            forum = await self._get_forum()
            if not forum:
                return (False, "Appeal system is not properly configured", None)

            # Generate appeal ID
            appeal_id = self.db.get_next_appeal_id()
            action_type = case.get("action_type", "unknown")

            # Create thread
            thread_name = f"[{case_id}] | Appeal | {user.name}"
            if len(thread_name) > 100:
                thread_name = thread_name[:97] + "..."

            # Build initial embed
            embed = self._build_appeal_embed(
                appeal_id=appeal_id,
                case_id=case_id,
                user=user,
                action_type=action_type,
                reason=reason,
                case_data=case,
            )

            # Build case URL for View Case button
            case_url = None
            if case.get("thread_id") and case.get("guild_id"):
                case_url = f"https://discord.com/channels/{case['guild_id']}/{case['thread_id']}"

            # Create forum thread with control panel
            thread = await forum.create_thread(
                name=thread_name,
                embed=embed,
                view=AppealActionView(
                    appeal_id=appeal_id,
                    case_id=case_id,
                    user_id=user.id,
                    guild_id=case["guild_id"],
                    case_url=case_url,
                    action_type=action_type,
                ),
            )

            # Store in database (only store metadata, not the actual attachment data)
            attachment_metadata = None
            if attachments:
                attachment_metadata = [
                    {"name": att["name"], "type": att["type"]}
                    for att in attachments
                ]

            self.db.create_appeal(
                appeal_id=appeal_id,
                case_id=case_id,
                user_id=user.id,
                guild_id=case["guild_id"],
                thread_id=thread.thread.id,
                action_type=action_type,
                reason=reason,
                email=email,
                attachments=attachment_metadata,
            )

            # Upload attachments to the thread if any
            if attachments:
                await self._upload_attachments(thread.thread, attachments, appeal_id)

            # Cache thread
            self._thread_cache[thread.thread.id] = (thread.thread, datetime.now(NY_TZ))

            # Log
            prior_appeals = appeals_this_week  # Already calculated above
            logger.tree("APPEAL CREATED", [
                ("Appeal ID", appeal_id),
                ("Case ID", case_id),
                ("User", user.name),
                ("ID", str(user.id)),
                ("Action", action_type.title()),
                ("Prior Appeals", f"{prior_appeals} this week"),
                ("Thread ID", str(thread.thread.id)),
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

    def _build_appeal_embed(
        self: "AppealService",
        appeal_id: str,
        case_id: str,
        user: discord.User,
        action_type: str,
        reason: str,
        case_data: dict,
    ) -> discord.Embed:
        """Build the appeal embed for the forum thread."""
        now = datetime.now(NY_TZ)

        # Emoji based on action type
        emoji = "🔨" if action_type == "ban" else "🔇"

        embed = discord.Embed(
            title=f"{emoji} {action_type.title()} Appeal",
            color=EmbedColors.WARNING,
            timestamp=now,
        )

        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)

        # Appeal info
        embed.add_field(name="Appeal ID", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Case ID", value=f"`{case_id}`", inline=True)
        embed.add_field(name="Status", value="⏳ Pending", inline=True)

        # User info
        embed.add_field(name="User", value=f"{user.mention}\n`{user.id}`", inline=True)

        # Account age
        created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
        age_days = (now - created_at).days
        if age_days < 30:
            age_str = f"{age_days} days"
        elif age_days < 365:
            age_str = f"{age_days // 30} months"
        else:
            years = age_days // 365
            months = (age_days % 365) // 30
            age_str = f"{years}y {months}m"
        embed.add_field(name="Account Age", value=f"`{age_str}`", inline=True)

        # Action details
        if action_type == "mute":
            duration = case_data.get("duration_seconds")
            if duration:
                hours = duration // 3600
                minutes = (duration % 3600) // 60
                embed.add_field(name="Mute Duration", value=f"`{hours}h {minutes}m`", inline=True)
            else:
                embed.add_field(name="Mute Duration", value="`Permanent`", inline=True)

        # Original case date
        case_created = case_data.get("created_at")
        if case_created:
            embed.add_field(
                name="Action Date",
                value=f"<t:{int(case_created)}:R>",
                inline=True,
            )

        # User's appeal reason
        embed.add_field(
            name="Appeal Reason",
            value=f"```{reason[:1000]}```" if reason else "```No reason provided```",
            inline=False,
        )

        # Prior actions
        mute_count = self.db.get_user_mute_count(user.id, case_data.get("guild_id", 0))
        ban_count = self.db.get_user_ban_count(user.id, case_data.get("guild_id", 0))
        embed.add_field(
            name="Prior Actions",
            value=f"Mutes: `{mute_count}` | Bans: `{ban_count}`",
            inline=False,
        )

        return embed

    async def _upload_attachments(
        self: "AppealService",
        thread: discord.Thread,
        attachments: List[Dict[str, str]],
        appeal_id: str,
    ) -> None:
        """
        Upload attachments to the appeal thread.

        Args:
            thread: Discord thread to upload to.
            attachments: List of attachments with name, type, and base64 data.
            appeal_id: Appeal ID for logging.
        """
        if not attachments:
            return

        discord_files = []
        for att in attachments:
            try:
                # Decode base64 data
                file_data = base64.b64decode(att["data"])
                file_obj = io.BytesIO(file_data)
                discord_file = discord.File(file_obj, filename=att["name"])
                discord_files.append(discord_file)
            except Exception as e:
                logger.warning("Failed to process attachment", [
                    ("Appeal ID", appeal_id),
                    ("File", att.get("name", "unknown")),
                    ("Error", str(e)[:50]),
                ])
                continue

        if discord_files:
            try:
                await thread.send(
                    content="📎 **Attachments from appellant:**",
                    files=discord_files,
                )
                logger.tree("Appeal Attachments Uploaded", [
                    ("Appeal ID", appeal_id),
                    ("Count", str(len(discord_files))),
                ], emoji="📎")
            except discord.HTTPException as e:
                log_http_error(e, "Upload Attachments", [
                    ("Appeal ID", appeal_id),
                ])

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
