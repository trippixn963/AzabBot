"""
Case Log Service
================

Main service class for logging moderation actions to forum threads.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import io
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict, Tuple, List

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.retry import (
    safe_fetch_channel,
    safe_fetch_message,
    safe_send,
    safe_edit,
    safe_delete,
)
from src.utils.async_utils import create_safe_task

from .constants import (
    THREAD_CACHE_TTL,
    THREAD_CACHE_MAX_SIZE,
    PROFILE_UPDATE_DEBOUNCE,
    REASON_CHECK_INTERVAL,
    REASON_EXPIRY_TIME,
    REASON_CLEANUP_AGE,
    REPEAT_MUTE_THRESHOLD,
    REPEAT_WARN_THRESHOLD,
)
from .utils import (
    format_duration_precise,
    format_age,
    parse_duration_to_seconds,
    has_valid_media_evidence,
)
from .views import CaseLogView, CaseControlPanelView
from .embeds import build_control_panel_embed
from .actions import CaseLogActionsMixin
from .actions_extended import CaseLogExtendedActionsMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


class CaseLogService(CaseLogActionsMixin, CaseLogExtendedActionsMixin):
    """
    Service for logging moderation actions to forum threads.

    DESIGN:
        Each mute/ban/warn creates its own case and thread (per-action).
        Legacy per-user cases are supported for backward compatibility.
    """

    def __init__(self, bot: "AzabBot") -> None:
        """Initialize the case log service."""
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        # Forum cache
        self._forum: Optional[discord.ForumChannel] = None
        self._forum_cache_time: Optional[datetime] = None

        # Thread cache: thread_id -> (thread, cached_at)
        self._thread_cache: Dict[int, Tuple[discord.Thread, datetime]] = {}

        # Pending reason scheduler
        self._reason_check_task: Optional[asyncio.Task] = None
        self._reason_check_running: bool = False

        # Debounced profile updates
        self._pending_profile_updates: Dict[int, dict] = {}
        self._profile_update_task: Optional[asyncio.Task] = None

        # Forum tag cache: tag_name -> ForumTag
        self._tag_cache: Dict[str, discord.ForumTag] = {}
        self._tags_initialized: bool = False

    # =========================================================================
    # Forum Tag Definitions
    # =========================================================================

    # Status tags
    TAG_PENDING_REVIEW = ("🔴 Pending Review", discord.Colour.red())
    TAG_APPROVED = ("🟢 Approved", discord.Colour.green())

    # Action type tags
    TAG_MUTE = ("🔇 Mute", discord.Colour.orange())
    TAG_BAN = ("🔨 Ban", discord.Colour.dark_red())
    TAG_WARN = ("⚠️ Warn", discord.Colour.gold())
    TAG_FORBID = ("🚫 Forbid", discord.Colour.purple())

    ALL_TAGS = [TAG_PENDING_REVIEW, TAG_APPROVED, TAG_MUTE, TAG_BAN, TAG_WARN, TAG_FORBID]

    # =========================================================================
    # Forum Tag Management
    # =========================================================================

    async def ensure_forum_tags(self) -> bool:
        """
        Ensure all required tags exist on the case forum.
        Creates missing tags and caches all tag references.

        Returns:
            True if tags are ready, False if failed.
        """
        if self._tags_initialized:
            return True

        if not self.enabled:
            return False

        try:
            forum = await self._get_forum()
            if not forum:
                logger.warning("Case Log: Cannot ensure tags - forum not found")
                return False

            existing_tags = {tag.name: tag for tag in forum.available_tags}
            tags_to_create = []
            created_count = 0

            # Check which tags need to be created
            for tag_name, tag_color in self.ALL_TAGS:
                if tag_name in existing_tags:
                    self._tag_cache[tag_name] = existing_tags[tag_name]
                else:
                    tags_to_create.append(discord.ForumTag(name=tag_name, emoji=None, moderated=False))

            # Create missing tags (need to update forum with all tags)
            if tags_to_create:
                new_tags = list(forum.available_tags) + tags_to_create
                # Discord limits to 20 tags
                if len(new_tags) > 20:
                    logger.warning("Case Log: Too many tags, cannot add all")
                    new_tags = new_tags[:20]

                await forum.edit(available_tags=new_tags)
                created_count = len(tags_to_create)

                # Refresh forum to get new tag IDs
                forum = await self.bot.fetch_channel(self.config.case_log_forum_id)
                if forum and isinstance(forum, discord.ForumChannel):
                    for tag in forum.available_tags:
                        self._tag_cache[tag.name] = tag

            self._tags_initialized = True

            if created_count > 0:
                logger.tree("Case Forum Tags Created", [
                    ("Created", str(created_count)),
                    ("Total Tags", str(len(self._tag_cache))),
                ], emoji="🏷️")
            else:
                logger.tree("Case Forum Tags Ready", [
                    ("Tags Cached", str(len(self._tag_cache))),
                ], emoji="🏷️")

            return True

        except discord.Forbidden:
            logger.error("Case Log: No permission to manage forum tags")
            return False
        except Exception as e:
            logger.error("Case Log: Failed to ensure forum tags", [
                ("Error", str(e)[:100]),
            ])
            return False

    def get_tags_for_case(self, action_type: str, is_approved: bool = False) -> List[discord.ForumTag]:
        """
        Get the appropriate tags for a case.

        Args:
            action_type: The action type (mute, ban, warn, forbid).
            is_approved: Whether the case is approved.

        Returns:
            List of ForumTag objects to apply.
        """
        tags = []

        # Status tag
        if is_approved:
            status_tag = self._tag_cache.get(self.TAG_APPROVED[0])
        else:
            status_tag = self._tag_cache.get(self.TAG_PENDING_REVIEW[0])

        if status_tag:
            tags.append(status_tag)

        # Action type tag
        action_tag_map = {
            "mute": self.TAG_MUTE[0],
            "timeout": self.TAG_MUTE[0],
            "ban": self.TAG_BAN[0],
            "warn": self.TAG_WARN[0],
            "forbid": self.TAG_FORBID[0],
        }

        action_tag_name = action_tag_map.get(action_type.lower())
        if action_tag_name:
            action_tag = self._tag_cache.get(action_tag_name)
            if action_tag:
                tags.append(action_tag)

        return tags

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Check if case logging is enabled."""
        return self.config.case_log_forum_id is not None

    def get_case_info(self, user_id: int) -> Optional[dict]:
        """Get case info for a user without logging."""
        case = self.db.get_case_log(user_id)
        if case:
            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}
        return None

    async def prepare_case(self, user: discord.Member) -> Optional[dict]:
        """Prepare a case for a user (get or create without logging)."""
        if not self.enabled:
            return None

        try:
            case = await self._get_or_create_case(user)
            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}
        except Exception as e:
            logger.error("Case Log: Failed To Prepare Case", [
                ("User ID", str(user.id)),
                ("Error", str(e)[:100]),
            ])
            return None

    # =========================================================================
    # Pending Reason Scheduler
    # =========================================================================

    async def start_reason_scheduler(self) -> None:
        """Start the background task for checking expired pending reasons."""
        if self._reason_check_task and not self._reason_check_task.done():
            self._reason_check_task.cancel()

        # Ensure forum tags exist on startup
        await self.ensure_forum_tags()

        self._reason_check_running = True
        self._reason_check_task = create_safe_task(
            self._reason_check_loop(), "Case Log Reason Checker"
        )

        logger.tree("Pending Reason Scheduler Started", [
            ("Check Interval", "5 minutes"),
            ("Expiry Time", "1 hour"),
        ], emoji="⏰")

    async def stop_reason_scheduler(self) -> None:
        """Stop the pending reason scheduler."""
        self._reason_check_running = False

        if self._reason_check_task and not self._reason_check_task.done():
            self._reason_check_task.cancel()
            try:
                await self._reason_check_task
            except asyncio.CancelledError:
                pass

        logger.tree("Pending Reason Scheduler Stopped", [
            ("Status", "Inactive"),
        ], emoji="⏹️")

    async def _reason_check_loop(self) -> None:
        """Background loop to check for expired pending reasons."""
        await self.bot.wait_until_ready()

        while self._reason_check_running:
            try:
                await self._process_expired_reasons()
                await asyncio.sleep(REASON_CHECK_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Pending Reason Scheduler Error", [
                    ("Error", str(e)[:100]),
                ])
                await asyncio.sleep(REASON_CHECK_INTERVAL)

    async def _process_expired_reasons(self) -> None:
        """Process expired pending reasons (cleanup only, no owner ping)."""
        self.db.cleanup_old_pending_reasons(max_age_seconds=REASON_CLEANUP_AGE)
        expired = self.db.get_expired_pending_reasons(max_age_seconds=REASON_EXPIRY_TIME)

        for pending in expired:
            try:
                # Just mark as processed and clean up - no owner ping needed
                self.db.mark_pending_reason_notified(pending["id"])

                logger.tree("Missing Reason Expired", [
                    ("Thread ID", str(pending["thread_id"])),
                    ("Moderator ID", str(pending["moderator_id"])),
                    ("Action", pending["action_type"]),
                ], emoji="⚠️")

            except Exception as e:
                logger.error("Failed To Process Expired Reason", [
                    ("Pending ID", str(pending["id"])),
                    ("Error", str(e)[:50]),
                ])

    # =========================================================================
    # Profile Updates (Debounced)
    # =========================================================================

    def _schedule_profile_update(self, user_id: int, case: dict) -> None:
        """Schedule a debounced profile stats update."""
        self._pending_profile_updates[user_id] = case

        if self._profile_update_task is None or self._profile_update_task.done():
            self._profile_update_task = create_safe_task(
                self._process_profile_updates(), "Case Log Profile Updates"
            )

    async def _process_profile_updates(self) -> None:
        """Process all pending profile updates after debounce delay."""
        await asyncio.sleep(PROFILE_UPDATE_DEBOUNCE)

        pending = self._pending_profile_updates.copy()
        self._pending_profile_updates.clear()

        if not pending:
            return

        success_count = 0
        fail_count = 0
        for user_id, case in pending.items():
            try:
                await self._update_profile_stats(user_id, case)
                success_count += 1
            except Exception as e:
                fail_count += 1
                logger.warning("Profile Stats Update Failed", [
                    ("User ID", str(user_id)),
                    ("Error", str(e)[:50]),
                ])

        if success_count > 0 or fail_count > 0:
            logger.tree("PROFILE STATS UPDATED", [
                ("Processed", str(success_count)),
                ("Failed", str(fail_count)),
            ], emoji="📊")

    async def _update_profile_stats(self, user_id: int, case: dict) -> None:
        """Update the pinned profile message with current stats."""
        try:
            case_thread = await self._get_case_thread(case["thread_id"])
            if not case_thread:
                return

            profile_msg = None

            if case.get("profile_message_id"):
                profile_msg = await safe_fetch_message(case_thread, case["profile_message_id"])

            if not profile_msg:
                try:
                    pinned = await case_thread.pins()
                    for msg in pinned:
                        if msg.embeds and msg.embeds[0].title == "📋 User Profile":
                            profile_msg = msg
                            self.db.set_profile_message_id(user_id, msg.id)
                            break
                except Exception:
                    pass

            if not profile_msg:
                return

            main_guild_id = self.config.logging_guild_id
            guild = self.bot.get_guild(main_guild_id) if main_guild_id else case_thread.guild
            member = guild.get_member(user_id) if guild else None

            embed = discord.Embed(
                title="📋 User Profile",
                color=EmbedColors.INFO,
                timestamp=datetime.now(NY_TZ),
            )

            if member:
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.add_field(name="Username", value=f"{member.name}", inline=True)
                embed.add_field(name="Display Name", value=f"{member.display_name}", inline=True)
            else:
                try:
                    user = await self.bot.fetch_user(user_id)
                    embed.set_thumbnail(url=user.display_avatar.url)
                    embed.add_field(name="Username", value=f"{user.name}", inline=True)
                    embed.add_field(name="Display Name", value=f"⚠️ Left Server", inline=True)
                except discord.NotFound:
                    embed.add_field(name="Username", value=f"Unknown", inline=True)
                    embed.add_field(name="Display Name", value=f"⚠️ User Not Found", inline=True)

            embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)

            mute_count = case.get("mute_count", 0)
            ban_count = case.get("ban_count", 0)

            embed.add_field(name="Total Mutes", value=f"`{mute_count}`", inline=True)
            embed.add_field(name="Total Bans", value=f"`{ban_count}`", inline=True)

            last_mute = case.get("last_mute_at")
            last_ban = case.get("last_ban_at")
            if last_mute or last_ban:
                last_action = max(filter(None, [last_mute, last_ban]))
                embed.add_field(
                    name="Last Action",
                    value=f"<t:{int(last_action)}:R>",
                    inline=True,
                )

            if mute_count >= 3 or ban_count >= 2:
                warnings = []
                if mute_count >= 3:
                    warnings.append(f"{mute_count} mutes")
                if ban_count >= 2:
                    warnings.append(f"{ban_count} bans")
                embed.add_field(
                    name="⚠️ Repeat Offender",
                    value=f"{', '.join(warnings)}",
                    inline=False,
                )

            previous_names = self.db.get_previous_names(user_id, limit=3)
            if previous_names:
                names_str = ", ".join(f"`{name}`" for name in previous_names)
                embed.add_field(name="Previous Names", value=names_str, inline=False)

            await safe_edit(profile_msg, embed=embed)

        except Exception as e:
            logger.warning("Profile Stats Update Failed", [
                ("Error", str(e)[:50]),
            ])

    async def _update_control_panel(
        self,
        case_id: str,
        case_thread: discord.Thread,
        new_status: Optional[str] = None,
        user: Optional[discord.Member] = None,
        moderator: Optional[discord.Member] = None,
        transcript_url: Optional[str] = None,
    ) -> bool:
        """
        Update the control panel message in place.

        Args:
            case_id: The case ID.
            case_thread: The case thread.
            new_status: New status (open, resolved, expired, approved).
            user: The target user.
            moderator: The moderator.
            transcript_url: URL to the transcript (for approved cases).

        Returns:
            True if updated successfully.
        """
        try:
            # Get case data
            case = self.db.get_case(case_id)
            if not case:
                logger.warning("Control Panel Update - Case Not Found", [
                    ("Case ID", case_id),
                ])
                return False

            control_panel_msg_id = case.get("control_panel_message_id")
            if not control_panel_msg_id:
                # No control panel, try to find it in pinned messages
                try:
                    pinned = await case_thread.pins()
                    for msg in pinned:
                        if msg.embeds and msg.embeds[0].title and "Control Panel" in msg.embeds[0].title:
                            control_panel_msg_id = msg.id
                            self.db.set_case_control_panel_message(case_id, msg.id)
                            logger.tree("Control Panel Found In Pins", [
                                ("Case ID", case_id),
                                ("Message ID", str(msg.id)),
                            ], emoji="📌")
                            break
                except Exception as e:
                    logger.warning("Control Panel Pin Search Failed", [
                        ("Case ID", case_id),
                        ("Error", str(e)[:50]),
                    ])

            if not control_panel_msg_id:
                logger.warning("Control Panel Not Found", [
                    ("Case ID", case_id),
                    ("Thread ID", str(case_thread.id)),
                ])
                return False

            # Fetch the message
            control_msg = await safe_fetch_message(case_thread, control_panel_msg_id)
            if not control_msg:
                logger.warning("Control Panel Message Fetch Failed", [
                    ("Case ID", case_id),
                    ("Message ID", str(control_panel_msg_id)),
                ])
                return False

            # Determine status
            status = new_status or case.get("status", "open")

            # Build updated embed
            control_embed = build_control_panel_embed(
                case=case,
                user=user,
                moderator=moderator,
                status=status,
            )

            # Build updated view
            action_type = case.get("action_type", "")
            is_mute = action_type in ("mute", "timeout")

            # Check if evidence exists for this case
            evidence_urls = self.db.get_case_evidence(case_id)
            has_evidence = len(evidence_urls) > 0

            # Build transcript URL if approved and not provided
            final_transcript_url = transcript_url
            if status == "approved" and not final_transcript_url:
                if self.config.case_transcript_base_url:
                    final_transcript_url = f"{self.config.case_transcript_base_url}/{case_id}"

            control_view = CaseControlPanelView(
                user_id=case.get("user_id"),
                guild_id=case.get("guild_id"),
                case_id=case_id,
                case_thread_id=case_thread.id,
                status=status,
                is_mute=is_mute,
                has_evidence=has_evidence,
                transcript_url=final_transcript_url,
            )

            # Edit the message
            await safe_edit(control_msg, embed=control_embed, view=control_view)

            logger.tree("Control Panel Updated", [
                ("Case ID", case_id),
                ("Status", status),
                ("Transcript URL", "Yes" if final_transcript_url else "No"),
            ], emoji="🎛️")

            return True

        except Exception as e:
            logger.warning("Control Panel Update Failed", [
                ("Case ID", case_id),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:50]),
            ])
            return False

    # =========================================================================
    # Forum & Thread Access
    # =========================================================================

    async def _get_forum(self) -> Optional[discord.ForumChannel]:
        """Get the case log forum channel with TTL-based caching."""
        if not self.config.case_log_forum_id:
            return None

        now = datetime.now(NY_TZ)

        if self._forum is not None and self._forum_cache_time is not None:
            if now - self._forum_cache_time < THREAD_CACHE_TTL:
                return self._forum

        channel = await safe_fetch_channel(self.bot, self.config.case_log_forum_id)
        if channel is None:
            logger.warning("Case Log Forum Not Found", [
                ("Forum ID", str(self.config.case_log_forum_id)),
            ])
            return None

        if isinstance(channel, discord.ForumChannel):
            self._forum = channel
            self._forum_cache_time = now
            return self._forum

        logger.warning("Invalid Case Log Forum Channel", [
            ("Channel ID", str(self.config.case_log_forum_id)),
            ("Expected", "ForumChannel"),
            ("Got", type(channel).__name__),
        ])
        return None

    async def _get_case_thread(self, thread_id: int) -> Optional[discord.Thread]:
        """Get a case thread by ID with TTL-based caching."""
        now = datetime.now(NY_TZ)

        if thread_id in self._thread_cache:
            cached_thread, cached_at = self._thread_cache[thread_id]
            if now - cached_at < THREAD_CACHE_TTL:
                return cached_thread
            else:
                try:
                    del self._thread_cache[thread_id]
                except KeyError:
                    pass

        channel = await safe_fetch_channel(self.bot, thread_id)
        if channel is None:
            logger.warning("Case Thread Not Found", [
                ("Thread ID", str(thread_id)),
            ])
            return None

        if isinstance(channel, discord.Thread):
            self._thread_cache[thread_id] = (channel, now)
            if len(self._thread_cache) > THREAD_CACHE_MAX_SIZE:
                try:
                    oldest = min(self._thread_cache.keys(), key=lambda k: self._thread_cache[k][1])
                    del self._thread_cache[oldest]
                except (KeyError, ValueError):
                    pass
            return channel

        logger.warning("Invalid Case Thread Channel", [
            ("Thread ID", str(thread_id)),
            ("Expected", "Thread"),
            ("Got", type(channel).__name__),
        ])
        return None

    # =========================================================================
    # Case Creation
    # =========================================================================

    async def _create_action_case(
        self,
        user: discord.User,
        moderator: discord.Member,
        action_type: str,
        reason: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        evidence: Optional[str] = None,
        message_url: Optional[str] = None,
    ) -> dict:
        """Create a new per-action case with its own forum thread."""
        case_id = self.db.get_next_case_id()
        guild_id = moderator.guild.id

        thread, control_panel_msg_id = await self._create_action_thread(
            user=user,
            case_id=case_id,
            action_type=action_type,
            moderator=moderator,
            duration_seconds=duration_seconds,
            reason=reason,
            message_url=message_url,
            guild_id=guild_id,
            has_evidence=bool(evidence),
        )

        if thread:
            self.db.create_case(
                case_id=case_id,
                user_id=user.id,
                guild_id=guild_id,
                thread_id=thread.id,
                action_type=action_type,
                moderator_id=moderator.id,
                reason=reason,
                duration_seconds=duration_seconds,
                evidence=evidence,
            )

            # Store control panel message ID if created
            if control_panel_msg_id:
                self.db.set_case_control_panel_message(case_id, control_panel_msg_id)

            self._thread_cache[thread.id] = (thread, datetime.now(NY_TZ))

            tag_names = [t.name for t in case_tags] if case_tags else []
            logger.tree("ACTION CASE CREATED", [
                ("User", user.name),
                ("ID", str(user.id)),
                ("Action", action_type.title()),
                ("Case ID", case_id),
                ("Thread ID", str(thread.id)),
                ("Tags", ", ".join(tag_names) if tag_names else "None"),
                ("Control Panel", "Yes" if control_panel_msg_id else "No"),
            ], emoji="📂")

            return {
                "case_id": case_id,
                "thread_id": thread.id,
                "action_type": action_type,
                "user_id": user.id,
                "control_panel_message_id": control_panel_msg_id,
            }

        logger.error(f"_create_action_case: Failed to create thread for {action_type} case, user {user.id}")
        raise RuntimeError(f"Failed to create {action_type} case thread")

    async def _create_action_thread(
        self,
        user: discord.User,
        case_id: str,
        action_type: str,
        moderator: Optional[discord.Member] = None,
        duration_seconds: Optional[int] = None,
        reason: Optional[str] = None,
        message_url: Optional[str] = None,
        guild_id: Optional[int] = None,
        has_evidence: bool = False,
    ) -> tuple[Optional[discord.Thread], Optional[int]]:
        """
        Create a new forum thread for a per-action case.

        Args:
            user: The target user.
            case_id: The case ID.
            action_type: Type of action (mute, ban, warn, etc).
            moderator: The moderator who took action.
            duration_seconds: Duration for timed actions.
            reason: Reason for the action.
            message_url: URL to the original message.
            guild_id: The guild ID.
            has_evidence: Whether evidence was provided.

        Returns:
            Tuple of (thread, control_panel_message_id)
        """
        forum = await self._get_forum()
        if not forum:
            logger.warning("Create Action Thread Failed", [
                ("Reason", "Forum not found"),
            ])
            return None, None

        now = datetime.now(NY_TZ)
        created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at

        user_embed = discord.Embed(
            title="📋 User Profile",
            color=EmbedColors.INFO,
            timestamp=now,
        )
        user_embed.set_thumbnail(url=user.display_avatar.url)
        user_embed.add_field(name="Username", value=f"{user.name}", inline=True)
        user_embed.add_field(
            name="Display Name",
            value=f"{user.display_name}" if hasattr(user, 'display_name') else user.name,
            inline=True,
        )
        user_embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)
        user_embed.add_field(
            name="Discord Joined",
            value=f"<t:{int(user.created_at.timestamp())}:F>",
            inline=True,
        )

        if hasattr(user, "joined_at") and user.joined_at:
            user_embed.add_field(
                name="Server Joined",
                value=f"<t:{int(user.joined_at.timestamp())}:F>",
                inline=True,
            )

        account_age = format_age(created_at, now)
        user_embed.add_field(name="Account Age", value=account_age, inline=True)

        previous_names = self.db.get_previous_names(user.id, limit=3)
        if previous_names:
            names_str = ", ".join(f"`{name}`" for name in previous_names)
            user_embed.add_field(name="Previous Names", value=names_str, inline=False)

        action_display = action_type.title()
        display_name = user.display_name if hasattr(user, 'display_name') else user.name
        thread_name = f"[{case_id}] | {action_display} | {display_name}"

        # Get tags for this case
        case_tags = self.get_tags_for_case(action_type, is_approved=False)

        try:
            thread_with_msg = await forum.create_thread(
                name=thread_name[:100],
                embed=user_embed,
                applied_tags=case_tags if case_tags else None,
            )

            try:
                if thread_with_msg.message:
                    await thread_with_msg.message.pin()
            except Exception as pin_error:
                logger.warning("Pin Profile Failed", [
                    ("Case ID", case_id),
                    ("Error", str(pin_error)[:50]),
                ])

            thread = thread_with_msg.thread
            control_panel_msg_id = None

            # Create and send control panel
            if thread and guild_id:
                try:
                    # Build case dict for control panel embed
                    case_data = {
                        "case_id": case_id,
                        "action_type": action_type,
                        "user_id": user.id,
                        "moderator_id": moderator.id if moderator else None,
                        "duration_seconds": duration_seconds,
                        "reason": reason,
                        "created_at": now.timestamp(),
                    }

                    # Build control panel embed
                    control_embed = build_control_panel_embed(
                        case=case_data,
                        user=user if isinstance(user, discord.Member) else None,
                        moderator=moderator,
                        status="open",
                    )

                    # Build control panel view
                    is_mute = action_type in ("mute", "timeout")
                    control_view = CaseControlPanelView(
                        user_id=user.id,
                        guild_id=guild_id,
                        case_id=case_id,
                        case_thread_id=thread.id,
                        status="open",
                        is_mute=is_mute,
                        message_url=message_url,
                        has_evidence=has_evidence,
                    )

                    # Send control panel
                    control_msg = await safe_send(thread, embed=control_embed, view=control_view)
                    if control_msg:
                        control_panel_msg_id = control_msg.id
                        # Pin the control panel
                        try:
                            await control_msg.pin()
                        except Exception as pin_error:
                            logger.warning("Pin Control Panel Failed", [
                                ("Case ID", case_id),
                                ("Error", str(pin_error)[:50]),
                            ])

                except Exception as cp_error:
                    logger.warning("Control Panel Creation Failed", [
                        ("Case ID", case_id),
                        ("Error", str(cp_error)[:50]),
                    ])

            return thread, control_panel_msg_id

        except Exception as e:
            logger.error(f"Failed to create action thread: {type(e).__name__}: {str(e)[:100]}")
            return None, None

    async def _send_evidence_request(
        self,
        case_id: str,
        thread: discord.Thread,
        moderator: discord.Member,
        action_type: str,
    ) -> Optional[discord.Message]:
        """
        Send a message requesting evidence for a case.

        The moderator should reply to this message with media (image/video)
        to provide evidence for the action.

        Args:
            case_id: The case ID.
            thread: The case thread.
            moderator: The moderator who took the action.
            action_type: Type of action (mute, ban, warn, etc.)

        Returns:
            The evidence request message, or None if failed.
        """
        try:
            embed = discord.Embed(
                title="⚠️ Evidence Required",
                description=(
                    f"Please provide evidence for this **{action_type}**.\n\n"
                    f"**Reply to this message** with an image or video.\n"
                    f"The media will be permanently linked to case `#{case_id}`."
                ),
                color=EmbedColors.WARNING,
            )
            embed.set_footer(text="Reply with media to complete this request")

            # Ping moderator outside embed so they see it
            msg = await safe_send(thread, content=f"{moderator.mention}", embed=embed)
            if msg:
                # Store the message ID so we can watch for replies
                self.db.set_case_evidence_request_message(case_id, msg.id)
                logger.tree("Evidence Request Sent", [
                    ("Case ID", case_id),
                    ("Thread", str(thread.id)),
                    ("Moderator", str(moderator)),
                ], emoji="⚠️")
                return msg

        except Exception as e:
            logger.error("Evidence Request Failed", [
                ("Case ID", case_id),
                ("Error", str(e)[:50]),
            ])

        return None

    async def handle_evidence_reply(
        self,
        message: discord.Message,
    ) -> bool:
        """
        Handle a reply to an evidence request message.

        This method is called when a message is detected as a reply
        to an evidence request. It captures the media and links it
        to the case.

        Args:
            message: The reply message with attachments.

        Returns:
            True if evidence was successfully captured.
        """
        if not message.reference or not message.reference.message_id:
            return False

        # Check if this is a reply to an evidence request
        case = self.db.get_case_by_evidence_request_message(message.reference.message_id)
        if not case:
            return False

        # Check for attachments
        valid_attachments = []
        for attachment in message.attachments:
            # Accept images and videos
            if attachment.content_type and (
                attachment.content_type.startswith("image/") or
                attachment.content_type.startswith("video/")
            ):
                valid_attachments.append(attachment)

        if not valid_attachments:
            # No valid media, send a reminder
            try:
                await message.reply(
                    "⚠️ Please provide an **image or video** as evidence.",
                    delete_after=10,
                )
            except Exception:
                pass
            return False

        # Re-upload attachments to ensure permanence
        evidence_urls = []
        thread = message.channel

        try:
            for attachment in valid_attachments:
                # Download the attachment
                file_data = await attachment.read()
                file = discord.File(
                    fp=io.BytesIO(file_data),
                    filename=attachment.filename,
                    description=f"Evidence for case #{case['case_id']}",
                )

                # Upload to the same thread (ensures permanence as long as thread exists)
                evidence_msg = await thread.send(
                    f"📎 **Evidence for Case #{case['case_id']}**",
                    file=file,
                )
                if evidence_msg and evidence_msg.attachments:
                    evidence_urls.append(evidence_msg.attachments[0].url)

            if evidence_urls:
                # Update the case with evidence URLs
                self.db.update_case_evidence(case["case_id"], evidence_urls)

                # Send confirmation
                await message.reply(
                    f"✅ Evidence captured for case `#{case['case_id']}` ({len(evidence_urls)} file(s)).",
                    delete_after=30,
                )

                # Delete the evidence request message
                try:
                    request_msg = await thread.fetch_message(message.reference.message_id)
                    await request_msg.delete()
                except Exception:
                    pass

                logger.tree("Evidence Captured", [
                    ("Case ID", case["case_id"]),
                    ("Files", str(len(evidence_urls))),
                    ("By", str(message.author)),
                ], emoji="✅")

                return True

        except Exception as e:
            logger.error("Evidence Capture Failed", [
                ("Case ID", case["case_id"]),
                ("Error", str(e)[:50]),
            ])

        return False

    async def _get_or_create_case(
        self,
        user: discord.Member,
        duration: Optional[str] = None,
        moderator_id: Optional[int] = None,
    ) -> dict:
        """LEGACY: Get existing case or create new one with forum thread."""
        case = self.db.get_case_log(user.id)
        if case:
            return case

        case_id = self.db.get_next_case_id()
        thread = await self._create_case_thread(user, case_id)

        if thread:
            self.db.create_case_log(user.id, case_id, thread.id, duration, moderator_id)
            self._thread_cache[thread.id] = (thread, datetime.now(NY_TZ))

            logger.tree("CASE THREAD CREATED", [
                ("User", user.name),
                ("ID", str(user.id)),
                ("Case ID", case_id),
                ("Thread ID", str(thread.id)),
            ], emoji="📂")

            return {
                "user_id": user.id,
                "case_id": case_id,
                "thread_id": thread.id,
                "just_created": True,
            }

        logger.error(f"_get_or_create_case: Failed to create thread for user {user.id}, case_id={case_id}")
        raise RuntimeError("Failed to create case thread")

    async def _create_case_thread(
        self,
        user: discord.Member,
        case_id: str,
    ) -> Optional[discord.Thread]:
        """LEGACY: Create a new forum thread for this case."""
        forum = await self._get_forum()
        if not forum:
            logger.warning("Create Case Thread Failed", [
                ("Reason", "Forum not found"),
            ])
            return None

        now = datetime.now(NY_TZ)
        created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at

        user_embed = discord.Embed(
            title="📋 User Profile",
            color=EmbedColors.INFO,
            timestamp=now,
        )
        user_embed.set_thumbnail(url=user.display_avatar.url)
        user_embed.add_field(name="Username", value=f"{user.name}", inline=True)
        user_embed.add_field(name="Display Name", value=f"{user.display_name}", inline=True)
        user_embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)
        user_embed.add_field(
            name="Discord Joined",
            value=f"<t:{int(user.created_at.timestamp())}:F>",
            inline=True,
        )

        if hasattr(user, "joined_at") and user.joined_at:
            user_embed.add_field(
                name="Server Joined",
                value=f"<t:{int(user.joined_at.timestamp())}:F>",
                inline=True,
            )

        account_age = format_age(created_at, now)
        user_embed.add_field(name="Account Age", value=account_age, inline=True)

        previous_names = self.db.get_previous_names(user.id, limit=3)
        if previous_names:
            names_str = ", ".join(f"`{name}`" for name in previous_names)
            user_embed.add_field(name="Previous Names", value=names_str, inline=False)

        thread_name = f"[{case_id}] | {user.display_name}"

        try:
            thread_with_msg = await forum.create_thread(
                name=thread_name[:100],
                embed=user_embed,
            )

            try:
                if thread_with_msg.message:
                    await thread_with_msg.message.pin()
                    self.db.set_profile_message_id(user.id, thread_with_msg.message.id)
            except Exception as pin_error:
                logger.warning("Pin User Profile Failed", [
                    ("Case ID", case_id),
                    ("Error", str(pin_error)[:50]),
                ])

            return thread_with_msg.thread

        except Exception as e:
            logger.error("Failed To Create Case Thread", [
                ("User", user.name),
                ("ID", str(user.id)),
                ("Case ID", case_id),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:100]),
            ])
            return None

    # =========================================================================
    # Reason Reply Handler
    # =========================================================================

    async def handle_reason_reply(self, message: discord.Message) -> bool:
        """Handle a reply message that might be a pending reason response."""
        if not message.reference or not message.reference.message_id:
            return False

        pending = self.db.get_pending_reason_by_thread(message.channel.id, message.author.id)
        if not pending:
            return False

        if message.reference.message_id != pending["warning_message_id"]:
            return False

        reason = message.content.strip()[:500]
        action_type = pending["action_type"]

        attachment_url = None
        if message.attachments:
            for att in message.attachments:
                if att.content_type and (att.content_type.startswith("image/") or att.content_type.startswith("video/")):
                    attachment_url = att.url
                    break

        is_voice_chat = reason and reason.lower().strip() in ("voice chat", "voicechat", "vc")

        if action_type in ("mute", "extension", "ban", "timeout"):
            if not attachment_url and not is_voice_chat:
                try:
                    await message.channel.send(
                        f"{message.author.mention} An attachment (screenshot/video) is required, or reply with `voice chat` if this happened in VC.",
                        delete_after=10,
                    )
                except discord.HTTPException as e:
                    logger.debug(f"Evidence requirement message failed: {message.channel.id} - {e.code}")
                return False
        else:
            if not reason:
                return False

        try:
            thread = message.channel
            embed_message = await safe_fetch_message(thread, pending["embed_message_id"])

            if not embed_message or not embed_message.embeds:
                return False

            embed = embed_message.embeds[0]

            # Update reason field
            reason_field_index = None
            for i, field in enumerate(embed.fields):
                if field.name == "Reason":
                    reason_field_index = i
                    break

            if is_voice_chat:
                vc_activity = self.db.get_recent_voice_activity(
                    pending["target_user_id"],
                    self.config.logging_guild_id,
                    limit=10,
                    max_age_seconds=3600,
                )
                if vc_activity:
                    vc_summary = []
                    for event in vc_activity[:5]:
                        event_type = event.get("event_type", "unknown")
                        channel = event.get("channel_name", "Unknown")
                        timestamp = event.get("timestamp", 0)
                        vc_summary.append(f"`{event_type}` {channel} <t:{int(timestamp)}:R>")

                    vc_text = "\n".join(vc_summary)
                    reason = f"Voice Chat Activity:\n{vc_text}"
                else:
                    reason = "Voice Chat (no recent activity found)"

            if reason_field_index is not None:
                embed.set_field_at(reason_field_index, name="Reason", value=f"`{reason}`", inline=False)
            else:
                embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

            if attachment_url:
                evidence_msg = await safe_send(thread, f"📎 Evidence: {attachment_url}")
                if evidence_msg:
                    has_evidence = False
                    for i, field in enumerate(embed.fields):
                        if field.name == "Evidence":
                            embed.set_field_at(i, name="Evidence", value=f"[View Evidence]({evidence_msg.jump_url})", inline=False)
                            has_evidence = True
                            break
                    if not has_evidence:
                        embed.add_field(name="Evidence", value=f"[View Evidence]({evidence_msg.jump_url})", inline=False)

            # Update the embed without buttons (control panel handles all controls)
            await safe_edit(embed_message, embed=embed)

            # Delete warning and reply
            try:
                warning_msg = await safe_fetch_message(thread, pending["warning_message_id"])
                if warning_msg:
                    await safe_delete(warning_msg)
                await safe_delete(message)
            except Exception:
                pass

            await safe_send(thread, f"✅ Reason updated by {message.author.mention}", delete_after=10)

            self.db.delete_pending_reason(pending["id"])

            logger.tree("Reason Reply Processed", [
                ("Moderator", message.author.name),
                ("Action", action_type),
                ("Has Attachment", str(bool(attachment_url))),
            ], emoji="✅")

            return True

        except Exception as e:
            logger.error("Handle Reason Reply Failed", [
                ("Error", str(e)[:100]),
            ])
            return False


# =============================================================================
# Exports
# =============================================================================

__all__ = ["CaseLogService"]
