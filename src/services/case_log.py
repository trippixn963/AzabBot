"""
Azab Discord Bot - Case Log Service
====================================

Service for logging mute/unmute actions to forum threads.

DESIGN:
    Each user gets a unique case thread when first muted.
    All subsequent mute/unmute events are logged to the same thread.
    Thread format: [XXXX] | Username

Features:
    - Unique case ID and thread per user
    - Mute/unmute events logged to same thread
    - Auto-unmutes (expired mutes) logged
    - Mute count tracked in embed titles
    - User profile pinned in first message

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# View Classes
# =============================================================================

class JumpToMessageView(discord.ui.View):
    """View with a button linking to the source message."""

    def __init__(self, message_url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="Jump to Message",
            url=message_url,
            style=discord.ButtonStyle.link,
            emoji="🔗",
        ))


# =============================================================================
# Case Log Service
# =============================================================================

class CaseLogService:
    """
    Service for logging moderation actions to forum threads.

    DESIGN:
        Each user gets a unique case thread where all mute/unmute events
        are logged. Thread persists across all moderation actions for
        that user.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
        db: Database manager.
        _forum: Cached forum channel reference.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the case log service.

        Args:
            bot: Main bot instance.
        """
        self.bot = bot
        self.config = get_config()
        self.db = get_db()
        self._forum: Optional[discord.ForumChannel] = None

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Check if case logging is enabled."""
        return self.config.case_log_forum_id is not None

    def get_case_info(self, user_id: int) -> Optional[dict]:
        """
        Get case info for a user without logging.

        Args:
            user_id: Discord user ID.

        Returns:
            Dict with case_id and thread_id, or None if no case exists.
        """
        case = self.db.get_case_log(user_id)
        if case:
            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}
        return None

    async def prepare_case(self, user: discord.Member) -> Optional[dict]:
        """
        Prepare a case for a user (get or create without logging).

        Use this to get case_id for embeds before calling log_mute.

        Args:
            user: The Discord member.

        Returns:
            Dict with case_id and thread_id, or None if disabled/failed.
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
    # Forum Access
    # =========================================================================

    async def _get_forum(self) -> Optional[discord.ForumChannel]:
        """
        Get the case log forum channel.

        DESIGN:
            Caches forum reference after first fetch.
            Returns None if forum ID not configured or channel not found.

        Returns:
            Forum channel or None.
        """
        if not self.config.case_log_forum_id:
            return None

        if self._forum is None:
            try:
                channel = self.bot.get_channel(self.config.case_log_forum_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(self.config.case_log_forum_id)
                if isinstance(channel, discord.ForumChannel):
                    self._forum = channel
            except Exception as e:
                logger.warning(f"Failed To Get Case Log Forum: {self.config.case_log_forum_id} - {str(e)[:50]}")
                return None

        return self._forum

    async def _get_case_thread(self, thread_id: int) -> Optional[discord.Thread]:
        """
        Get a case thread by ID.

        Args:
            thread_id: The thread ID.

        Returns:
            The thread, or None if not found.
        """
        try:
            thread = self.bot.get_channel(thread_id)
            if thread is None:
                thread = await self.bot.fetch_channel(thread_id)
            if isinstance(thread, discord.Thread):
                return thread
        except discord.NotFound:
            logger.warning(f"Case Thread Not Found: {thread_id}")
        except Exception as e:
            logger.warning(f"Failed To Get Case Thread: {thread_id} - {str(e)[:50]}")
        return None

    # =========================================================================
    # Mute Logging
    # =========================================================================

    async def log_mute(
        self,
        user: discord.Member,
        moderator: discord.Member,
        duration: str,
        reason: Optional[str] = None,
        source_message_url: Optional[str] = None,
        is_extension: bool = False,
        evidence: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Log a mute action to the user's case thread.

        DESIGN:
            Creates new case thread if user has no existing case.
            Increments mute count and logs event to existing case.

        Args:
            user: The user being muted.
            moderator: The moderator who issued the mute.
            duration: Duration display string.
            reason: Optional reason for the mute.
            source_message_url: Optional URL to the mute message in server.
            is_extension: Whether this is extending an existing mute.
            evidence: Optional evidence link or description.

        Returns:
            Dict with case_id and thread_id, or None if disabled/failed.
        """
        if not self.enabled:
            return None

        try:
            case = await self._get_or_create_case(user)
            case_thread = await self._get_case_thread(case["thread_id"])

            if not case_thread:
                return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

            # Determine mute count (don't increment for extensions)
            if case.get("just_created"):
                mute_count = 1
            elif is_extension:
                # Get current count without incrementing
                case_data = self.db.get_case_log(user.id)
                mute_count = case_data["mute_count"] if case_data else 1
            else:
                mute_count = self.db.increment_mute_count(user.id)

            # Build and send mute embed with jump button
            embed = self._build_mute_embed(user, moderator, duration, reason, mute_count, is_extension, evidence)

            if source_message_url:
                view = JumpToMessageView(source_message_url)
                await case_thread.send(embed=embed, view=view)
            else:
                await case_thread.send(embed=embed)

            # If no reason provided, ping moderator
            if not reason:
                await case_thread.send(
                    f"{moderator.mention} Please provide a reason for this {'extension' if is_extension else 'mute'}."
                )

            # Repeat offender alert at 3+ mutes (not for extensions)
            if not is_extension:
                is_permanent = duration.lower() in ("permanent", "perm", "forever")
                if mute_count >= 3 and not is_permanent:
                    alert_embed = discord.Embed(
                        title="⚠️ Repeat Offender Alert",
                        color=EmbedColors.WARNING,
                        description=f"**{user.display_name}** has been muted **{mute_count} times**.\n\nConsider a longer mute duration for this user.",
                    )
                    set_footer(alert_embed)
                    await case_thread.send(embed=alert_embed)

            if is_extension:
                log_type = "Mute Extended"
            elif case.get("just_created"):
                log_type = "New Case Created With Mute"
            else:
                log_type = "Mute Logged"

            logger.tree(f"Case Log: {log_type}", [
                ("User", f"{user.display_name} ({user.id})"),
                ("Case ID", case['case_id']),
                ("Muted By", f"{moderator.display_name}"),
                ("Duration", duration),
                ("Mute #", str(mute_count)),
                ("Reason", reason if reason else "Not provided"),
            ], emoji="🔇")

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Mute", [
                ("User ID", str(user.id)),
                ("Error", str(e)[:100]),
            ])
            return None

    # =========================================================================
    # Unmute Logging
    # =========================================================================

    async def log_unmute(
        self,
        user_id: int,
        moderator: discord.Member,
        display_name: str,
        reason: Optional[str] = None,
        source_message_url: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Log an unmute action to the user's case thread.

        Args:
            user_id: The user being unmuted.
            moderator: The moderator who issued the unmute.
            display_name: Display name of the user.
            reason: Optional reason for the unmute.
            source_message_url: Optional URL to the unmute message in server.

        Returns:
            Dict with case_id and thread_id, or None if no case exists.
        """
        if not self.enabled:
            return None

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                # No case exists, nothing to log
                return None

            # Update last unmute timestamp
            self.db.update_last_unmute(user_id)

            # Try to get user avatar
            user_avatar_url = None
            try:
                user = await self.bot.fetch_user(user_id)
                if user:
                    user_avatar_url = user.display_avatar.url
            except Exception:
                pass

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                embed = self._build_unmute_embed(moderator, reason, user_avatar_url)

                if source_message_url:
                    view = JumpToMessageView(source_message_url)
                    await case_thread.send(embed=embed, view=view)
                else:
                    await case_thread.send(embed=embed)

                # If no reason provided, ping moderator
                if not reason:
                    await case_thread.send(
                        f"{moderator.mention} Please provide a reason for this unmute."
                    )

                logger.tree("Case Log: Unmute Logged", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Case ID", case['case_id']),
                    ("Unmuted By", f"{moderator.display_name}"),
                    ("Reason", reason if reason else "Not provided"),
                ], emoji="🔊")

            return {"case_id": case["case_id"], "thread_id": case["thread_id"]}

        except Exception as e:
            logger.error("Case Log: Failed To Log Unmute", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])
            return None

    async def log_mute_expired(
        self,
        user_id: int,
        display_name: str,
    ) -> None:
        """
        Log an auto-unmute (expired mute) to the user's case thread.

        Args:
            user_id: The user whose mute expired.
            display_name: Display name of the user.
        """
        if not self.enabled:
            return

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                return

            # Update last unmute timestamp
            self.db.update_last_unmute(user_id)

            # Try to get user avatar
            user_avatar_url = None
            try:
                user = await self.bot.fetch_user(user_id)
                if user:
                    user_avatar_url = user.display_avatar.url
            except Exception:
                pass

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                embed = self._build_expired_embed(user_avatar_url)
                await case_thread.send(embed=embed)

                logger.tree("Case Log: Mute Expiry Logged", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Case ID", case['case_id']),
                ], emoji="⏰")

        except Exception as e:
            logger.error("Case Log: Failed To Log Mute Expiry", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])

    async def log_member_left_muted(
        self,
        user_id: int,
        display_name: str,
        muted_at: float,
    ) -> None:
        """
        Log when a muted user leaves the server.

        Args:
            user_id: The user who left.
            display_name: Display name of the user.
            muted_at: Timestamp when the user was muted.
        """
        if not self.enabled:
            return

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                return

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                embed = discord.Embed(
                    title="🚪 Left Server While Muted",
                    description="User left the server with an active mute.",
                    color=EmbedColors.WARNING,
                )

                now = datetime.now(NY_TZ)
                embed.add_field(
                    name="Left At",
                    value=f"<t:{int(now.timestamp())}:F>",
                    inline=True,
                )

                # Calculate time since muted
                time_since_mute = now.timestamp() - muted_at
                duration_str = self._format_duration_precise(time_since_mute)
                embed.add_field(
                    name="Time After Mute",
                    value=f"`{duration_str}`",
                    inline=True,
                )

                set_footer(embed)
                await case_thread.send(embed=embed)

                logger.tree("Case Log: Member Left Muted", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Case ID", case['case_id']),
                    ("Left After", duration_str),
                ], emoji="🚪")

        except Exception as e:
            logger.error("Case Log: Failed To Log Member Left", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])

    def _format_duration_precise(self, seconds: float) -> str:
        """
        Format duration with precision (seconds, minutes, hours, days).

        Args:
            seconds: Duration in seconds.

        Returns:
            Human-readable duration string.
        """
        seconds = int(seconds)

        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''}"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        elif seconds < 86400:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if minutes > 0:
                return f"{hours}h {minutes}m"
            return f"{hours} hour{'s' if hours != 1 else ''}"
        else:
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            if hours > 0:
                return f"{days}d {hours}h"
            return f"{days} day{'s' if days != 1 else ''}"

    async def log_mute_evasion_return(
        self,
        member: discord.Member,
        moderator_ids: list[int],
    ) -> None:
        """
        Log when a muted user rejoins the server (mute evasion attempt).

        Pings all moderators who muted/extended this user.

        Args:
            member: The member who rejoined.
            moderator_ids: List of moderator IDs who muted this user.
        """
        if not self.enabled:
            return

        try:
            case = self.db.get_case_log(member.id)
            if not case:
                return

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                embed = discord.Embed(
                    title="⚠️ Rejoined While Muted",
                    description="User rejoined the server with an active mute. Muted role has been re-applied.",
                    color=EmbedColors.WARNING,
                )

                embed.set_thumbnail(url=member.display_avatar.url)

                now = datetime.now(NY_TZ)
                embed.add_field(
                    name="Time",
                    value=f"<t:{int(now.timestamp())}:F>",
                    inline=True,
                )

                set_footer(embed)
                await case_thread.send(embed=embed)

                # Ping all moderators who muted this user
                if moderator_ids:
                    pings = " ".join(f"<@{mod_id}>" for mod_id in moderator_ids)
                    await case_thread.send(f"🔔 {pings}")

                logger.tree("Case Log: Mute Evasion Return", [
                    ("User", f"{member} ({member.id})"),
                    ("Case ID", case['case_id']),
                    ("Mods Pinged", str(len(moderator_ids))),
                ], emoji="⚠️")

        except Exception as e:
            logger.error("Case Log: Failed To Log Mute Evasion", [
                ("User ID", str(member.id)),
                ("Error", str(e)[:100]),
            ])

    async def log_muted_vc_violation(
        self,
        user_id: int,
        display_name: str,
        channel_name: str,
    ) -> None:
        """
        Log when a muted user attempts to join voice and gets timed out.

        Args:
            user_id: The user's Discord ID.
            display_name: The user's display name.
            channel_name: The voice channel they attempted to join.
        """
        if not self.enabled:
            return

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                return

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                embed = discord.Embed(
                    title="🔇 Voice Channel Violation",
                    description="User attempted to join a voice channel while muted. They have been disconnected and given a 1-hour timeout.",
                    color=EmbedColors.ERROR,
                )

                now = datetime.now(NY_TZ)
                embed.add_field(
                    name="Attempted Channel",
                    value=f"🔊 {channel_name}",
                    inline=True,
                )
                embed.add_field(
                    name="Action Taken",
                    value="Disconnected + 1h Timeout",
                    inline=True,
                )
                embed.add_field(
                    name="Time",
                    value=f"<t:{int(now.timestamp())}:F>",
                    inline=True,
                )

                set_footer(embed)
                await case_thread.send(embed=embed)

                logger.tree("Case Log: VC Violation", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Case ID", case['case_id']),
                    ("Channel", channel_name),
                ], emoji="🔇")

        except Exception as e:
            logger.error("Case Log: Failed To Log VC Violation", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])

    # =========================================================================
    # Case Management
    # =========================================================================

    async def _get_or_create_case(
        self,
        user: discord.Member,
    ) -> dict:
        """
        Get existing case or create new one with forum thread.

        Args:
            user: The user to get/create case for.

        Returns:
            Dict with case info, includes 'just_created' flag if new.
        """
        case = self.db.get_case_log(user.id)
        if case:
            return case  # Existing case

        # Create new case
        case_id = self.db.get_next_case_id()
        thread = await self._create_case_thread(user, case_id)

        if thread:
            self.db.create_case_log(user.id, case_id, thread.id)
            return {
                "user_id": user.id,
                "case_id": case_id,
                "thread_id": thread.id,
                "just_created": True,
            }

        raise RuntimeError("Failed to create case thread")

    async def _create_case_thread(
        self,
        user: discord.Member,
        case_id: str,
    ) -> Optional[discord.Thread]:
        """
        Create a new forum thread for this case.

        DESIGN:
            Thread includes user profile embed only.
            Mute embed is sent separately to include jump button.
            User profile is pinned for easy reference.

        Args:
            user: The user the case is for.
            case_id: The unique 4-character alphanumeric case ID.

        Returns:
            The created thread, or None on failure.
        """
        forum = await self._get_forum()
        if not forum:
            return None

        # Build user profile embed
        user_embed = discord.Embed(
            title="📋 User Profile",
            color=EmbedColors.INFO,
        )
        user_embed.set_thumbnail(url=user.display_avatar.url)
        user_embed.add_field(name="Username", value=f"{user.name}", inline=True)
        user_embed.add_field(name="Display Name", value=f"{user.display_name}", inline=True)
        user_embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)

        # Discord account creation date
        user_embed.add_field(
            name="Discord Joined",
            value=f"<t:{int(user.created_at.timestamp())}:F>",
            inline=True,
        )

        # Server join date
        if hasattr(user, "joined_at") and user.joined_at:
            user_embed.add_field(
                name="Server Joined",
                value=f"<t:{int(user.joined_at.timestamp())}:F>",
                inline=True,
            )

        # Account age
        now = datetime.now(NY_TZ)
        created_at = user.created_at.replace(tzinfo=NY_TZ) if user.created_at.tzinfo is None else user.created_at
        account_age = self._format_age(created_at, now)
        user_embed.add_field(name="Account Age", value=account_age, inline=True)

        set_footer(user_embed)

        # Create thread with user profile only
        thread_name = f"[{case_id}] | {user.display_name}"

        try:
            thread_with_msg = await forum.create_thread(
                name=thread_name[:100],  # Discord limit
                embed=user_embed,
            )

            # Pin the first message (user profile)
            try:
                if thread_with_msg.message:
                    await thread_with_msg.message.pin()
            except Exception as pin_error:
                logger.warning(f"Failed To Pin User Profile: Case {case_id} - {str(pin_error)[:50]}")

            return thread_with_msg.thread

        except Exception as e:
            logger.error("Failed To Create Case Thread", [
                ("User", f"{user.display_name} ({user.id})"),
                ("Case ID", case_id),
                ("Error", str(e)[:100]),
            ])
            return None

    # =========================================================================
    # Embed Builders
    # =========================================================================

    def _build_mute_embed(
        self,
        user: discord.Member,
        moderator: discord.Member,
        duration: str,
        reason: Optional[str] = None,
        mute_count: int = 1,
        is_extension: bool = False,
        evidence: Optional[str] = None,
    ) -> discord.Embed:
        """
        Build a mute action embed.

        Args:
            user: The user being muted.
            moderator: The moderator who issued the mute.
            duration: Duration display string.
            reason: Optional reason for the mute.
            mute_count: The mute number for this user.
            is_extension: Whether this is a mute extension.
            evidence: Optional evidence link or description.

        Returns:
            Discord Embed for the mute action.
        """
        if is_extension:
            title = "🔇 Mute Extended"
        elif mute_count > 1:
            title = f"🔇 User Muted (Mute #{mute_count})"
        else:
            title = "🔇 User Muted"

        embed = discord.Embed(
            title=title,
            color=EmbedColors.ERROR,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Muted By", value=f"`{moderator.display_name}`", inline=True)
        embed.add_field(name="Duration", value=f"`{duration}`", inline=True)

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:f>",
            inline=True,
        )

        if reason:
            embed.add_field(name="Reason", value=f"`{reason}`", inline=False)

        if evidence:
            embed.add_field(name="Evidence", value=evidence, inline=False)

        set_footer(embed)
        return embed

    def _build_unmute_embed(
        self,
        moderator: discord.Member,
        reason: Optional[str] = None,
        user_avatar_url: Optional[str] = None,
    ) -> discord.Embed:
        """
        Build an unmute action embed.

        Args:
            moderator: The moderator who issued the unmute.
            reason: Optional reason for the unmute.
            user_avatar_url: Avatar URL of the unmuted user.

        Returns:
            Discord Embed for the unmute action.
        """
        embed = discord.Embed(
            title="🔊 User Unmuted",
            color=EmbedColors.SUCCESS,
        )
        if user_avatar_url:
            embed.set_thumbnail(url=user_avatar_url)
        embed.add_field(name="Unmuted By", value=f"{moderator.mention}", inline=True)

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:f>",
            inline=True,
        )

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        set_footer(embed)
        return embed

    def _build_expired_embed(
        self,
        user_avatar_url: Optional[str] = None,
    ) -> discord.Embed:
        """
        Build a mute expired (auto-unmute) embed.

        Args:
            user_avatar_url: Avatar URL of the user whose mute expired.

        Returns:
            Discord Embed for the expiry.
        """
        embed = discord.Embed(
            title="⏰ Mute Expired (Auto-Unmute)",
            color=EmbedColors.INFO,
        )
        if user_avatar_url:
            embed.set_thumbnail(url=user_avatar_url)

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:f>",
            inline=True,
        )

        set_footer(embed)
        return embed

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _format_age(self, start: datetime, end: datetime) -> str:
        """
        Format age as years, months, and days.

        Args:
            start: Start datetime.
            end: End datetime.

        Returns:
            Formatted string like "1y 6m 15d".
        """
        total_days = (end - start).days

        years = total_days // 365
        remaining_days = total_days % 365
        months = remaining_days // 30
        days = remaining_days % 30

        parts = []
        if years > 0:
            parts.append(f"{years}y")
        if months > 0:
            parts.append(f"{months}m")
        if days > 0 or not parts:
            parts.append(f"{days}d")

        return " ".join(parts)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["CaseLogService"]
