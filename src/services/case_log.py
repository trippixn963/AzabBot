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
                logger.warning("Failed To Get Case Log Forum", [
                    ("Forum ID", str(self.config.case_log_forum_id)),
                    ("Error", str(e)[:50]),
                ])
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
            logger.warning("Case Thread Not Found", [
                ("Thread ID", str(thread_id)),
            ])
        except Exception as e:
            logger.warning("Failed To Get Case Thread", [
                ("Thread ID", str(thread_id)),
                ("Error", str(e)[:50]),
            ])
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
    ) -> None:
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
        """
        if not self.enabled:
            return

        try:
            case = await self._get_or_create_case(user, moderator, duration, reason)

            # If case was just created, mute embed was included in thread creation
            if case.get("just_created"):
                logger.tree("Case Log: New Case Created With Mute", [
                    ("User", f"{user.display_name} ({user.id})"),
                    ("Case ID", f"{case['case_id']:04d}"),
                    ("Thread ID", str(case["thread_id"])),
                    ("Muted By", f"{moderator.display_name}"),
                    ("Duration", duration),
                    ("Mute #", "1"),
                    ("Reason", reason if reason else "Not provided"),
                ], emoji="📋")

                # If no reason provided, ping moderator in the thread
                if not reason:
                    case_thread = await self._get_case_thread(case["thread_id"])
                    if case_thread:
                        await case_thread.send(
                            f"{moderator.mention} Please provide a reason for this mute."
                        )
                return

            # Existing case - increment mute count and send mute embed
            mute_count = self.db.increment_mute_count(user.id)

            case_thread = await self._get_case_thread(case["thread_id"])
            if case_thread:
                embed = self._build_mute_embed(user, moderator, duration, reason, mute_count)
                await case_thread.send(embed=embed)

                # If no reason provided, ping moderator
                if not reason:
                    await case_thread.send(
                        f"{moderator.mention} Please provide a reason for this mute."
                    )

                # Repeat offender alert at 3+ mutes
                is_permanent = duration.lower() in ("permanent", "perm", "forever")
                if mute_count >= 3 and not is_permanent:
                    alert_embed = discord.Embed(
                        title="⚠️ Repeat Offender Alert",
                        color=EmbedColors.WARNING,
                        description=f"**{user.display_name}** has been muted **{mute_count} times**.\n\nConsider a longer mute duration for this user.",
                    )
                    set_footer(alert_embed)
                    await case_thread.send(embed=alert_embed)

                logger.tree("Case Log: Mute Logged", [
                    ("User", f"{user.display_name} ({user.id})"),
                    ("Case ID", f"{case['case_id']:04d}"),
                    ("Muted By", f"{moderator.display_name}"),
                    ("Duration", duration),
                    ("Mute #", str(mute_count)),
                    ("Reason", reason if reason else "Not provided"),
                ], emoji="🔇")

        except Exception as e:
            logger.error("Case Log: Failed To Log Mute", [
                ("User ID", str(user.id)),
                ("Error", str(e)[:100]),
            ])

    # =========================================================================
    # Unmute Logging
    # =========================================================================

    async def log_unmute(
        self,
        user_id: int,
        moderator: discord.Member,
        display_name: str,
        reason: Optional[str] = None,
    ) -> None:
        """
        Log an unmute action to the user's case thread.

        Args:
            user_id: The user being unmuted.
            moderator: The moderator who issued the unmute.
            display_name: Display name of the user.
            reason: Optional reason for the unmute.
        """
        if not self.enabled:
            return

        try:
            case = self.db.get_case_log(user_id)
            if not case:
                # No case exists, nothing to log
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
                embed = self._build_unmute_embed(moderator, reason, user_avatar_url)
                await case_thread.send(embed=embed)

                # If no reason provided, ping moderator
                if not reason:
                    await case_thread.send(
                        f"{moderator.mention} Please provide a reason for this unmute."
                    )

                logger.tree("Case Log: Unmute Logged", [
                    ("User", f"{display_name} ({user_id})"),
                    ("Case ID", f"{case['case_id']:04d}"),
                    ("Unmuted By", f"{moderator.display_name}"),
                    ("Reason", reason if reason else "Not provided"),
                ], emoji="🔊")

        except Exception as e:
            logger.error("Case Log: Failed To Log Unmute", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])

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
                    ("Case ID", f"{case['case_id']:04d}"),
                ], emoji="⏰")

        except Exception as e:
            logger.error("Case Log: Failed To Log Mute Expiry", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:100]),
            ])

    # =========================================================================
    # Case Management
    # =========================================================================

    async def _get_or_create_case(
        self,
        user: discord.Member,
        moderator: discord.Member,
        duration: str,
        reason: Optional[str] = None,
    ) -> dict:
        """
        Get existing case or create new one with forum thread.

        Args:
            user: The user being muted.
            moderator: The moderator issuing the mute.
            duration: Duration display string.
            reason: Optional reason for the mute.

        Returns:
            Dict with case info, includes 'just_created' flag if new.
        """
        case = self.db.get_case_log(user.id)
        if case:
            return case  # Existing case

        # Create new case
        case_id = self.db.get_next_case_id()
        thread = await self._create_case_thread(user, case_id, moderator, duration, reason)

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
        case_id: int,
        moderator: discord.Member,
        duration: str,
        reason: Optional[str] = None,
    ) -> Optional[discord.Thread]:
        """
        Create a new forum thread for this case.

        DESIGN:
            Thread includes user profile embed + initial mute embed.
            User profile is pinned for easy reference.

        Args:
            user: The user being muted.
            case_id: The case number.
            moderator: The moderator issuing the mute.
            duration: Duration display string.
            reason: Optional reason for the mute.

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

        # Build initial mute embed
        mute_embed = self._build_mute_embed(user, moderator, duration, reason, mute_count=1)

        # Create thread
        thread_name = f"[{case_id:04d}] | {user.display_name}"

        try:
            thread_with_msg = await forum.create_thread(
                name=thread_name[:100],  # Discord limit
                embeds=[user_embed, mute_embed],
            )

            # Pin the first message (user profile)
            try:
                if thread_with_msg.message:
                    await thread_with_msg.message.pin()
            except Exception as pin_error:
                logger.warning("Failed To Pin User Profile", [
                    ("Case ID", str(case_id)),
                    ("Error", str(pin_error)[:50]),
                ])

            return thread_with_msg.thread

        except Exception as e:
            logger.error("Failed To Create Case Thread", [
                ("User", f"{user.display_name} ({user.id})"),
                ("Case ID", str(case_id)),
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
    ) -> discord.Embed:
        """
        Build a mute action embed.

        Args:
            user: The user being muted.
            moderator: The moderator who issued the mute.
            duration: Duration display string.
            reason: Optional reason for the mute.
            mute_count: The mute number for this user.

        Returns:
            Discord Embed for the mute action.
        """
        title = f"🔇 User Muted (Mute #{mute_count})" if mute_count > 1 else "🔇 User Muted"

        embed = discord.Embed(
            title=title,
            color=EmbedColors.ERROR,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Muted By", value=f"{moderator.mention}", inline=True)
        embed.add_field(name="Duration", value=f"`{duration}`", inline=True)

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
