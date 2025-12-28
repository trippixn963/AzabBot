"""
Azab Discord Bot - Appeal Service
==================================

Service for handling ban and mute appeals.

Features:
    - Create appeals via DM or button
    - Appeals create forum threads in mods server
    - Links to original case via case_id
    - Approve/deny/close appeals with actions
    - Mutes over 6 hours and all bans can be appealed

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.retry import safe_fetch_channel, safe_send, safe_edit
from src.utils.views import CASE_EMOJI, APPROVE_EMOJI, APPEAL_EMOJI, DENY_EMOJI

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Minimum mute duration (in seconds) that can be appealed (6 hours)
MIN_APPEALABLE_MUTE_DURATION = 6 * 60 * 60  # 6 hours in seconds

# Appeal cooldown: 24 hours between appeals for the same case
APPEAL_COOLDOWN_SECONDS = 24 * 60 * 60  # 24 hours

# Appeal rate limit: max 3 appeals per user per week
MAX_APPEALS_PER_WEEK = 3
APPEAL_RATE_LIMIT_SECONDS = 7 * 24 * 60 * 60  # 7 days


# =============================================================================
# Appeal Service
# =============================================================================

class AppealService:
    """
    Service for managing ban and mute appeals.

    DESIGN:
        Appeals are created in a dedicated forum channel in the mods server.
        Each appeal gets its own thread using the original case ID.
        All bans can be appealed, mutes over 6 hours can be appealed.
    """

    # Thread cache TTL
    THREAD_CACHE_TTL = timedelta(minutes=5)

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()
        self._forum: Optional[discord.ForumChannel] = None
        self._forum_cache_time: Optional[datetime] = None
        self._thread_cache: Dict[int, tuple[discord.Thread, datetime]] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Check if appeal system is enabled."""
        return self.config.appeal_forum_id is not None

    # =========================================================================
    # Forum Access
    # =========================================================================

    async def _get_forum(self) -> Optional[discord.ForumChannel]:
        """Get the appeal forum channel with caching."""
        if not self.config.appeal_forum_id:
            return None

        now = datetime.now(NY_TZ)

        # Check cache
        if self._forum is not None and self._forum_cache_time is not None:
            if now - self._forum_cache_time < self.THREAD_CACHE_TTL:
                return self._forum

        # Fetch forum
        channel = await safe_fetch_channel(self.bot, self.config.appeal_forum_id)
        if channel is None:
            logger.warning(f"Appeal Forum Not Found: {self.config.appeal_forum_id}")
            return None

        if isinstance(channel, discord.ForumChannel):
            self._forum = channel
            self._forum_cache_time = now
            return self._forum

        logger.warning(f"Channel {self.config.appeal_forum_id} is not a ForumChannel")
        return None

    async def _get_appeal_thread(self, thread_id: int) -> Optional[discord.Thread]:
        """Get an appeal thread by ID with caching."""
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
    # Appeal Eligibility
    # =========================================================================

    def can_appeal(self, case_id: str) -> tuple[bool, Optional[str], Optional[dict]]:
        """
        Check if a case can be appealed.

        Args:
            case_id: Case ID to check.

        Returns:
            Tuple of (can_appeal, reason_if_not, case_data).
            case_data is returned to avoid redundant queries.
        """
        # Check if appeals are enabled
        if not self.enabled:
            return (False, "Appeal system is not enabled", None)

        # Check if case exists
        case = self.db.get_appealable_case(case_id)
        if not case:
            return (False, "Case not found", None)

        # Check action type
        action_type = case.get("action_type", "")
        if action_type not in ("ban", "mute"):
            return (False, f"Cannot appeal {action_type} actions", None)

        # For mutes, check duration (must be >= 6 hours)
        if action_type == "mute":
            duration = case.get("duration_seconds")
            if duration is None:
                # Permanent mute - can appeal
                pass
            elif duration < MIN_APPEALABLE_MUTE_DURATION:
                hours = duration // 3600
                minutes = (duration % 3600) // 60
                return (False, f"Mutes under 6 hours cannot be appealed (this mute: {hours}h {minutes}m)", None)

        # Check if already appealed
        can_appeal_db, reason = self.db.can_appeal_case(case_id)
        if not can_appeal_db:
            return (False, reason, None)

        return (True, None, case)

    # =========================================================================
    # Create Appeal
    # =========================================================================

    async def create_appeal(
        self,
        case_id: str,
        user: discord.User,
        reason: str,
    ) -> tuple[bool, str, Optional[str]]:
        """
        Create a new appeal for a case.

        Args:
            case_id: Case ID to appeal.
            user: User submitting the appeal.
            reason: User's appeal reason.

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
        import time
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

            # Create forum thread
            thread = await forum.create_thread(
                name=thread_name,
                embed=embed,
                view=AppealActionView(appeal_id, case_id, user.id),
            )

            # Store in database
            self.db.create_appeal(
                appeal_id=appeal_id,
                case_id=case_id,
                user_id=user.id,
                guild_id=case["guild_id"],
                thread_id=thread.thread.id,
                action_type=action_type,
                reason=reason,
            )

            # Cache thread
            self._thread_cache[thread.thread.id] = (thread.thread, datetime.now(NY_TZ))

            # Log
            logger.tree("APPEAL CREATED", [
                ("Appeal ID", appeal_id),
                ("Case ID", case_id),
                ("User", f"{user} ({user.id})"),
                ("Action", action_type.title()),
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
        self,
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

        set_footer(embed)

        return embed

    # =========================================================================
    # Resolve Appeal
    # =========================================================================

    async def approve_appeal(
        self,
        appeal_id: str,
        moderator: discord.Member,
        reason: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Approve an appeal and take action.

        For bans: Unban the user.
        For mutes: Unmute the user.

        Args:
            appeal_id: Appeal ID to approve.
            moderator: Moderator approving.
            reason: Optional approval reason.

        Returns:
            Tuple of (success, message).
        """
        appeal = self.db.get_appeal(appeal_id)
        if not appeal:
            return (False, "Appeal not found")

        if appeal["status"] != "pending":
            return (False, "Appeal is no longer pending")

        # Atomically resolve the appeal first to prevent race conditions
        # This only succeeds if status is still 'pending'
        resolved = self.db.resolve_appeal(
            appeal_id=appeal_id,
            resolution="approved",
            resolved_by=moderator.id,
            resolution_reason=reason,
        )
        if not resolved:
            return (False, "Appeal was already processed by another moderator")

        try:
            # Get the guild
            guild = self.bot.get_guild(appeal["guild_id"])
            if not guild:
                return (False, "Guild not found")

            user_id = appeal["user_id"]
            action_type = appeal["action_type"]
            case_id = appeal["case_id"]

            # Take action based on type
            if action_type == "ban":
                # Unban user
                try:
                    user = await self.bot.fetch_user(user_id)
                    await guild.unban(user, reason=f"Appeal {appeal_id} approved by {moderator}")
                except discord.NotFound:
                    pass  # User not banned or doesn't exist
                except discord.HTTPException as e:
                    logger.warning(f"Failed to unban user {user_id}: {e}")

            elif action_type == "mute":
                # Remove muted role
                member = guild.get_member(user_id)
                if member:
                    muted_role = guild.get_role(self.config.muted_role_id)
                    if muted_role and muted_role in member.roles:
                        try:
                            await member.remove_roles(
                                muted_role,
                                reason=f"Appeal {appeal_id} approved by {moderator}"
                            )
                        except discord.HTTPException as e:
                            logger.warning(f"Failed to unmute user {user_id}: {e}")

                    # Remove timeout if any
                    if member.is_timed_out():
                        try:
                            await member.timeout(None, reason=f"Appeal {appeal_id} approved")
                        except discord.HTTPException:
                            pass

                # Clear mute from database
                self.db.remove_mute(user_id, guild.id, moderator.id, "Appeal approved")

            # Resolve the original case
            case = self.db.get_case(case_id)
            if case:
                self.db.resolve_case(
                    case_id=case_id,
                    resolved_by=moderator.id,
                    reason=f"Appeal approved: {reason}" if reason else "Appeal approved",
                )

            # Update thread
            thread = await self._get_appeal_thread(appeal["thread_id"])
            if thread:
                # Send resolution message
                embed = discord.Embed(
                    title="✅ Appeal Approved",
                    description=f"This appeal has been **approved** by {moderator.mention}.",
                    color=EmbedColors.SUCCESS,
                    timestamp=datetime.now(NY_TZ),
                )
                if reason:
                    embed.add_field(name="Reason", value=f"```{reason}```", inline=False)

                action_taken = "User has been unbanned" if action_type == "ban" else "User has been unmuted"
                embed.add_field(name="Action Taken", value=action_taken, inline=False)

                set_footer(embed)
                await safe_send(thread, embed=embed)

                # Archive thread
                try:
                    await thread.edit(archived=True, locked=True)
                except discord.HTTPException:
                    pass

            # Log
            logger.tree("APPEAL APPROVED", [
                ("Appeal ID", appeal_id),
                ("Case ID", case_id),
                ("Moderator", f"{moderator} ({moderator.id})"),
                ("Action", action_type.title()),
            ], emoji="✅")

            # Log to server logs
            await self._log_appeal_resolved(
                appeal_id=appeal_id,
                case_id=case_id,
                user_id=user_id,
                moderator=moderator,
                resolution="approved",
                reason=reason,
            )

            # DM the user
            try:
                user = await self.bot.fetch_user(user_id)
                dm_embed = discord.Embed(
                    title="✅ Your Appeal Was Approved",
                    description=f"Your appeal for case `{case_id}` has been approved.",
                    color=EmbedColors.SUCCESS,
                    timestamp=datetime.now(NY_TZ),
                )
                if action_type == "ban":
                    dm_embed.add_field(
                        name="Action",
                        value="You have been unbanned from the server.",
                        inline=False,
                    )
                else:
                    dm_embed.add_field(
                        name="Action",
                        value="Your mute has been removed.",
                        inline=False,
                    )
                if reason:
                    dm_embed.add_field(name="Note", value=reason, inline=False)
                set_footer(dm_embed)
                await user.send(embed=dm_embed)
            except (discord.HTTPException, discord.Forbidden):
                pass  # Can't DM user

            return (True, f"Appeal approved. User has been {'unbanned' if action_type == 'ban' else 'unmuted'}.")

        except Exception as e:
            logger.error("Appeal Approval Failed", [
                ("Appeal ID", appeal_id),
                ("Error", str(e)[:100]),
            ])
            return (False, f"Failed to approve appeal: {str(e)[:50]}")

    async def deny_appeal(
        self,
        appeal_id: str,
        moderator: discord.Member,
        reason: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Deny an appeal.

        Args:
            appeal_id: Appeal ID to deny.
            moderator: Moderator denying.
            reason: Optional denial reason.

        Returns:
            Tuple of (success, message).
        """
        appeal = self.db.get_appeal(appeal_id)
        if not appeal:
            return (False, "Appeal not found")

        if appeal["status"] != "pending":
            return (False, "Appeal is no longer pending")

        # Atomically resolve the appeal first to prevent race conditions
        # This only succeeds if status is still 'pending'
        resolved = self.db.resolve_appeal(
            appeal_id=appeal_id,
            resolution="denied",
            resolved_by=moderator.id,
            resolution_reason=reason,
        )
        if not resolved:
            return (False, "Appeal was already processed by another moderator")

        try:
            user_id = appeal["user_id"]
            case_id = appeal["case_id"]

            # Update thread
            thread = await self._get_appeal_thread(appeal["thread_id"])
            if thread:
                embed = discord.Embed(
                    title="❌ Appeal Denied",
                    description=f"This appeal has been **denied** by {moderator.mention}.",
                    color=EmbedColors.ERROR,
                    timestamp=datetime.now(NY_TZ),
                )
                if reason:
                    embed.add_field(name="Reason", value=f"```{reason}```", inline=False)
                set_footer(embed)
                await safe_send(thread, embed=embed)

                # Archive thread
                try:
                    await thread.edit(archived=True, locked=True)
                except discord.HTTPException:
                    pass

            # Log
            logger.tree("APPEAL DENIED", [
                ("Appeal ID", appeal_id),
                ("Case ID", case_id),
                ("Moderator", f"{moderator} ({moderator.id})"),
            ], emoji="❌")

            # Log to server logs
            await self._log_appeal_resolved(
                appeal_id=appeal_id,
                case_id=case_id,
                user_id=user_id,
                moderator=moderator,
                resolution="denied",
                reason=reason,
            )

            # DM the user
            try:
                user = await self.bot.fetch_user(user_id)
                dm_embed = discord.Embed(
                    title="❌ Your Appeal Was Denied",
                    description=f"Your appeal for case `{case_id}` has been denied.",
                    color=EmbedColors.ERROR,
                    timestamp=datetime.now(NY_TZ),
                )
                if reason:
                    dm_embed.add_field(name="Reason", value=reason, inline=False)
                set_footer(dm_embed)
                await user.send(embed=dm_embed)
            except (discord.HTTPException, discord.Forbidden):
                pass

            return (True, "Appeal denied.")

        except Exception as e:
            logger.error("Appeal Denial Failed", [
                ("Appeal ID", appeal_id),
                ("Error", str(e)[:100]),
            ])
            return (False, f"Failed to deny appeal: {str(e)[:50]}")

    # =========================================================================
    # Logging Integration
    # =========================================================================

    async def _log_appeal_created(
        self,
        appeal_id: str,
        case_id: str,
        user: discord.User,
        action_type: str,
        reason: str,
    ) -> None:
        """Log appeal creation to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="📝 Appeal Submitted",
                color=EmbedColors.WARNING,
                timestamp=datetime.now(NY_TZ),
            )

            embed.add_field(name="Appeal ID", value=f"`{appeal_id}`", inline=True)
            embed.add_field(name="Case ID", value=f"`{case_id}`", inline=True)
            embed.add_field(name="Type", value=action_type.title(), inline=True)
            embed.add_field(
                name="User",
                value=f"{user.mention}\n`{user.id}`",
                inline=True,
            )
            if reason:
                preview = (reason[:100] + "...") if len(reason) > 100 else reason
                embed.add_field(name="Reason Preview", value=f"```{preview}```", inline=False)

            set_footer(embed)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.MOD_ACTIONS,
                embed,
            )
        except Exception as e:
            logger.debug(f"Failed to log appeal creation: {e}")

    async def _log_appeal_resolved(
        self,
        appeal_id: str,
        case_id: str,
        user_id: int,
        moderator: discord.Member,
        resolution: str,
        reason: Optional[str],
    ) -> None:
        """Log appeal resolution to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            emoji = "✅" if resolution == "approved" else "❌"
            color = EmbedColors.SUCCESS if resolution == "approved" else EmbedColors.ERROR

            embed = discord.Embed(
                title=f"{emoji} Appeal {resolution.title()}",
                color=color,
                timestamp=datetime.now(NY_TZ),
            )

            embed.add_field(name="Appeal ID", value=f"`{appeal_id}`", inline=True)
            embed.add_field(name="Case ID", value=f"`{case_id}`", inline=True)
            embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)
            embed.add_field(
                name="Resolved By",
                value=f"{moderator.mention}\n`{moderator.id}`",
                inline=True,
            )
            if reason:
                embed.add_field(name="Reason", value=f"```{reason[:200]}```", inline=False)

            set_footer(embed)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.MOD_ACTIONS,
                embed,
            )
        except Exception as e:
            logger.debug(f"Failed to log appeal resolution: {e}")


# =============================================================================
# Appeal Action View (Persistent)
# =============================================================================

class AppealActionView(discord.ui.View):
    """
    Persistent view with Approve/Deny buttons for appeals.

    DESIGN:
        Uses custom_id pattern for persistence across bot restarts.
        Only moderators can use these buttons.
    """

    def __init__(self, appeal_id: str, case_id: str, user_id: int):
        super().__init__(timeout=None)

        # Add buttons
        self.add_item(ApproveAppealButton(appeal_id, case_id))
        self.add_item(DenyAppealButton(appeal_id, case_id))
        self.add_item(ViewCaseButton(case_id))


class ApproveAppealButton(discord.ui.DynamicItem[discord.ui.Button], template=r"appeal_approve:(?P<appeal_id>[A-Z0-9]+):(?P<case_id>[A-Z0-9]+)"):
    """Persistent approve appeal button."""

    def __init__(self, appeal_id: str, case_id: str):
        super().__init__(
            discord.ui.Button(
                label="Approve",
                style=discord.ButtonStyle.secondary,
                custom_id=f"appeal_approve:{appeal_id}:{case_id}",
                emoji=APPROVE_EMOJI,
            )
        )
        self.appeal_id = appeal_id
        self.case_id = case_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "ApproveAppealButton":
        appeal_id = match.group("appeal_id")
        case_id = match.group("case_id")
        return cls(appeal_id, case_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        # Check permissions - must have moderate_members OR be in allowed user list
        config = get_config()
        allowed_ids = {config.developer_id}
        if config.appeal_allowed_user_ids:
            allowed_ids |= config.appeal_allowed_user_ids

        has_permission = (
            interaction.user.guild_permissions.moderate_members or
            interaction.user.id in allowed_ids
        )

        if not has_permission:
            await interaction.response.send_message(
                "You don't have permission to approve appeals.",
                ephemeral=True,
            )
            return

        # Show modal for reason
        modal = AppealReasonModal(self.appeal_id, self.case_id, "approve")
        await interaction.response.send_modal(modal)


class DenyAppealButton(discord.ui.DynamicItem[discord.ui.Button], template=r"appeal_deny:(?P<appeal_id>[A-Z0-9]+):(?P<case_id>[A-Z0-9]+)"):
    """Persistent deny appeal button."""

    def __init__(self, appeal_id: str, case_id: str):
        super().__init__(
            discord.ui.Button(
                label="Deny",
                style=discord.ButtonStyle.secondary,
                custom_id=f"appeal_deny:{appeal_id}:{case_id}",
                emoji=DENY_EMOJI,
            )
        )
        self.appeal_id = appeal_id
        self.case_id = case_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "DenyAppealButton":
        appeal_id = match.group("appeal_id")
        case_id = match.group("case_id")
        return cls(appeal_id, case_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        # Check permissions - must have moderate_members OR be in allowed user list
        config = get_config()
        allowed_ids = {config.developer_id}
        if config.appeal_allowed_user_ids:
            allowed_ids |= config.appeal_allowed_user_ids

        has_permission = (
            interaction.user.guild_permissions.moderate_members or
            interaction.user.id in allowed_ids
        )

        if not has_permission:
            await interaction.response.send_message(
                "You don't have permission to deny appeals.",
                ephemeral=True,
            )
            return

        # Show modal for reason
        modal = AppealReasonModal(self.appeal_id, self.case_id, "deny")
        await interaction.response.send_modal(modal)


class ViewCaseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"appeal_viewcase:(?P<case_id>[A-Z0-9]+)"):
    """Persistent button to view the original case thread."""

    def __init__(self, case_id: str):
        super().__init__(
            discord.ui.Button(
                label="View Case",
                style=discord.ButtonStyle.secondary,
                emoji=CASE_EMOJI,
                custom_id=f"appeal_viewcase:{case_id}",
            )
        )
        self.case_id = case_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "ViewCaseButton":
        case_id = match.group("case_id")
        return cls(case_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        # Get case info
        db = get_db()
        case = db.get_case(self.case_id)

        if case and case.get("thread_id"):
            case_url = f"https://discord.com/channels/{case['guild_id']}/{case['thread_id']}"
            await interaction.response.send_message(
                f"View case thread: {case_url}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"Case `{self.case_id}` not found or thread unavailable.",
                ephemeral=True,
            )


# =============================================================================
# Appeal Reason Modal
# =============================================================================

class AppealReasonModal(discord.ui.Modal):
    """Modal for entering appeal resolution reason."""

    def __init__(self, appeal_id: str, case_id: str, action: str):
        title = "Approve Appeal" if action == "approve" else "Deny Appeal"
        super().__init__(title=title)
        self.appeal_id = appeal_id
        self.case_id = case_id
        self.action = action

        self.reason = discord.ui.TextInput(
            label="Reason (optional)",
            style=discord.TextStyle.paragraph,
            placeholder="Enter a reason for this decision...",
            required=False,
            max_length=500,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        # Get appeal service from bot
        bot = interaction.client
        if not hasattr(bot, "appeal_service") or not bot.appeal_service:
            await interaction.followup.send(
                "Appeal service is not available.",
                ephemeral=True,
            )
            return

        reason = self.reason.value.strip() if self.reason.value else None

        if self.action == "approve":
            success, message = await bot.appeal_service.approve_appeal(
                self.appeal_id,
                interaction.user,
                reason,
            )
        else:
            success, message = await bot.appeal_service.deny_appeal(
                self.appeal_id,
                interaction.user,
                reason,
            )

        await interaction.followup.send(message, ephemeral=True)


# =============================================================================
# Submit Appeal Button (for case embeds)
# =============================================================================

class SubmitAppealButton(discord.ui.DynamicItem[discord.ui.Button], template=r"submit_appeal:(?P<case_id>[A-Z0-9]+):(?P<user_id>\d+)"):
    """
    Persistent button on case embeds to submit an appeal.

    Only the affected user can use this button.
    """

    def __init__(self, case_id: str, user_id: int):
        super().__init__(
            discord.ui.Button(
                label="Appeal",
                style=discord.ButtonStyle.secondary,
                custom_id=f"submit_appeal:{case_id}:{user_id}",
                emoji=APPEAL_EMOJI,
            )
        )
        self.case_id = case_id
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match,
    ) -> "SubmitAppealButton":
        case_id = match.group("case_id")
        user_id = int(match.group("user_id"))
        return cls(case_id, user_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        # This button should only appear in the original case thread
        # and only the affected user can submit
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "You can only appeal your own cases.",
                ephemeral=True,
            )
            return

        # Check if appeal service is available
        bot = interaction.client
        if not hasattr(bot, "appeal_service") or not bot.appeal_service:
            await interaction.response.send_message(
                "Appeal system is not available.",
                ephemeral=True,
            )
            return

        # Check eligibility
        can_appeal, reason, _ = bot.appeal_service.can_appeal(self.case_id)
        if not can_appeal:
            await interaction.response.send_message(
                f"Cannot submit appeal: {reason}",
                ephemeral=True,
            )
            return

        # Show appeal modal
        modal = SubmitAppealModal(self.case_id)
        await interaction.response.send_modal(modal)


class SubmitAppealModal(discord.ui.Modal, title="Submit Appeal"):
    """Modal for submitting an appeal."""

    def __init__(self, case_id: str):
        super().__init__()
        self.case_id = case_id

        self.reason = discord.ui.TextInput(
            label="Why should your punishment be removed?",
            style=discord.TextStyle.paragraph,
            placeholder="Explain why you believe your ban/mute should be reversed...",
            required=True,
            min_length=20,
            max_length=1000,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        bot = interaction.client
        if not hasattr(bot, "appeal_service") or not bot.appeal_service:
            await interaction.followup.send(
                "Appeal system is not available.",
                ephemeral=True,
            )
            return

        success, message, appeal_id = await bot.appeal_service.create_appeal(
            case_id=self.case_id,
            user=interaction.user,
            reason=self.reason.value,
        )

        if success:
            await interaction.followup.send(
                f"✅ {message}\n\nYour appeal has been submitted to the moderation team for review.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"❌ {message}",
                ephemeral=True,
            )


# =============================================================================
# Setup Function (for persistent views)
# =============================================================================

def setup_appeal_views(bot: "AzabBot") -> None:
    """Register appeal dynamic items for persistence."""
    bot.add_dynamic_items(
        ApproveAppealButton,
        DenyAppealButton,
        ViewCaseButton,
        SubmitAppealButton,
    )
    logger.debug("Appeal Views Registered")
