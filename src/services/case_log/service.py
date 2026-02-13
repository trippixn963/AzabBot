"""
AzabBot - Case Log Service
==========================

Logging moderation actions to forum threads.

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
from src.utils.discord_rate_limit import log_http_error
from src.core.constants import DELETE_AFTER_MEDIUM, DELETE_AFTER_EXTENDED, QUERY_LIMIT_SMALL, PREVIOUS_NAMES_LIMIT

from .constants import (
    THREAD_CACHE_TTL,
    THREAD_CACHE_MAX_SIZE,
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
from .tags import CaseLogTagsMixin
from .scheduler import CaseLogSchedulerMixin
from .updates import CaseLogUpdatesMixin

if TYPE_CHECKING:
    from src.bot import AzabBot


class CaseLogService(
    CaseLogTagsMixin,
    CaseLogSchedulerMixin,
    CaseLogUpdatesMixin,
    CaseLogActionsMixin,
    CaseLogExtendedActionsMixin,
):
    """
    Service for logging moderation actions to forum threads.

    DESIGN:
        Each mute/ban/warn creates its own case and thread (per-action).
        Legacy per-user cases are supported for backward compatibility.
    """

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the case log service.

        Sets up forum caching, thread caching, pending reason scheduler,
        and profile update debouncing. Initializes all mixin components.

        Args:
            bot: Main bot instance for Discord API access.
        """
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

        if self.enabled:
            logger.tree("Case Log Service Created", [
                ("Forum ID", str(self.config.case_log_forum_id)),
                ("Thread Cache", f"Max {THREAD_CACHE_MAX_SIZE}"),
            ], emoji="📝")
        else:
            logger.debug("Case Log Service Disabled (no forum configured)")

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """
        Check if case logging is enabled.

        Returns:
            True if case_log_forum_id is configured, False otherwise.
        """
        return self.config.case_log_forum_id is not None

    def get_case_info(self, user_id: int) -> Optional[dict]:
        """
        Get case info for a user without logging or creating a case.

        This is a lightweight lookup that doesn't trigger case creation
        or any side effects. Used for checking if a case exists.

        Args:
            user_id: Discord user ID to look up.

        Returns:
            Dict with case_id and thread_id if case exists, None otherwise.
        """
        case = self.db.get_case_log(user_id)
        if case:
            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}
        return None

    async def prepare_case(self, user: discord.Member) -> Optional[dict]:
        """
        Prepare a case for a user (get existing or create new without logging action).

        This ensures a case exists for the user but doesn't log any specific
        moderation action. Used when you need a case thread ready before
        taking action.

        Args:
            user: Discord member to prepare case for.

        Returns:
            Dict with case_id and thread_id if successful, None if disabled or failed.
        """
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
    # Forum & Thread Access
    # =========================================================================

    async def _get_forum(self) -> Optional[discord.ForumChannel]:
        """
        Get the case log forum channel with TTL-based caching.

        Caches the forum channel reference to avoid repeated API calls.
        Cache expires after THREAD_CACHE_TTL to ensure we detect channel
        changes or deletions.

        Returns:
            ForumChannel if found and valid, None if not configured or not found.
        """
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
        """
        Get a case thread by ID with TTL-based caching.

        Maintains an LRU-style cache of thread objects with TTL expiration.
        When cache exceeds THREAD_CACHE_MAX_SIZE, evicts oldest entry.

        Args:
            thread_id: Discord thread ID to fetch.

        Returns:
            Thread object if found and valid, None if not found or invalid type.
        """
        now = datetime.now(NY_TZ)

        if thread_id in self._thread_cache:
            cached_thread, cached_at = self._thread_cache[thread_id]
            if now - cached_at < THREAD_CACHE_TTL:
                return cached_thread
            else:
                self._thread_cache.pop(thread_id, None)

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
                    self._thread_cache.pop(oldest, None)
                except ValueError:
                    pass  # Cache empty
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
        """
        Create a new per-action case with its own forum thread.

        DESIGN: Each moderation action (mute, ban, warn) gets its own case
        and thread. This is the modern approach that replaced per-user cases.

        Creates:
        - Database case record with unique case_id
        - Forum thread with user profile embed
        - Control panel with action buttons
        - Evidence request if needed

        Args:
            user: Target user for the moderation action.
            moderator: Moderator taking the action.
            action_type: Type of action (mute, ban, warn, timeout, etc).
            reason: Optional reason for the action.
            duration_seconds: Optional duration for timed actions.
            evidence: Optional evidence URL or description.
            message_url: Optional URL to the message that triggered action.

        Returns:
            Dict with case_id, thread_id, action_type, user_id, control_panel_message_id.

        Raises:
            RuntimeError: If thread creation fails.
        """
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

            # Get applied tags from thread for logging
            tag_names = [t.name for t in thread.applied_tags] if hasattr(thread, 'applied_tags') and thread.applied_tags else []
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

        logger.error("Action Case Thread Failed", [("Action", action_type), ("User", str(user.id))])
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

        previous_names = self.db.get_previous_names(user.id, limit=PREVIOUS_NAMES_LIMIT)
        if previous_names:
            names_str = ", ".join(f"`{name}`" for name in previous_names)
            user_embed.add_field(name="Previous Names", value=names_str, inline=False)

        display_name = user.display_name if hasattr(user, 'display_name') else user.name
        thread_name = f"[{case_id}] | {display_name} | {user.id}"

        # Get tags for this case
        case_tags = self.get_tags_for_case(action_type)

        try:
            thread_with_msg = await forum.create_thread(
                name=thread_name[:100],
                embed=user_embed,
                applied_tags=case_tags or [],
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
                        status="active",
                    )

                    # Build control panel view
                    is_mute = action_type in ("mute", "timeout")
                    control_view = CaseControlPanelView(
                        user_id=user.id,
                        guild_id=guild_id,
                        case_id=case_id,
                        case_thread_id=thread.id,
                        status="active",
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
            logger.error("Action Thread Creation Failed", [("Error", f"{type(e).__name__}: {str(e)[:100]}")])
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
        to provide evidence for the action. The message ID is stored in the
        database so we can detect replies to it.

        DESIGN: Evidence requests are skipped for the bot owner to streamline
        their workflow. All other moderators must provide evidence.

        Args:
            case_id: The case ID for tracking.
            thread: The case thread where request will be posted.
            moderator: The moderator who took the action.
            action_type: Type of action (mute, ban, warn, etc.) for context.

        Returns:
            The evidence request message if sent successfully, None if skipped or failed.
        """
        # Skip evidence request for developer/owner or bot auto-actions
        if self.config.owner_id and moderator.id == self.config.owner_id:
            return None
        if moderator.bot:
            return None

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

            msg = await safe_send(thread, embed=embed)
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
        to an evidence request. It validates attachments, uploads them
        to permanent storage (assets thread), and links them to the case.

        WORKFLOW:
        1. Check if reply is to an evidence request message
        2. Validate attachments (images/videos only)
        3. Upload to assets thread for permanent storage
        4. Update case database with evidence URLs
        5. Post reference in case thread
        6. Delete the evidence request message

        Args:
            message: The reply message with attachments.

        Returns:
            True if evidence was successfully captured and stored, False otherwise.
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
                    delete_after=DELETE_AFTER_MEDIUM,
                )
            except discord.HTTPException:
                pass
            return False

        # Upload attachments to assets thread for permanent storage
        evidence_urls = []
        thread = message.channel

        try:
            # Get assets thread for permanent storage
            assets_thread = None
            if self.config.transcript_assets_thread_id:
                try:
                    assets_thread = self.bot.get_channel(self.config.transcript_assets_thread_id)
                    if not assets_thread:
                        assets_thread = await self.bot.fetch_channel(self.config.transcript_assets_thread_id)
                except (discord.NotFound, discord.HTTPException):
                    pass

            for attachment in valid_attachments:
                # Download the attachment
                file_data = await attachment.read()
                file = discord.File(
                    fp=io.BytesIO(file_data),
                    filename=attachment.filename,
                    description=f"Evidence for case #{case['case_id']}",
                )

                # Upload to assets thread if available (permanent), otherwise case thread
                target_thread = assets_thread if assets_thread else thread
                evidence_msg = await target_thread.send(
                    f"📎 **Evidence for Case #{case['case_id']}**",
                    file=file,
                )
                if evidence_msg and evidence_msg.attachments:
                    evidence_urls.append(evidence_msg.attachments[0].url)

            if evidence_urls:
                # Update the case with evidence URLs
                self.db.update_case_evidence(case["case_id"], evidence_urls)

                # Also post a reference in the case thread
                evidence_links = "\n".join([f"[Evidence {i+1}]({url})" for i, url in enumerate(evidence_urls)])
                await thread.send(f"📎 **Evidence submitted** ({len(evidence_urls)} file(s)):\n{evidence_links}")

                # Send confirmation
                await message.reply(
                    f"✅ Evidence captured for case `#{case['case_id']}` ({len(evidence_urls)} file(s)).",
                    delete_after=DELETE_AFTER_EXTENDED,
                )

                # Delete the evidence request message
                try:
                    request_msg = await thread.fetch_message(message.reference.message_id)
                    await request_msg.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass

                logger.tree("Evidence Captured", [
                    ("Case ID", case["case_id"]),
                    ("Files", str(len(evidence_urls))),
                    ("By", str(message.author)),
                    ("Storage", "Assets Thread" if assets_thread else "Case Thread"),
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
        """
        LEGACY: Get existing case or create new one with forum thread.

        This is the old per-user case system where each user had one case
        thread for all their moderation actions. Kept for backward compatibility
        but new code should use _create_action_case instead.

        Args:
            user: Discord member to get/create case for.
            duration: Optional duration string for the case.
            moderator_id: Optional moderator ID who created the case.

        Returns:
            Dict with user_id, case_id, thread_id, and just_created flag.

        Raises:
            RuntimeError: If thread creation fails.
        """
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

        logger.error("Case Thread Creation Failed", [("User", str(user.id)), ("Case", case_id)])
        raise RuntimeError("Failed to create case thread")

    async def _create_case_thread(
        self,
        user: discord.Member,
        case_id: str,
    ) -> Optional[discord.Thread]:
        """
        LEGACY: Create a new forum thread for this case.

        Creates a per-user case thread with user profile embed.
        This is the old system - new code should use _create_action_thread.

        Args:
            user: Discord member to create thread for.
            case_id: Unique case ID for the thread name.

        Returns:
            Thread object if created successfully, None if failed.
        """
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

        previous_names = self.db.get_previous_names(user.id, limit=PREVIOUS_NAMES_LIMIT)
        if previous_names:
            names_str = ", ".join(f"`{name}`" for name in previous_names)
            user_embed.add_field(name="Previous Names", value=names_str, inline=False)

        thread_name = f"[{case_id}] | {user.display_name} | {user.id}"

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
        """
        Handle a reply message that might be a pending reason response.

        When a moderator takes action without providing a reason, the bot
        sends a warning message. This method detects replies to that warning
        and updates the case with the provided reason and optional evidence.

        WORKFLOW:
        1. Check if reply is to a pending reason warning
        2. Validate reason text and optional evidence attachment
        3. Handle special "voice chat" reason with activity lookup
        4. Update the case embed with reason and evidence
        5. Delete warning and reply messages
        6. Mark pending reason as resolved

        EVIDENCE REQUIREMENTS:
        - Mute/ban/timeout actions require image/video evidence OR "voice chat"
        - Other actions only require reason text

        Args:
            message: The reply message potentially containing reason/evidence.

        Returns:
            True if reason was successfully processed and case updated, False otherwise.
        """
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
                        delete_after=DELETE_AFTER_MEDIUM,
                    )
                except discord.HTTPException as e:
                    log_http_error(e, "Evidence Message", [("Channel", str(message.channel.id))])
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
                    self.config.main_guild_id,
                    limit=QUERY_LIMIT_SMALL,
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
            except discord.HTTPException:
                pass

            await safe_send(thread, f"✅ Reason updated by {message.author.mention}", delete_after=DELETE_AFTER_MEDIUM)

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
