"""
Azab Discord Bot - Server Logging Service
==========================================

Comprehensive server activity logging using a forum channel with categorized threads.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Dict, List, Tuple, Union
import asyncio
import io
import re

import aiohttp
import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.core.constants import EMOJI_USERID, SECONDS_PER_DAY, SECONDS_PER_HOUR
from src.utils.views import DownloadButton, OldAvatarButton, NewAvatarButton, CASE_EMOJI, DOWNLOAD_EMOJI
from src.utils.rate_limiter import rate_limit
from src.utils.async_utils import create_safe_task

# Import from local package
from .categories import LogCategory, THREAD_DESCRIPTIONS

if TYPE_CHECKING:
    from src.bot import AzabBot


# Alias for backward compatibility
USERID_EMOJI = EMOJI_USERID

# =============================================================================
# Persistent Views
# =============================================================================

class UserIdButton(discord.ui.DynamicItem[discord.ui.Button], template=r"log_userid:(?P<user_id>\d+)"):
    """Button that shows a user's ID in a copyable format."""

    def __init__(self, user_id: int):
        super().__init__(
            discord.ui.Button(
                label="UserID",
                style=discord.ButtonStyle.secondary,
                emoji=USERID_EMOJI,
                custom_id=f"log_userid:{user_id}",
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "UserIdButton":
        """Reconstruct the button from the custom_id regex match."""
        user_id = int(match.group("user_id"))
        return cls(user_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Send user ID as plain text (not embed) for mobile copy support."""
        await interaction.response.send_message(
            f"`{self.user_id}`",
            ephemeral=True,
        )


class LogView(discord.ui.View):
    """Persistent view for log embeds with Case, UserID, and Download buttons."""

    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=None)

        # Check if user has an open case - add Case button first if so
        db = get_db()
        case = db.get_case_log(user_id)
        if case:
            case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
            self.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))

        self.add_item(UserIdButton(user_id))
        self.add_item(DownloadButton(user_id))


# Custom emojis for log buttons
TRANSCRIPT_EMOJI = discord.PartialEmoji(name="transcript", id=1455205892319481916)
TICKET_EMOJI = discord.PartialEmoji(name="ticket", id=1455177168098295983)
MESSAGE_EMOJI = discord.PartialEmoji(name="message", id=1452783032460247150)


class ReactionLogView(discord.ui.View):
    """View for reaction logs with Jump, UserID, and Avatar buttons."""

    def __init__(self, user_id: int, guild_id: int, message_url: str):
        super().__init__(timeout=None)

        # Jump to message button first
        self.add_item(discord.ui.Button(
            label="Message",
            url=message_url,
            style=discord.ButtonStyle.link,
            emoji=MESSAGE_EMOJI,
        ))

        # Check if user has an open case
        db = get_db()
        case = db.get_case_log(user_id)
        if case:
            case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
            self.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))

        self.add_item(UserIdButton(user_id))
        self.add_item(DownloadButton(user_id))


class MessageLogView(discord.ui.View):
    """View for message logs with optional Jump, UserID, and Avatar buttons."""

    def __init__(self, user_id: int, guild_id: int, message_url: Optional[str] = None):
        super().__init__(timeout=None)

        # Jump to message button first (if URL provided - for edits, not deletes)
        if message_url:
            self.add_item(discord.ui.Button(
                label="Message",
                url=message_url,
                style=discord.ButtonStyle.link,
                emoji=MESSAGE_EMOJI,
            ))

        # Check if user has an open case
        db = get_db()
        case = db.get_case_log(user_id)
        if case:
            case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
            self.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))

        self.add_item(UserIdButton(user_id))
        self.add_item(DownloadButton(user_id))


class ModActionLogView(discord.ui.View):
    """View for mod action logs with Case button support."""

    def __init__(self, user_id: int, guild_id: int, case_id: Optional[str] = None):
        super().__init__(timeout=None)

        db = get_db()

        # Add Case button if case_id provided - look up thread_id
        if case_id:
            case = db.get_case(case_id)
            if case and case.get("thread_id"):
                case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
                self.add_item(discord.ui.Button(
                    label="Case",
                    url=case_url,
                    style=discord.ButtonStyle.link,
                    emoji=CASE_EMOJI,
                ))

        self.add_item(UserIdButton(user_id))
        self.add_item(DownloadButton(user_id))


class TranscriptLinkView(discord.ui.View):
    """View with a link button to open transcript in browser."""

    def __init__(self, transcript_url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="Transcript",
            url=transcript_url,
            style=discord.ButtonStyle.link,
            emoji=TRANSCRIPT_EMOJI,
        ))


class TicketLogView(discord.ui.View):
    """View with Open Ticket button for ticket logs."""

    def __init__(self, guild_id: int, thread_id: int):
        super().__init__(timeout=None)
        ticket_url = f"https://discord.com/channels/{guild_id}/{thread_id}"
        self.add_item(discord.ui.Button(
            label="Open Ticket",
            url=ticket_url,
            style=discord.ButtonStyle.link,
            emoji=TICKET_EMOJI,
        ))


def setup_log_views(bot: "AzabBot") -> None:
    """Register persistent views for log buttons. Call this on bot startup."""
    # Add dynamic views for log buttons
    bot.add_dynamic_items(UserIdButton)
    bot.add_dynamic_items(OldAvatarButton)
    bot.add_dynamic_items(NewAvatarButton)


# =============================================================================
# Logging Service
# =============================================================================

class LoggingService:
    """
    Server activity logging service using forum threads.

    DESIGN:
        Creates and manages 15 threads in a forum channel, one per category.
        Each log type is routed to the appropriate thread.
        Embeds are consistent and include timestamps.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
        _forum: Cached forum channel reference.
        _threads: Cached thread references by category.
    """

    def __init__(self, bot: "AzabBot") -> None:
        """Initialize the logging service."""
        self.bot = bot
        self.config = get_config()
        self._forum: Optional[discord.ForumChannel] = None
        self._threads: Dict[LogCategory, discord.Thread] = {}
        self._initialized = False

        logger.tree("Logging Service Created", [
            ("Enabled", str(self.enabled)),
            ("Guild Filter", str(self.config.logging_guild_id) if self.config.logging_guild_id else "None (all guilds)"),
        ], emoji="📋")

    @property
    def enabled(self) -> bool:
        """Check if logging is enabled."""
        return self.config.server_logs_forum_id is not None

    def _should_log(self, guild_id: Optional[int], user_id: Optional[int] = None) -> bool:
        """Check if we should log for this guild and user."""
        if not self.enabled:
            return False
        if guild_id is None:
            return False
        # Skip ignored bots (configured via IGNORED_BOT_IDS env var)
        if user_id and self.config.ignored_bot_ids and user_id in self.config.ignored_bot_ids:
            return False
        # If logging_guild_id is set, only log for that guild
        if self.config.logging_guild_id:
            return guild_id == self.config.logging_guild_id
        return True  # No filter, log all guilds

    def _format_channel(self, channel) -> str:
        """Format channel reference as clickable mention."""
        if channel is None:
            return "#unknown"
        try:
            if hasattr(channel, 'id'):
                return f"<#{channel.id}>"
            elif hasattr(channel, 'name') and channel.name:
                return f"#{channel.name}"
            else:
                return "#unknown"
        except Exception:
            return "#unknown"

    def _format_role(self, role) -> str:
        """Format role reference with fallback to name."""
        if role is None:
            return "unknown role"
        try:
            if hasattr(role, 'name') and role.name:
                return f"`{role.name}`"
            elif hasattr(role, 'id'):
                return f"`role-{role.id}`"
            else:
                return "unknown role"
        except Exception:
            return "unknown role"

    # =========================================================================
    # Initialization
    # =========================================================================

    async def initialize(self) -> bool:
        """
        Initialize the logging service by setting up forum and threads.

        Returns:
            True if initialization succeeded.
        """
        if not self.enabled:
            logger.info("Logging Service disabled (no forum ID configured)")
            return False

        try:
            # Get forum channel
            self._forum = self.bot.get_channel(self.config.server_logs_forum_id)
            if not self._forum or not isinstance(self._forum, discord.ForumChannel):
                logger.warning(f"Logging Service: Forum channel not found: {self.config.server_logs_forum_id}")
                return False

            # Get or create threads for each category
            await self._setup_threads()

            # Validate thread sync
            sync_issues = await self._validate_threads()

            self._initialized = True
            log_items = [
                ("Forum", self._forum.name),
                ("Threads", f"{len(self._threads)}/{len(LogCategory)}"),
            ]
            if sync_issues:
                log_items.append(("Sync Issues", str(len(sync_issues))))
                logger.tree("Logging Service Initialized (with issues)", log_items, emoji="⚠️")
            else:
                logger.tree("Logging Service Initialized", log_items, emoji="✅")

            return True

        except Exception as e:
            logger.warning(f"Logging Service: Init failed: {e}")
            return False

    async def _setup_threads(self) -> None:
        """Set up all category threads."""
        if not self._forum:
            return

        # Get existing threads
        existing_threads = {}
        for thread in self._forum.threads:
            existing_threads[thread.name] = thread

        # Also check archived threads
        async for thread in self._forum.archived_threads(limit=50):
            existing_threads[thread.name] = thread

        # Create or get thread for each category
        for category in LogCategory:
            thread_name = category.value

            if thread_name in existing_threads:
                thread = existing_threads[thread_name]
                # Unarchive if needed
                if thread.archived:
                    try:
                        await thread.edit(archived=False)
                    except Exception:
                        pass
                self._threads[category] = thread
            else:
                # Create new thread
                try:
                    thread = await self._forum.create_thread(
                        name=thread_name,
                        content=THREAD_DESCRIPTIONS.get(category, "Server activity logs"),
                    )
                    self._threads[category] = thread.thread
                    await rate_limit("thread_create")
                except Exception as e:
                    logger.warning(f"Logging Service: Failed to create thread {thread_name}: {e}")

    async def _validate_threads(self) -> List[str]:
        """
        Validate that all log category threads exist and are synced.

        Returns:
            List of issue descriptions (empty if all valid).
        """
        issues: List[str] = []

        if not self._forum:
            issues.append("Forum channel not available")
            return issues

        # Check for missing categories
        for category in LogCategory:
            if category not in self._threads:
                issues.append(f"Missing thread: {category.value}")
                logger.warning(f"Logging Service: Missing thread for {category.value}")

        # Check for extra threads not matching any category
        category_names = {cat.value for cat in LogCategory}

        # Get all active threads
        forum_threads = list(self._forum.threads)

        # Also check archived threads
        try:
            async for thread in self._forum.archived_threads(limit=50):
                forum_threads.append(thread)
        except Exception:
            pass

        for thread in forum_threads:
            if thread.name not in category_names:
                issues.append(f"Extra thread: {thread.name}")
                logger.info(f"Logging Service: Unrecognized thread '{thread.name}' in forum")

        # Log summary
        if issues:
            logger.tree("Thread Sync Validation", [
                ("Total Categories", str(len(LogCategory))),
                ("Loaded Threads", str(len(self._threads))),
                ("Issues Found", str(len(issues))),
            ], emoji="⚠️")
        else:
            logger.tree("Thread Sync Validation", [
                ("Status", "All threads synced"),
                ("Categories", str(len(LogCategory))),
            ], emoji="✅")

        return issues

    # =========================================================================
    # Helpers
    # =========================================================================

    def _create_embed(
        self,
        title: str,
        color: int,
        description: Optional[str] = None,
        category: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> discord.Embed:
        """Create a standardized log embed."""
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(NY_TZ),
        )
        # Build footer with category and user ID
        footer_parts = []
        if category:
            footer_parts.append(category)
        if user_id:
            footer_parts.append(f"ID: {user_id}")
        footer_text = " • ".join(footer_parts) if footer_parts else datetime.now(NY_TZ).strftime("%B %d, %Y")
        embed.set_footer(text=footer_text)
        return embed

    def _format_user_field(self, user: Union[discord.User, discord.Member]) -> str:
        """Format user field inline without ID (ID goes in footer)."""
        return f"{user.mention} · {user.name}"

    def _format_reason(self, reason: Optional[str]) -> str:
        """Format reason field with code block."""
        if not reason:
            return "```No reason provided```"
        # Truncate long reasons
        if len(reason) > 500:
            reason = reason[:497] + "..."
        return f"```{reason}```"

    def _format_duration_precise(self, seconds: int) -> str:
        """
        Format duration with precision (seconds, minutes, hours, days, etc).

        Args:
            seconds: Duration in seconds.

        Returns:
            Human-readable duration string.
        """
        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''}"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            if secs > 0:
                return f"{minutes}m {secs}s"
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        elif seconds < 86400:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if minutes > 0:
                return f"{hours}h {minutes}m"
            return f"{hours} hour{'s' if hours != 1 else ''}"
        elif seconds < 2592000:  # Less than 30 days
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            if hours > 0:
                return f"{days}d {hours}h"
            return f"{days} day{'s' if days != 1 else ''}"
        elif seconds < 31536000:  # Less than 365 days
            months = seconds // 2592000
            days = (seconds % 2592000) // 86400
            if days > 0:
                return f"{months}mo {days}d"
            return f"{months} month{'s' if months != 1 else ''}"
        else:
            years = seconds // 31536000
            remaining_days = (seconds % 31536000) // 86400
            if remaining_days > 0:
                return f"{years}y {remaining_days}d"
            return f"{years} year{'s' if years != 1 else ''}"

    def _set_user_thumbnail(self, embed: discord.Embed, user: Union[discord.User, discord.Member]) -> None:
        """Set user avatar as thumbnail if available."""
        try:
            if user.display_avatar:
                embed.set_thumbnail(url=user.display_avatar.url)
        except Exception:
            pass

    async def _send_log(
        self,
        category: LogCategory,
        embed: discord.Embed,
        files: Optional[List[discord.File]] = None,
        user_id: Optional[int] = None,
        view: Optional[discord.ui.View] = None,
    ) -> Optional[discord.Message]:
        """Send a log to the appropriate thread. Returns the message if successful."""
        if not self._initialized or category not in self._threads:
            return None

        try:
            thread = self._threads[category]
            # Use provided view, or create LogView if user_id provided
            if view is None and user_id:
                view = LogView(user_id, thread.guild.id)
            message = await thread.send(embed=embed, files=files or [], view=view)
            return message
        except discord.Forbidden:
            return None
        except Exception as e:
            logger.warning(f"Logging Service: Send failed: {e}")
            return None

    # =========================================================================
    # Bans & Kicks
    # =========================================================================

    async def log_ban(
        self,
        user: discord.User,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log a ban."""
        if not self.enabled:
            return

        embed = self._create_embed("🔨 Member Banned", EmbedColors.LOG_NEGATIVE, category="Ban", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)

        # Add prior actions context
        if self.config.logging_guild_id:
            db = get_db()
            counts = db.get_user_case_counts(user.id, self.config.logging_guild_id)
            if counts["mute_count"] or counts["ban_count"] or counts["warn_count"]:
                prior = f"🔇 `{counts['mute_count']}` mutes · 🔨 `{counts['ban_count']}` bans · ⚠️ `{counts['warn_count']}` warns"
                embed.add_field(name="Prior Actions", value=prior, inline=False)

        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        # Use ModActionLogView with Case button if case_id provided
        view = ModActionLogView(user.id, self.config.logging_guild_id or 0, case_id=case_id)
        await self._send_log(LogCategory.BANS_KICKS, embed, user_id=user.id, view=view)

    async def log_unban(
        self,
        user: discord.User,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log an unban."""
        if not self.enabled:
            return

        embed = self._create_embed("🔓 Member Unbanned", EmbedColors.SUCCESS, category="Unban", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)
        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        view = ModActionLogView(user.id, self.config.logging_guild_id or 0, case_id=case_id)
        await self._send_log(LogCategory.BANS_KICKS, embed, user_id=user.id, view=view)

    async def log_kick(
        self,
        user: discord.User,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log a kick."""
        if not self.enabled:
            return

        embed = self._create_embed("👢 Member Kicked", EmbedColors.LOG_NEGATIVE, category="Kick", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)

        # Add prior actions context
        if self.config.logging_guild_id:
            db = get_db()
            counts = db.get_user_case_counts(user.id, self.config.logging_guild_id)
            if counts["mute_count"] or counts["ban_count"] or counts["warn_count"]:
                prior = f"🔇 `{counts['mute_count']}` mutes · 🔨 `{counts['ban_count']}` bans · ⚠️ `{counts['warn_count']}` warns"
                embed.add_field(name="Prior Actions", value=prior, inline=False)

        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        view = ModActionLogView(user.id, self.config.logging_guild_id or 0, case_id=case_id)
        await self._send_log(LogCategory.BANS_KICKS, embed, user_id=user.id, view=view)

    # =========================================================================
    # Mutes & Timeouts
    # =========================================================================

    async def log_timeout(
        self,
        user: discord.Member,
        until: Optional[datetime] = None,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log a timeout."""
        if not self._should_log(user.guild.id):
            return

        embed = self._create_embed("⏰ Member Timed Out", EmbedColors.WARNING, category="Timeout", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)

        if until:
            timestamp = int(until.timestamp())
            # Calculate duration
            now = datetime.now(until.tzinfo) if until.tzinfo else datetime.now()
            duration_seconds = int((until - now).total_seconds())
            if duration_seconds > 0:
                if duration_seconds >= 86400:
                    duration_str = f"{duration_seconds // 86400}d {(duration_seconds % 86400) // 3600}h"
                elif duration_seconds >= 3600:
                    duration_str = f"{duration_seconds // 3600}h {(duration_seconds % 3600) // 60}m"
                else:
                    duration_str = f"{duration_seconds // 60}m"
                embed.add_field(name="Duration", value=f"`{duration_str}`", inline=True)
            embed.add_field(name="Expires", value=f"<t:{timestamp}:R>", inline=True)

        # Add prior actions context
        db = get_db()
        counts = db.get_user_case_counts(user.id, user.guild.id)
        if counts["mute_count"] or counts["ban_count"] or counts["warn_count"]:
            prior = f"🔇 `{counts['mute_count']}` mutes · 🔨 `{counts['ban_count']}` bans · ⚠️ `{counts['warn_count']}` warns"
            embed.add_field(name="Prior Actions", value=prior, inline=False)

        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        view = ModActionLogView(user.id, user.guild.id, case_id=case_id)
        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=user.id, view=view)

    async def log_timeout_remove(
        self,
        user: discord.Member,
        moderator: Optional[discord.Member] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log a timeout removal."""
        if not self._should_log(user.guild.id):
            return

        embed = self._create_embed("⏰ Timeout Removed", EmbedColors.SUCCESS, category="Timeout Remove", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)
        self._set_user_thumbnail(embed, user)

        view = ModActionLogView(user.id, user.guild.id, case_id=case_id)
        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=user.id, view=view)

    async def log_mute(
        self,
        user: discord.Member,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log a mute (role-based)."""
        if not self._should_log(user.guild.id):
            return

        embed = self._create_embed("🔇 Member Muted", EmbedColors.LOG_NEGATIVE, category="Mute", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)

        # Add prior actions context
        db = get_db()
        counts = db.get_user_case_counts(user.id, user.guild.id)
        if counts["mute_count"] or counts["ban_count"] or counts["warn_count"]:
            prior = f"🔇 `{counts['mute_count']}` mutes · 🔨 `{counts['ban_count']}` bans · ⚠️ `{counts['warn_count']}` warns"
            embed.add_field(name="Prior Actions", value=prior, inline=False)

        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        view = ModActionLogView(user.id, user.guild.id, case_id=case_id)
        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=user.id, view=view)

    async def log_unmute(
        self,
        user: discord.Member,
        moderator: Optional[discord.Member] = None,
        case_id: Optional[str] = None,
    ) -> None:
        """Log an unmute (role-based)."""
        if not self._should_log(user.guild.id):
            return

        embed = self._create_embed("🔊 Member Unmuted", EmbedColors.SUCCESS, category="Unmute", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if case_id:
            embed.add_field(name="Case", value=f"`#{case_id}`", inline=True)
        self._set_user_thumbnail(embed, user)

        view = ModActionLogView(user.id, user.guild.id, case_id=case_id)
        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=user.id, view=view)

    async def log_muted_vc_violation(
        self,
        member: discord.Member,
        channel_name: str,
        timeout_duration: "timedelta",
        channel_id: Optional[int] = None,
    ) -> None:
        """Log when a muted user attempts to join voice and gets timed out."""
        if not self._should_log(member.guild.id):
            return

        from datetime import timedelta

        # Format timeout duration
        hours = int(timeout_duration.total_seconds() // 3600)
        timeout_str = f"{hours} hour{'s' if hours != 1 else ''}"

        embed = self._create_embed(
            "🔇 Muted User VC Violation",
            EmbedColors.ERROR,
            category="VC Violation",
            user_id=member.id,
        )
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        channel_value = f"🔊 <#{channel_id}>" if channel_id else f"🔊 {channel_name}"
        embed.add_field(name="Attempted Channel", value=channel_value, inline=True)
        embed.add_field(name="Action", value="Disconnected", inline=True)
        embed.add_field(name="Timeout Applied", value=f"`{timeout_str}`", inline=True)
        embed.add_field(
            name="Reason",
            value="Muted users are not allowed in voice channels",
            inline=False,
        )
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=member.id)

    # =========================================================================
    # Message Logs
    # =========================================================================

    async def log_message_delete(
        self,
        message: discord.Message,
        attachments: Optional[List[Tuple[str, bytes]]] = None,
    ) -> None:
        """Log a message deletion."""
        if not self._should_log(message.guild.id if message.guild else None, message.author.id):
            return

        embed = self._create_embed("🗑️ Message Deleted", EmbedColors.LOG_NEGATIVE, category="Message Delete", user_id=message.author.id)
        embed.add_field(name="Author", value=self._format_user_field(message.author), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(message.channel), inline=True)

        content = f"```{message.content[:900]}```" if message.content else "*(no content)*"
        embed.add_field(name="Content", value=content, inline=False)

        # Show attachment filenames (not raw CDN URLs)
        if message.attachments:
            att_names = [f"📎 {att.filename}" for att in message.attachments[:5]]
            embed.add_field(name="Attachments", value="\n".join(att_names), inline=True)

        # Handle reply info with jump link
        if message.reference and message.reference.message_id:
            channel_id = message.reference.channel_id or message.channel.id
            guild_id = message.guild.id if message.guild else 0
            reply_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{message.reference.message_id}"
            embed.add_field(
                name="Reply To",
                value=f"[Jump to message]({reply_url})",
                inline=True,
            )

        self._set_user_thumbnail(embed, message.author)

        # Prepare files from cached attachments
        files = []
        if attachments:
            for filename, data in attachments[:5]:  # Max 5 files
                files.append(discord.File(io.BytesIO(data), filename=filename))

        # Create view with UserID/Avatar buttons (no Jump since message is deleted)
        guild_id = message.guild.id if message.guild else 0
        view = MessageLogView(message.author.id, guild_id)

        await self._send_log(LogCategory.MESSAGES, embed, files, user_id=message.author.id, view=view)

    async def log_message_edit(
        self,
        before: discord.Message,
        after: discord.Message,
    ) -> None:
        """Log a message edit."""
        if not self._should_log(after.guild.id if after.guild else None, after.author.id):
            return

        # Skip if content didn't change
        if before.content == after.content:
            return

        embed = self._create_embed("✏️ Message Edited", EmbedColors.WARNING, category="Message Edit", user_id=after.author.id)
        embed.add_field(name="Author", value=self._format_user_field(after.author), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(after.channel), inline=True)

        before_content = f"```{before.content[:400]}```" if before.content else "*(empty)*"
        after_content = f"```{after.content[:400]}```" if after.content else "*(empty)*"

        embed.add_field(name="Before", value=before_content, inline=False)
        embed.add_field(name="After", value=after_content, inline=False)

        self._set_user_thumbnail(embed, after.author)

        # Create view with Jump button, UserID, Avatar
        guild_id = after.guild.id if after.guild else 0
        view = MessageLogView(after.author.id, guild_id, message_url=after.jump_url)

        await self._send_log(LogCategory.MESSAGES, embed, user_id=after.author.id, view=view)

    async def log_bulk_delete(
        self,
        channel: discord.TextChannel,
        count: int,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a bulk message delete."""
        if not self.enabled:
            return

        embed = self._create_embed("🗑️ Bulk Delete", EmbedColors.LOG_NEGATIVE, category="Bulk Delete")
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        embed.add_field(name="Messages", value=f"**{count}**", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.MESSAGES, embed)

    # =========================================================================
    # Member Joins
    # =========================================================================

    async def log_member_join(
        self,
        member: discord.Member,
        invite_code: Optional[str] = None,
        inviter: Optional[discord.User] = None,
    ) -> None:
        """Log a member join."""
        if not self._should_log(member.guild.id, member.id):
            return

        db = get_db()

        # Get current join count (before incrementing)
        activity = db.get_member_activity(member.id, member.guild.id)
        join_count = (activity["join_count"] + 1) if activity else 1

        embed = self._create_embed("📥 Member Joined", EmbedColors.SUCCESS, category="Join", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)

        # Account age
        created = int(member.created_at.timestamp())
        embed.add_field(name="Account Created", value=f"<t:{created}:R>", inline=True)

        if invite_code:
            embed.add_field(name="Invite", value=f"`{invite_code}`", inline=True)
        if inviter:
            embed.add_field(name="Invited By", value=self._format_user_field(inviter), inline=True)

        # Join counter
        if join_count > 1:
            embed.add_field(name="Join #", value=f"`{join_count}`", inline=True)

        # Member count after join
        embed.add_field(name="Members", value=f"`{member.guild.member_count:,}`", inline=True)

        self._set_user_thumbnail(embed, member)

        message = await self._send_log(LogCategory.JOINS, embed, user_id=member.id)

        # Record join with message ID in database (persists across restarts)
        message_id = message.id if message else None
        db.record_member_join(member.id, member.guild.id, join_message_id=message_id)
        if message_id:
            logger.debug(f"Stored join message {message_id} for member {member.id} in database")

    async def _edit_join_message_on_leave(
        self,
        message_id: int,
        member: discord.Member,
        was_banned: bool,
    ) -> None:
        """Edit the original join embed to show they left."""
        logger.debug(f"Editing join message {message_id} for member {member.id}")
        try:
            thread = self._threads[LogCategory.JOINS]
            message = await thread.fetch_message(message_id)
            logger.debug(f"Fetched message {message_id}, has embeds: {bool(message.embeds)}")

            if message.embeds:
                embed = message.embeds[0]

                # Calculate time in server
                duration_str = "Unknown"
                if member.joined_at:
                    total_seconds = int(datetime.now(timezone.utc).timestamp() - member.joined_at.timestamp())
                    total_seconds = max(0, total_seconds)
                    duration_str = self._format_duration_precise(total_seconds)

                # Update title and color based on ban status
                if was_banned:
                    embed.title = "📥 Member Joined → 🔨 Banned"
                    embed.color = EmbedColors.LOG_NEGATIVE
                else:
                    embed.title = "📥 Member Joined → 📤 Left"
                    embed.color = EmbedColors.WARNING

                # Add "Left After" field
                embed.add_field(name="Left After", value=f"`{duration_str}`", inline=True)

                await message.edit(embed=embed)
        except discord.NotFound:
            pass  # Message was deleted
        except Exception as e:
            logger.debug(f"Logging Service: Failed to edit join message on leave: {e}")

    # =========================================================================
    # Member Leaves
    # =========================================================================

    async def log_member_leave(
        self,
        member: discord.Member,
        was_banned: bool = False,
    ) -> None:
        """Log a member leave with detailed info."""
        db = get_db()

        # Get join message ID from database (persists across restarts)
        join_message_id = db.pop_join_message_id(member.id, member.guild.id)
        logger.debug(f"Member leave: {member.id}, join_message_id={join_message_id}, JOINS in threads={LogCategory.JOINS in self._threads}")

        # Edit the original join embed to show they left
        if join_message_id and LogCategory.JOINS in self._threads:
            await self._edit_join_message_on_leave(join_message_id, member, was_banned)
        elif join_message_id:
            logger.debug(f"JOINS thread not found, cannot edit join message for {member.id}")

        if not self._should_log(member.guild.id, member.id):
            return
        leave_count = db.record_member_leave(member.id, member.guild.id)

        # Change title if banned
        if was_banned:
            title = "📤 Member Left [Banned]"
            color = EmbedColors.LOG_NEGATIVE
        else:
            title = "📤 Member Left"
            color = EmbedColors.WARNING

        embed = self._create_embed(title, color, category="Leave", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)

        # Account created
        created = int(member.created_at.timestamp())
        embed.add_field(name="Account Age", value=f"<t:{created}:R>", inline=True)

        # Time in server (how long they were here)
        if member.joined_at:
            total_seconds = int(datetime.now(timezone.utc).timestamp() - member.joined_at.timestamp())
            total_seconds = max(0, total_seconds)  # Safety: ensure positive
            duration_str = self._format_duration_precise(total_seconds)
            embed.add_field(name="Time in Server", value=f"`{duration_str}`", inline=True)

        # Leave counter
        if leave_count > 1:
            embed.add_field(name="Leave #", value=f"`{leave_count}`", inline=True)

        # Member count after leave
        embed.add_field(name="Members", value=f"`{member.guild.member_count:,}`", inline=True)

        # Role list with count
        roles = [r for r in member.roles if r.name != "@everyone"]
        role_count = len(roles)
        role_names = [self._format_role(r) for r in roles[:15]]  # Show up to 15 roles
        if role_names:
            roles_str = " ".join(role_names)
            if role_count > 15:
                roles_str += f" +{role_count - 15} more"
            embed.add_field(name=f"Roles ({role_count})", value=roles_str, inline=False)

        self._set_user_thumbnail(embed, member)

        # LogView automatically adds Case button if user has a case
        await self._send_log(LogCategory.LEAVES, embed, user_id=member.id)

    # =========================================================================
    # Role Changes
    # =========================================================================

    async def log_role_add(
        self,
        member: discord.Member,
        role: discord.Role,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a role being added to a member."""
        if not self._should_log(member.guild.id, member.id):
            return

        embed = self._create_embed("➕ Role Added", EmbedColors.SUCCESS, category="Role Add", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Role", value=self._format_role(role), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.ROLE_CHANGES, embed, user_id=member.id)

    async def log_role_remove(
        self,
        member: discord.Member,
        role: discord.Role,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a role being removed from a member."""
        if not self._should_log(member.guild.id, member.id):
            return

        embed = self._create_embed("➖ Role Removed", EmbedColors.LOG_NEGATIVE, category="Role Remove", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Role", value=self._format_role(role), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.ROLE_CHANGES, embed, user_id=member.id)

    # =========================================================================
    # Name Changes
    # =========================================================================

    async def log_nickname_change(
        self,
        member: discord.Member,
        before: Optional[str],
        after: Optional[str],
    ) -> None:
        """Log a nickname change."""
        if not self._should_log(member.guild.id, member.id):
            return

        embed = self._create_embed("✨ Nickname Changed", EmbedColors.INFO, category="Nickname", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Before", value=f"`{before}`" if before else "*(none)*", inline=True)
        embed.add_field(name="After", value=f"`{after}`" if after else "*(none)*", inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.NAME_CHANGES, embed, user_id=member.id)

    async def log_username_change(
        self,
        user: discord.User,
        before: str,
        after: str,
    ) -> None:
        """Log a username change."""
        if not self.enabled or (self.config.ignored_bot_ids and user.id in self.config.ignored_bot_ids):
            return

        embed = self._create_embed("✨ Username Changed", EmbedColors.INFO, category="Username", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Before", value=f"`{before}`", inline=True)
        embed.add_field(name="After", value=f"`{after}`", inline=True)
        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.NAME_CHANGES, embed, user_id=user.id)

    # =========================================================================
    # Avatar Changes
    # =========================================================================

    async def log_avatar_change(
        self,
        user: discord.User,
        before_url: Optional[str],
        after_url: Optional[str],
    ) -> None:
        """Log an avatar change."""
        if not self.enabled or (self.config.ignored_bot_ids and user.id in self.config.ignored_bot_ids):
            return

        embed = self._create_embed("🖼️ Avatar Changed", EmbedColors.INFO, category="Avatar", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)

        files = []
        old_avatar_downloaded = False

        # Download and attach old avatar before it expires
        if before_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(before_url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            files.append(discord.File(io.BytesIO(data), filename="old_avatar.png"))
                            embed.set_thumbnail(url="attachment://old_avatar.png")
                            embed.add_field(name="Previous", value="See thumbnail ↗️", inline=True)
                            old_avatar_downloaded = True
            except Exception:
                pass

        if after_url:
            embed.set_image(url=after_url)
            embed.add_field(name="New", value="See image below ↓", inline=True)

        message = await self._send_log(LogCategory.AVATAR_CHANGES, embed, files, user_id=user.id)

        # Add download buttons for old and new avatars (ephemeral style)
        if message:
            try:
                view = discord.ui.View(timeout=None)

                # Old avatar button (fetches from message attachment)
                if old_avatar_downloaded:
                    view.add_item(OldAvatarButton(message.channel.id, message.id))

                # New avatar button (fetches from message embed image)
                if after_url:
                    view.add_item(NewAvatarButton(message.channel.id, message.id))

                view.add_item(UserIdButton(user.id))
                await message.edit(view=view)
            except Exception:
                pass

    # =========================================================================
    # Voice Activity
    # =========================================================================

    async def log_voice_join(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
    ) -> None:
        """Log a voice channel join."""
        if not self._should_log(member.guild.id, member.id):
            return

        # Skip logging moderator voice activity (too spammy)
        if self.config.moderator_ids and member.id in self.config.moderator_ids:
            return

        embed = self._create_embed("🟢 Voice Join", EmbedColors.SUCCESS, category="Voice Join", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=f"🔊 {self._format_channel(channel)}", inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_leave(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
    ) -> None:
        """Log a voice channel leave."""
        if not self._should_log(member.guild.id, member.id):
            return

        # Skip logging moderator voice activity (too spammy)
        if self.config.moderator_ids and member.id in self.config.moderator_ids:
            return

        embed = self._create_embed("🔴 Voice Leave", EmbedColors.LOG_NEGATIVE, category="Voice Leave", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=f"🔊 {self._format_channel(channel)}", inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_move(
        self,
        member: discord.Member,
        before: discord.VoiceChannel,
        after: discord.VoiceChannel,
    ) -> None:
        """Log a voice channel move."""
        if not self._should_log(member.guild.id):
            return

        # Skip logging moderator voice activity (too spammy)
        if self.config.moderator_ids and member.id in self.config.moderator_ids:
            return

        embed = self._create_embed("🔀 Voice Move", EmbedColors.BLUE, category="Voice Move", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Moved", value=f"{before.name} → {after.name}", inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_mute(
        self,
        member: discord.Member,
        muted: bool,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a server mute/unmute."""
        if not self._should_log(member.guild.id):
            return

        if muted:
            embed = self._create_embed("🔇 Server Muted", EmbedColors.WARNING, category="Voice Mute", user_id=member.id)
        else:
            embed = self._create_embed("🔊 Server Unmuted", EmbedColors.SUCCESS, category="Voice Unmute", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_deafen(
        self,
        member: discord.Member,
        deafened: bool,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a server deafen/undeafen."""
        if not self._should_log(member.guild.id):
            return

        if deafened:
            embed = self._create_embed("🔇 Server Deafened", EmbedColors.WARNING, category="Voice Deafen", user_id=member.id)
        else:
            embed = self._create_embed("🔊 Server Undeafened", EmbedColors.SUCCESS, category="Voice Undeafen", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_self_mute(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
        muted: bool,
    ) -> None:
        """Log a user self-muting/unmuting."""
        if not self._should_log(member.guild.id, member.id):
            return

        # Skip mods (too spammy)
        if self.config.moderator_ids and member.id in self.config.moderator_ids:
            return

        if muted:
            embed = self._create_embed("🔇 Self Muted", EmbedColors.INFO, category="Self Mute", user_id=member.id)
        else:
            embed = self._create_embed("🔊 Self Unmuted", EmbedColors.INFO, category="Self Unmute", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_self_deafen(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
        deafened: bool,
    ) -> None:
        """Log a user self-deafening/undeafening."""
        if not self._should_log(member.guild.id, member.id):
            return

        # Skip mods (too spammy)
        if self.config.moderator_ids and member.id in self.config.moderator_ids:
            return

        if deafened:
            embed = self._create_embed("🔇 Self Deafened", EmbedColors.INFO, category="Self Deafen", user_id=member.id)
        else:
            embed = self._create_embed("🔊 Self Undeafened", EmbedColors.INFO, category="Self Undeafen", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_stream(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
        streaming: bool,
    ) -> None:
        """Log a user starting/stopping a stream."""
        if not self._should_log(member.guild.id, member.id):
            return

        if streaming:
            embed = self._create_embed("📺 Started Streaming", EmbedColors.SUCCESS, category="Stream Start", user_id=member.id)
        else:
            embed = self._create_embed("📺 Stopped Streaming", EmbedColors.WARNING, category="Stream Stop", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_voice_video(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
        video_on: bool,
    ) -> None:
        """Log a user turning camera on/off."""
        if not self._should_log(member.guild.id, member.id):
            return

        if video_on:
            embed = self._create_embed("📹 Camera On", EmbedColors.SUCCESS, category="Camera On", user_id=member.id)
        else:
            embed = self._create_embed("📹 Camera Off", EmbedColors.WARNING, category="Camera Off", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    # =========================================================================
    # Channel Changes
    # =========================================================================

    async def log_channel_create(
        self,
        channel: discord.abc.GuildChannel,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a channel creation."""
        if not self.enabled:
            return

        embed = self._create_embed("📁 Channel Created", EmbedColors.SUCCESS, category="Channel Create")
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        embed.add_field(name="Type", value=str(channel.type).title(), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.CHANNELS, embed)

    async def log_channel_delete(
        self,
        channel_name: str,
        channel_type: str,
        moderator: Optional[discord.Member] = None,
        channel_id: Optional[int] = None,
    ) -> None:
        """Log a channel deletion."""
        if not self.enabled:
            return

        embed = self._create_embed("📁 Channel Deleted", EmbedColors.LOG_NEGATIVE, category="Channel Delete")
        # Show both mention (for searchability) and name (since deleted channels show as #deleted-channel)
        channel_value = f"<#{channel_id}> · `{channel_name}`" if channel_id else f"`{channel_name}`"
        embed.add_field(name="Channel", value=channel_value, inline=True)
        embed.add_field(name="Type", value=channel_type.title(), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.CHANNELS, embed)

    async def log_channel_update(
        self,
        channel: discord.abc.GuildChannel,
        changes: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a channel update."""
        if not self.enabled:
            return

        embed = self._create_embed("📁 Channel Updated", EmbedColors.WARNING, category="Channel Update")
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Changes", value=f"```{changes}```", inline=False)

        await self._send_log(LogCategory.CHANNELS, embed)

    # =========================================================================
    # Role Management
    # =========================================================================

    async def log_role_create(
        self,
        role: discord.Role,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a role creation."""
        if not self.enabled:
            return

        embed = self._create_embed("🎭 Role Created", EmbedColors.SUCCESS, category="Role Create")
        embed.add_field(name="Role", value=self._format_role(role), inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.ROLES, embed)

    async def log_role_delete(
        self,
        role_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a role deletion."""
        if not self.enabled:
            return

        embed = self._create_embed("🎭 Role Deleted", EmbedColors.LOG_NEGATIVE, category="Role Delete")
        role_display = f"`{role_name}`" if role_name else "unknown role"
        embed.add_field(name="Role", value=role_display, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.ROLES, embed)

    async def log_role_update(
        self,
        role: discord.Role,
        changes: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a role update."""
        if not self.enabled:
            return

        embed = self._create_embed("🎭 Role Updated", EmbedColors.WARNING, category="Role Update")
        embed.add_field(name="Role", value=self._format_role(role), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Changes", value=f"```{changes}```", inline=False)

        await self._send_log(LogCategory.ROLES, embed)

    # =========================================================================
    # Emoji & Stickers
    # =========================================================================

    async def log_emoji_create(
        self,
        emoji: discord.Emoji,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log an emoji creation."""
        if not self.enabled:
            return

        user_id = moderator.id if moderator else None
        embed = self._create_embed("😀 Emoji Created", EmbedColors.SUCCESS, category="Emoji Create", user_id=user_id)
        embed.add_field(name="Emoji", value=f"{emoji} `:{emoji.name}:`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        # Additional info
        embed.add_field(name="Animated", value="Yes" if emoji.animated else "No", inline=True)
        embed.add_field(name="ID", value=f"`{emoji.id}`", inline=True)

        # Show emoji as thumbnail
        embed.set_thumbnail(url=emoji.url)

        await self._send_log(LogCategory.EMOJI_STICKERS, embed, user_id=user_id)

    async def log_emoji_delete(
        self,
        emoji_name: str,
        emoji_id: Optional[int] = None,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log an emoji deletion."""
        if not self.enabled:
            return

        user_id = moderator.id if moderator else None
        embed = self._create_embed("😀 Emoji Deleted", EmbedColors.LOG_NEGATIVE, category="Emoji Delete", user_id=user_id)
        embed.add_field(name="Emoji", value=f"`:{emoji_name}:`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if emoji_id:
            embed.add_field(name="ID", value=f"`{emoji_id}`", inline=True)

        await self._send_log(LogCategory.EMOJI_STICKERS, embed, user_id=user_id)

    async def log_sticker_create(
        self,
        sticker: discord.GuildSticker,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a sticker creation."""
        if not self.enabled:
            return

        user_id = moderator.id if moderator else None
        embed = self._create_embed("🎨 Sticker Created", EmbedColors.SUCCESS, category="Sticker Create", user_id=user_id)
        embed.add_field(name="Sticker", value=f"`{sticker.name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        # Additional info
        if sticker.description:
            embed.add_field(name="Description", value=sticker.description[:100], inline=True)
        embed.add_field(name="Emoji", value=sticker.emoji or "None", inline=True)
        embed.add_field(name="ID", value=f"`{sticker.id}`", inline=True)

        # Show sticker as thumbnail
        embed.set_thumbnail(url=sticker.url)

        await self._send_log(LogCategory.EMOJI_STICKERS, embed, user_id=user_id)

    async def log_sticker_delete(
        self,
        sticker_name: str,
        sticker_id: Optional[int] = None,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a sticker deletion."""
        if not self.enabled:
            return

        user_id = moderator.id if moderator else None
        embed = self._create_embed("🎨 Sticker Deleted", EmbedColors.LOG_NEGATIVE, category="Sticker Delete", user_id=user_id)
        embed.add_field(name="Sticker", value=f"`{sticker_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if sticker_id:
            embed.add_field(name="ID", value=f"`{sticker_id}`", inline=True)

        await self._send_log(LogCategory.EMOJI_STICKERS, embed, user_id=user_id)

    # =========================================================================
    # Server Settings
    # =========================================================================

    async def log_server_update(
        self,
        changes: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log server settings changes."""
        if not self.enabled:
            return

        embed = self._create_embed("⚙️ Server Updated", EmbedColors.WARNING, category="Server Update")
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Changes", value=f"```{changes}```", inline=False)

        await self._send_log(LogCategory.SERVER_SETTINGS, embed)

    async def log_server_icon_change(
        self,
        guild: discord.Guild,
        old_icon_url: Optional[str],
        new_icon_url: Optional[str],
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log server icon change with images."""
        if not self.enabled:
            return

        embed = self._create_embed("🖼️ Server Icon Changed", EmbedColors.WARNING, category="Icon Change")
        embed.add_field(name="Server", value=guild.name, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        if old_icon_url:
            embed.add_field(name="Previous", value=f"[View]({old_icon_url})", inline=True)
        else:
            embed.add_field(name="Previous", value="*(none)*", inline=True)

        if new_icon_url:
            embed.set_thumbnail(url=new_icon_url)
            embed.add_field(name="New", value="See thumbnail →", inline=True)
        else:
            embed.add_field(name="New", value="*(removed)*", inline=True)

        await self._send_log(LogCategory.SERVER_SETTINGS, embed)

    async def log_server_banner_change(
        self,
        guild: discord.Guild,
        old_banner_url: Optional[str],
        new_banner_url: Optional[str],
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log server banner change with images."""
        if not self.enabled:
            return

        embed = self._create_embed("🎨 Server Banner Changed", EmbedColors.WARNING, category="Banner Change")
        embed.add_field(name="Server", value=guild.name, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        if old_banner_url:
            embed.add_field(name="Previous", value=f"[View]({old_banner_url})", inline=True)
        else:
            embed.add_field(name="Previous", value="*(none)*", inline=True)

        if new_banner_url:
            embed.set_image(url=new_banner_url)
            embed.add_field(name="New", value="See image below ↓", inline=True)
        else:
            embed.add_field(name="New", value="*(removed)*", inline=True)

        await self._send_log(LogCategory.SERVER_SETTINGS, embed)

    # =========================================================================
    # Permissions
    # =========================================================================

    async def log_permission_update(
        self,
        channel: discord.abc.GuildChannel,
        target: str,
        action: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log permission overwrite changes."""
        if not self.enabled:
            return

        embed = self._create_embed(f"🔐 Permission {action.title()}", EmbedColors.WARNING, category=f"Permission {action.title()}")
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        embed.add_field(name="Target", value=f"`{target}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.PERMISSIONS, embed)

    # =========================================================================
    # Bots & Integrations
    # =========================================================================

    async def log_bot_add(
        self,
        bot: discord.Member,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a bot being added."""
        if not self.enabled:
            return

        embed = self._create_embed("🤖 Bot Added", EmbedColors.WARNING, category="Bot Add", user_id=bot.id)
        embed.add_field(name="Bot", value=self._format_user_field(bot), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        self._set_user_thumbnail(embed, bot)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed, user_id=bot.id)

    async def log_bot_remove(
        self,
        bot_name: str,
        bot_id: int,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a bot being removed."""
        if not self.enabled:
            return

        embed = self._create_embed("🤖 Bot Removed", EmbedColors.LOG_NEGATIVE, category="Bot Remove", user_id=bot_id)
        embed.add_field(name="Bot", value=f"`{bot_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed, user_id=bot_id)

    async def log_integration_add(
        self,
        name: str,
        int_type: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log an integration being added."""
        if not self.enabled:
            return

        embed = self._create_embed("🔗 Integration Added", EmbedColors.INFO, category="Integration Add")
        embed.add_field(name="Name", value=name, inline=True)
        embed.add_field(name="Type", value=int_type, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed)

    async def log_integration_remove(
        self,
        name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log an integration being removed."""
        if not self.enabled:
            return

        embed = self._create_embed("🔗 Integration Removed", EmbedColors.LOG_NEGATIVE, category="Integration Remove")
        embed.add_field(name="Name", value=name, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed)

    # =========================================================================
    # Webhooks
    # =========================================================================

    async def log_webhook_create(
        self,
        webhook_name: str,
        channel: discord.abc.GuildChannel,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a webhook being created."""
        if not self.enabled:
            return

        embed = self._create_embed("🪝 Webhook Created", EmbedColors.SUCCESS, category="Webhook Create")
        embed.add_field(name="Name", value=f"`{webhook_name}`", inline=True)
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed)

    async def log_webhook_delete(
        self,
        webhook_name: str,
        channel_name: str,
        moderator: Optional[discord.Member] = None,
        channel_id: Optional[int] = None,
    ) -> None:
        """Log a webhook being deleted."""
        if not self.enabled:
            return

        embed = self._create_embed("🪝 Webhook Deleted", EmbedColors.LOG_NEGATIVE, category="Webhook Delete")
        embed.add_field(name="Name", value=f"`{webhook_name}`", inline=True)
        channel_value = f"<#{channel_id}>" if channel_id else f"`{channel_name}`"
        embed.add_field(name="Channel", value=channel_value, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed)

    # =========================================================================
    # Thread Activity
    # =========================================================================

    async def log_thread_create(
        self,
        thread: discord.Thread,
        creator: Optional[discord.Member] = None,
    ) -> None:
        """Log a thread being created."""
        if not self.enabled:
            return

        embed = self._create_embed("🧵 Thread Created", EmbedColors.SUCCESS, category="Thread Create")
        embed.add_field(name="Thread", value=f"#{thread.name}" if thread.name else "#unknown-thread", inline=True)
        if thread.parent:
            embed.add_field(name="Parent", value=self._format_channel(thread.parent), inline=True)
        if creator:
            embed.add_field(name="By", value=self._format_user_field(creator), inline=True)

        await self._send_log(LogCategory.THREADS, embed)

    async def log_thread_delete(
        self,
        thread_name: str,
        parent_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a thread being deleted."""
        if not self.enabled:
            return

        embed = self._create_embed("🧵 Thread Deleted", EmbedColors.LOG_NEGATIVE, category="Thread Delete")
        embed.add_field(name="Thread", value=f"`{thread_name}`", inline=True)
        embed.add_field(name="Parent", value=f"`{parent_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.THREADS, embed)

    async def log_thread_archive(
        self,
        thread: discord.Thread,
        archived: bool,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a thread being archived/unarchived."""
        if not self.enabled:
            return

        if archived:
            embed = self._create_embed("🧵 Thread Archived", EmbedColors.WARNING, category="Thread Archive")
        else:
            embed = self._create_embed("🧵 Thread Unarchived", EmbedColors.SUCCESS, category="Thread Unarchive")

        embed.add_field(name="Thread", value=f"#{thread.name}" if thread.name else "#unknown-thread", inline=True)
        if thread.parent:
            embed.add_field(name="Parent", value=self._format_channel(thread.parent), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.THREADS, embed)

    # =========================================================================
    # AutoMod Actions
    # =========================================================================

    async def log_automod_action(
        self,
        rule_name: str,
        action_type: str,
        user: discord.Member,
        channel: Optional[discord.abc.GuildChannel] = None,
        content: Optional[str] = None,
        matched_keyword: Optional[str] = None,
    ) -> None:
        """Log an AutoMod action."""
        if not self.enabled:
            return

        embed = self._create_embed("🛡️ AutoMod Action", EmbedColors.WARNING, category="AutoMod", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Rule", value=f"`{rule_name}`", inline=True)
        embed.add_field(name="Action", value=f"`{action_type}`", inline=True)

        if channel:
            embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)

        if matched_keyword:
            embed.add_field(name="Matched", value=f"`{matched_keyword}`", inline=True)

        if content:
            truncated = content[:300] if len(content) > 300 else content
            embed.add_field(name="Content", value=f"```{truncated}```", inline=False)

        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.AUTOMOD, embed, user_id=user.id)

    async def log_automod_block(
        self,
        rule_name: str,
        user: discord.Member,
        channel: Optional[discord.abc.GuildChannel] = None,
        content: Optional[str] = None,
        matched_keyword: Optional[str] = None,
    ) -> None:
        """Log a message blocked by AutoMod."""
        if not self.enabled:
            return

        embed = self._create_embed("🛡️ Message Blocked", EmbedColors.LOG_NEGATIVE, category="AutoMod Block", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Rule", value=f"`{rule_name}`", inline=True)

        if channel:
            embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)

        if matched_keyword:
            embed.add_field(name="Matched", value=f"`{matched_keyword}`", inline=True)

        if content:
            truncated = content[:300] if len(content) > 300 else content
            embed.add_field(name="Content", value=f"```{truncated}```", inline=False)

        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.AUTOMOD, embed, user_id=user.id)

    # =========================================================================
    # Scheduled Events
    # =========================================================================

    async def log_event_create(
        self,
        event: discord.ScheduledEvent,
        creator: Optional[discord.Member] = None,
    ) -> None:
        """Log a scheduled event creation."""
        if not self.enabled:
            return

        embed = self._create_embed("📅 Event Created", EmbedColors.SUCCESS, category="Event Create")
        embed.add_field(name="Event", value=f"`{event.name}`", inline=True)

        if event.start_time:
            start = int(event.start_time.timestamp())
            embed.add_field(name="Starts", value=f"<t:{start}:F>", inline=True)

        if event.location:
            embed.add_field(name="Location", value=f"`{event.location}`", inline=True)
        elif event.channel:
            embed.add_field(name="Channel", value=self._format_channel(event.channel), inline=True)

        if creator:
            embed.add_field(name="By", value=self._format_user_field(creator), inline=True)

        if event.description:
            desc = event.description[:200] if len(event.description) > 200 else event.description
            embed.add_field(name="Description", value=f"```{desc}```", inline=False)

        if event.cover_image:
            embed.set_image(url=event.cover_image.url)

        await self._send_log(LogCategory.EVENTS, embed)

    async def log_event_update(
        self,
        event: discord.ScheduledEvent,
        changes: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a scheduled event update."""
        if not self.enabled:
            return

        embed = self._create_embed("📅 Event Updated", EmbedColors.WARNING, category="Event Update")
        embed.add_field(name="Event", value=f"`{event.name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Changes", value=f"```{changes}```", inline=False)

        await self._send_log(LogCategory.EVENTS, embed)

    async def log_event_delete(
        self,
        event_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a scheduled event deletion."""
        if not self.enabled:
            return

        embed = self._create_embed("📅 Event Deleted", EmbedColors.LOG_NEGATIVE, category="Event Delete")
        embed.add_field(name="Event", value=f"`{event_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.EVENTS, embed)

    async def log_event_start(
        self,
        event: discord.ScheduledEvent,
    ) -> None:
        """Log a scheduled event starting."""
        if not self.enabled:
            return

        embed = self._create_embed("📅 Event Started", EmbedColors.SUCCESS, category="Event Start")
        embed.add_field(name="Event", value=f"`{event.name}`", inline=True)

        if event.channel:
            embed.add_field(name="Channel", value=self._format_channel(event.channel), inline=True)
        elif event.location:
            embed.add_field(name="Location", value=f"`{event.location}`", inline=True)

        await self._send_log(LogCategory.EVENTS, embed)

    async def log_event_end(
        self,
        event: discord.ScheduledEvent,
    ) -> None:
        """Log a scheduled event ending."""
        if not self.enabled:
            return

        embed = self._create_embed("📅 Event Ended", EmbedColors.INFO, category="Event End")
        embed.add_field(name="Event", value=f"`{event.name}`", inline=True)

        await self._send_log(LogCategory.EVENTS, embed)

    # =========================================================================
    # Forum Posts
    # =========================================================================

    async def log_forum_post_create(
        self,
        thread: discord.Thread,
        author: Optional[discord.Member] = None,
    ) -> None:
        """Log a new forum post creation."""
        if not self.enabled:
            return

        user_id = author.id if author else None
        embed = self._create_embed("📝 Forum Post Created", EmbedColors.SUCCESS, category="Forum Post", user_id=user_id)
        embed.add_field(name="Post", value=f"#{thread.name}" if thread.name else "#unknown-post", inline=True)

        if thread.parent:
            embed.add_field(name="Forum", value=self._format_channel(thread.parent), inline=True)

        if author:
            embed.add_field(name="Author", value=self._format_user_field(author), inline=True)
            self._set_user_thumbnail(embed, author)

        # Show applied tags if any
        if thread.applied_tags:
            tags = ", ".join([f"`{tag.name}`" for tag in thread.applied_tags[:5]])
            embed.add_field(name="Tags", value=tags, inline=False)

        await self._send_log(LogCategory.THREADS, embed, user_id=user_id)

    # =========================================================================
    # Reactions
    # =========================================================================

    async def log_reaction_add(
        self,
        reaction: discord.Reaction,
        user: discord.Member,
        message: discord.Message,
    ) -> None:
        """Log a reaction being added."""
        if not self.enabled:
            return

        embed = self._create_embed("➕ Reaction Added", EmbedColors.SUCCESS, category="Reaction Add", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Reacted", value=f"{reaction.emoji} in {self._format_channel(message.channel)}", inline=True)

        # Show message preview in code block
        if message.content:
            preview = message.content[:100] + "..." if len(message.content) > 100 else message.content
            embed.add_field(name="Message", value=f"```{preview}```", inline=False)

        self._set_user_thumbnail(embed, user)

        view = ReactionLogView(user.id, user.guild.id, message.jump_url)
        await self._send_log(LogCategory.REACTIONS, embed, view=view)

    async def log_reaction_remove(
        self,
        reaction: discord.Reaction,
        user: discord.Member,
        message: discord.Message,
    ) -> None:
        """Log a reaction being removed."""
        if not self.enabled:
            return

        embed = self._create_embed("➖ Reaction Removed", EmbedColors.LOG_NEGATIVE, category="Reaction Remove", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Removed", value=f"{reaction.emoji} from {self._format_channel(message.channel)}", inline=True)
        self._set_user_thumbnail(embed, user)

        view = ReactionLogView(user.id, user.guild.id, message.jump_url)
        await self._send_log(LogCategory.REACTIONS, embed, view=view)

    async def log_reaction_clear(
        self,
        message: discord.Message,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log all reactions being cleared from a message."""
        if not self.enabled:
            return

        embed = self._create_embed("🗑️ Reactions Cleared", EmbedColors.LOG_NEGATIVE, category="Reaction Clear")
        embed.add_field(name="Channel", value=self._format_channel(message.channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        # Message button
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(
            label="Message",
            url=message.jump_url,
            style=discord.ButtonStyle.link,
            emoji=MESSAGE_EMOJI,
        ))

        await self._send_log(LogCategory.REACTIONS, embed, view=view)

    # =========================================================================
    # Stage Activity
    # =========================================================================

    async def log_stage_start(
        self,
        stage: discord.StageInstance,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a stage instance starting."""
        if not self.enabled:
            return

        embed = self._create_embed("🎤 Stage Started", EmbedColors.SUCCESS, category="Stage Start")
        embed.add_field(name="Topic", value=f"`{stage.topic}`", inline=True)

        if stage.channel:
            embed.add_field(name="Channel", value=self._format_channel(stage.channel), inline=True)

        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.STAGE, embed)

    async def log_stage_end(
        self,
        channel_name: str,
        topic: str,
        moderator: Optional[discord.Member] = None,
        channel_id: Optional[int] = None,
    ) -> None:
        """Log a stage instance ending."""
        if not self.enabled:
            return

        embed = self._create_embed("🎤 Stage Ended", EmbedColors.LOG_NEGATIVE, category="Stage End")
        embed.add_field(name="Topic", value=f"`{topic}`", inline=True)
        channel_value = f"🔊 <#{channel_id}>" if channel_id else f"🔊 `{channel_name}`"
        embed.add_field(name="Channel", value=channel_value, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.STAGE, embed)

    async def log_stage_update(
        self,
        stage: discord.StageInstance,
        changes: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a stage instance being updated."""
        if not self.enabled:
            return

        embed = self._create_embed("🎤 Stage Updated", EmbedColors.WARNING, category="Stage Update")
        embed.add_field(name="Topic", value=f"`{stage.topic}`", inline=True)
        if stage.channel:
            embed.add_field(name="Channel", value=self._format_channel(stage.channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Changes", value=f"```{changes}```", inline=False)

        await self._send_log(LogCategory.STAGE, embed)

    async def log_stage_speaker(
        self,
        member: discord.Member,
        channel: discord.StageChannel,
        became_speaker: bool,
    ) -> None:
        """Log a member becoming/stopping being a speaker."""
        if not self.enabled:
            return

        if became_speaker:
            embed = self._create_embed("🎤 Speaker Added", EmbedColors.SUCCESS, category="Speaker Add", user_id=member.id)
        else:
            embed = self._create_embed("🎤 Speaker Removed", EmbedColors.WARNING, category="Speaker Remove", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Stage", value=self._format_channel(channel), inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.STAGE, embed, user_id=member.id)

    # =========================================================================
    # Message Pin/Unpin
    # =========================================================================

    async def log_message_pin(
        self,
        message: Optional[discord.Message] = None,
        pinned: bool = True,
        moderator: Optional[discord.Member] = None,
        channel: Optional[discord.TextChannel] = None,
        message_id: Optional[int] = None,
    ) -> None:
        """
        Log a message being pinned or unpinned.

        Args:
            message: The message object (if available)
            pinned: True for pin, False for unpin
            moderator: The moderator who performed the action
            channel: Fallback channel when message can't be fetched
            message_id: Fallback message ID when message can't be fetched
        """
        if not self.enabled:
            return

        user_id = message.author.id if message else None

        if pinned:
            embed = self._create_embed("📌 Message Pinned", EmbedColors.SUCCESS, category="Pin", user_id=user_id)
        else:
            embed = self._create_embed("📌 Message Unpinned", EmbedColors.WARNING, category="Unpin", user_id=user_id)

        if message:
            embed.add_field(name="Author", value=self._format_user_field(message.author), inline=True)
            embed.add_field(name="Channel", value=self._format_channel(message.channel), inline=True)
            if moderator:
                embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

            # Show message preview
            if message.content:
                preview = message.content[:200] + "..." if len(message.content) > 200 else message.content
                embed.add_field(name="Content Preview", value=f"```{preview}```", inline=False)

            self._set_user_thumbnail(embed, message.author)

            # Add Message button + UserID/Avatar
            view = MessageLogView(message.author.id, message.guild.id if message.guild else 0, message_url=message.jump_url)
            await self._send_log(LogCategory.MESSAGES, embed, user_id=user_id, view=view)
            return
        else:
            # Fallback when message can't be fetched
            if channel:
                embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
            if moderator:
                embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
            if message_id:
                embed.add_field(name="Message ID", value=f"`{message_id}`", inline=True)
            if not pinned:
                embed.add_field(name="Note", value="*Message may have been deleted*", inline=False)

        await self._send_log(LogCategory.MESSAGES, embed, user_id=user_id)

    # =========================================================================
    # Server Boosts
    # =========================================================================

    async def log_boost(
        self,
        member: discord.Member,
    ) -> None:
        """Log a member boosting the server."""
        if not self.enabled:
            return

        embed = self._create_embed("💎 Server Boosted", EmbedColors.SUCCESS, category="Boost", user_id=member.id)
        embed.add_field(name="Booster", value=self._format_user_field(member), inline=True)

        # Get server boost count
        if member.guild:
            embed.add_field(
                name="Server Boosts",
                value=f"**{member.guild.premium_subscription_count}** boosts",
                inline=True,
            )
            embed.add_field(
                name="Boost Level",
                value=f"Level **{member.guild.premium_tier}**",
                inline=True,
            )

        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.BOOSTS, embed, user_id=member.id)

    async def log_unboost(
        self,
        member: discord.Member,
    ) -> None:
        """Log a member removing their server boost."""
        if not self.enabled:
            return

        embed = self._create_embed("💔 Boost Removed", EmbedColors.LOG_NEGATIVE, category="Unboost", user_id=member.id)
        embed.add_field(name="Former Booster", value=self._format_user_field(member), inline=True)

        # Get server boost count
        if member.guild:
            embed.add_field(
                name="Server Boosts",
                value=f"**{member.guild.premium_subscription_count}** boosts",
                inline=True,
            )
            embed.add_field(
                name="Boost Level",
                value=f"Level **{member.guild.premium_tier}**",
                inline=True,
            )

        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.BOOSTS, embed, user_id=member.id)

    # =========================================================================
    # Invite Activity
    # =========================================================================

    async def log_invite_create(
        self,
        invite: discord.Invite,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log an invite being created."""
        if not self.enabled:
            return

        embed = self._create_embed("🔗 Invite Created", EmbedColors.SUCCESS, category="Invite Create")
        embed.add_field(name="Code", value=f"`{invite.code}`", inline=True)

        if invite.channel:
            embed.add_field(name="Channel", value=self._format_channel(invite.channel), inline=True)

        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        elif invite.inviter:
            embed.add_field(name="By", value=self._format_user_field(invite.inviter), inline=True)

        # Max uses
        if invite.max_uses:
            embed.add_field(name="Max Uses", value=str(invite.max_uses), inline=True)
        else:
            embed.add_field(name="Max Uses", value="Unlimited", inline=True)

        # Expiry
        if invite.max_age:
            if invite.max_age >= 86400:
                days = invite.max_age // 86400
                expiry = f"{days} day{'s' if days > 1 else ''}"
            elif invite.max_age >= 3600:
                hours = invite.max_age // 3600
                expiry = f"{hours} hour{'s' if hours > 1 else ''}"
            else:
                minutes = invite.max_age // 60
                expiry = f"{minutes} minute{'s' if minutes > 1 else ''}"
            embed.add_field(name="Expires In", value=expiry, inline=True)
        else:
            embed.add_field(name="Expires", value="Never", inline=True)

        # Temporary membership
        if invite.temporary:
            embed.add_field(name="Temporary", value="Yes (kicks on disconnect)", inline=True)

        await self._send_log(LogCategory.INVITES, embed)

    async def log_invite_delete(
        self,
        invite_code: str,
        channel_name: str,
        uses: Optional[int] = None,
        moderator: Optional[discord.Member] = None,
        channel_id: Optional[int] = None,
    ) -> None:
        """Log an invite being deleted."""
        if not self.enabled:
            return

        embed = self._create_embed("🔗 Invite Deleted", EmbedColors.LOG_NEGATIVE, category="Invite Delete")
        embed.add_field(name="Code", value=f"`{invite_code}`", inline=True)
        channel_value = f"<#{channel_id}>" if channel_id else f"`{channel_name}`"
        embed.add_field(name="Channel", value=channel_value, inline=True)

        if uses is not None:
            embed.add_field(name="Times Used", value=str(uses), inline=True)

        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.INVITES, embed)

    # =========================================================================
    # Voice Server Mute/Deafen (with moderator info from audit log)
    # =========================================================================

    async def log_server_voice_mute(
        self,
        member: discord.Member,
        muted: bool,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a server voice mute/unmute from audit log."""
        if not self.enabled:
            return

        if muted:
            embed = self._create_embed("🔇 Server Voice Muted", EmbedColors.WARNING, category="Voice Mute", user_id=member.id)
        else:
            embed = self._create_embed("🔊 Server Voice Unmuted", EmbedColors.SUCCESS, category="Voice Unmute", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        if member.voice and member.voice.channel:
            embed.add_field(name="Channel", value=f"🔊 {self._format_channel(member.voice.channel)}", inline=True)

        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_server_voice_deafen(
        self,
        member: discord.Member,
        deafened: bool,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a server voice deafen/undeafen from audit log."""
        if not self.enabled:
            return

        if deafened:
            embed = self._create_embed("🔇 Server Voice Deafened", EmbedColors.WARNING, category="Voice Deafen", user_id=member.id)
        else:
            embed = self._create_embed("🔊 Server Voice Undeafened", EmbedColors.SUCCESS, category="Voice Undeafen", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        if member.voice and member.voice.channel:
            embed.add_field(name="Channel", value=f"🔊 {self._format_channel(member.voice.channel)}", inline=True)

        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    # =========================================================================
    # Member Verification (Membership Screening)
    # =========================================================================

    async def log_member_verification(
        self,
        member: discord.Member,
    ) -> None:
        """Edit the original join embed to add [Verified] when member passes screening."""
        if not self._initialized or LogCategory.JOINS not in self._threads:
            return

        # Get join message ID from database (don't clear - we still need it for leave)
        db = get_db()
        message_id = db.get_join_message_id(member.id, member.guild.id)
        if not message_id:
            return

        try:
            thread = self._threads[LogCategory.JOINS]
            message = await thread.fetch_message(message_id)

            if message.embeds:
                embed = message.embeds[0]
                # Update title to add [Verified]
                embed.title = "📥 Member Joined [Verified] ✅"
                await message.edit(embed=embed)
        except discord.NotFound:
            pass  # Message was deleted
        except Exception as e:
            logger.debug(f"Logging Service: Failed to edit join message: {e}")

    # =========================================================================
    # Nickname Force Change (by mod)
    # =========================================================================

    async def log_nickname_force_change(
        self,
        target: discord.Member,
        old_nick: Optional[str],
        new_nick: Optional[str],
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log when a mod changes someone else's nickname."""
        if not self.enabled:
            return

        embed = self._create_embed("✏️ Nickname Force Changed", EmbedColors.WARNING, category="Nickname Force", user_id=target.id)
        embed.add_field(name="Target", value=self._format_user_field(target), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        embed.add_field(name="Before", value=f"`{old_nick}`" if old_nick else "*(none)*", inline=True)
        embed.add_field(name="After", value=f"`{new_nick}`" if new_nick else "*(none)*", inline=True)

        self._set_user_thumbnail(embed, target)

        await self._send_log(LogCategory.NAME_CHANGES, embed, user_id=target.id)

    # =========================================================================
    # Voice Disconnect (by mod)
    # =========================================================================

    async def log_voice_disconnect(
        self,
        target: discord.Member,
        channel_name: str,
        moderator: Optional[discord.Member] = None,
        channel_id: Optional[int] = None,
    ) -> None:
        """Log when a mod disconnects a user from voice."""
        if not self.enabled:
            return

        embed = self._create_embed("🔌 Voice Disconnected", EmbedColors.LOG_NEGATIVE, category="Voice Disconnect", user_id=target.id)
        embed.add_field(name="User", value=self._format_user_field(target), inline=True)
        channel_value = f"🔊 <#{channel_id}>" if channel_id else f"🔊 {channel_name}"
        embed.add_field(name="From Channel", value=channel_value, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        self._set_user_thumbnail(embed, target)

        await self._send_log(LogCategory.VOICE, embed, user_id=target.id)

    # =========================================================================
    # Mod Message Delete
    # =========================================================================

    async def log_mod_message_delete(
        self,
        author: discord.User,
        channel: discord.abc.GuildChannel,
        content: Optional[str],
        moderator: Optional[discord.Member] = None,
        attachments: Optional[List[Tuple[str, bytes]]] = None,
        attachment_names: Optional[List[str]] = None,
        sticker_names: Optional[List[str]] = None,
        has_embeds: bool = False,
        embed_titles: Optional[List[str]] = None,
    ) -> None:
        """Log when a mod deletes someone else's message."""
        if not self.enabled:
            return

        embed = self._create_embed("🗑️ Message Deleted by Mod", EmbedColors.LOG_NEGATIVE, category="Mod Delete", user_id=author.id)
        embed.add_field(name="Author", value=self._format_user_field(author), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        if content:
            truncated = content[:900] if len(content) > 900 else content
            embed.add_field(name="Content", value=f"```{truncated}```", inline=False)
        else:
            # Build context string for empty content
            context_parts = []

            if attachment_names:
                files_str = ", ".join(f"`{name}`" for name in attachment_names[:5])
                if len(attachment_names) > 5:
                    files_str += f" +{len(attachment_names) - 5} more"
                context_parts.append(f"📎 **Attachments:** {files_str}")

            if sticker_names:
                stickers_str = ", ".join(f"`{name}`" for name in sticker_names[:3])
                context_parts.append(f"🎨 **Stickers:** {stickers_str}")

            if has_embeds:
                if embed_titles:
                    titles_str = ", ".join(f"`{t}`" for t in embed_titles[:3])
                    context_parts.append(f"📋 **Embeds:** {titles_str}")
                else:
                    context_parts.append("📋 **Embed** (link preview or bot embed)")

            if context_parts:
                context_str = "\n".join(context_parts)
                embed.add_field(name="Content", value=f"*(no text)*\n{context_str}", inline=False)
            elif attachment_names is None and sticker_names is None:
                # No cached data - bot was likely offline when message was sent
                embed.add_field(
                    name="Content",
                    value="*(message not cached - bot may have restarted)*",
                    inline=False,
                )
            else:
                embed.add_field(name="Content", value="*(empty message)*", inline=False)

        self._set_user_thumbnail(embed, author)

        # Prepare attachment files
        files = []
        if attachments:
            for filename, data in attachments[:5]:
                files.append(discord.File(io.BytesIO(data), filename=filename))

        await self._send_log(LogCategory.MESSAGES, embed, files, user_id=author.id)

    # =========================================================================
    # Slowmode Changes
    # =========================================================================

    async def log_slowmode_change(
        self,
        channel: discord.abc.GuildChannel,
        old_delay: int,
        new_delay: int,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log when channel slowmode is changed."""
        if not self.enabled:
            return

        embed = self._create_embed("🐌 Slowmode Changed", EmbedColors.WARNING, category="Slowmode")
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        # Format delays nicely
        def format_delay(seconds: int) -> str:
            if seconds == 0:
                return "Off"
            elif seconds < 60:
                return f"{seconds}s"
            elif seconds < 3600:
                return f"{seconds // 60}m"
            else:
                return f"{seconds // 3600}h"

        embed.add_field(name="Before", value=f"`{format_delay(old_delay)}`", inline=True)
        embed.add_field(name="After", value=f"`{format_delay(new_delay)}`", inline=True)

        await self._send_log(LogCategory.CHANNELS, embed)

    # =========================================================================
    # Thread Lock/Unlock
    # =========================================================================

    async def log_thread_lock(
        self,
        thread: discord.Thread,
        locked: bool,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log when a thread is locked or unlocked."""
        if not self.enabled:
            return

        if locked:
            embed = self._create_embed("🔒 Thread Locked", EmbedColors.WARNING, category="Thread Lock")
        else:
            embed = self._create_embed("🔓 Thread Unlocked", EmbedColors.SUCCESS, category="Thread Unlock")

        embed.add_field(name="Thread", value=f"#{thread.name}" if thread.name else "#unknown-thread", inline=True)
        if thread.parent:
            embed.add_field(name="Parent", value=self._format_channel(thread.parent), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.THREADS, embed)

    # =========================================================================
    # Thread Member Tracking
    # =========================================================================

    async def log_thread_member_add(
        self,
        thread: discord.Thread,
        user: discord.User,
        added_by: Optional[discord.User] = None,
    ) -> None:
        """Log when a member is added to a private thread."""
        if not self.enabled:
            return

        embed = self._create_embed("🔗 Added to Private Thread", EmbedColors.INFO, category="Thread Member Add")

        embed.add_field(name="Thread", value=f"#{thread.name}", inline=True)
        embed.add_field(name="User Added", value=self._format_user_field(user), inline=True)
        if added_by:
            embed.add_field(name="By", value=self._format_user_field(added_by), inline=True)
        if thread.parent:
            embed.add_field(name="Parent Channel", value=self._format_channel(thread.parent), inline=True)

        embed.set_thumbnail(url=user.display_avatar.url)

        await self._send_log(LogCategory.THREADS, embed)

        logger.tree("Thread Member Added", [
            ("Thread", thread.name),
            ("User", str(user)),
            ("Added By", str(added_by) if added_by else "Unknown"),
        ], emoji="🔗")

    async def log_thread_member_remove(
        self,
        thread: discord.Thread,
        user: discord.User,
        removed_by: Optional[discord.User] = None,
    ) -> None:
        """Log when a member is removed from a private thread."""
        if not self.enabled:
            return

        embed = self._create_embed("🔗 Removed from Private Thread", EmbedColors.WARNING, category="Thread Member Remove")

        embed.add_field(name="Thread", value=f"#{thread.name}", inline=True)
        embed.add_field(name="User Removed", value=self._format_user_field(user), inline=True)
        if removed_by:
            embed.add_field(name="By", value=self._format_user_field(removed_by), inline=True)
        if thread.parent:
            embed.add_field(name="Parent Channel", value=self._format_channel(thread.parent), inline=True)

        embed.set_thumbnail(url=user.display_avatar.url)

        await self._send_log(LogCategory.THREADS, embed)

        logger.tree("Thread Member Removed", [
            ("Thread", thread.name),
            ("User", str(user)),
            ("Removed By", str(removed_by) if removed_by else "Unknown"),
        ], emoji="🔗")

    # =========================================================================
    # Forum Tag Changes
    # =========================================================================

    async def log_forum_tag_create(
        self,
        forum: discord.ForumChannel,
        tag_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log when a forum tag is created."""
        if not self.enabled:
            return

        embed = self._create_embed("🏷️ Forum Tag Created", EmbedColors.SUCCESS, category="Tag Create")
        embed.add_field(name="Forum", value=self._format_channel(forum), inline=True)
        embed.add_field(name="Tag", value=f"`{tag_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.CHANNELS, embed)

    async def log_forum_tag_delete(
        self,
        forum: discord.ForumChannel,
        tag_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log when a forum tag is deleted."""
        if not self.enabled:
            return

        embed = self._create_embed("🏷️ Forum Tag Deleted", EmbedColors.LOG_NEGATIVE, category="Tag Delete")
        embed.add_field(name="Forum", value=self._format_channel(forum), inline=True)
        embed.add_field(name="Tag", value=f"`{tag_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.CHANNELS, embed)

    async def log_forum_tag_update(
        self,
        forum: discord.ForumChannel,
        old_name: str,
        new_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log when a forum tag is renamed."""
        if not self.enabled:
            return

        embed = self._create_embed("🏷️ Forum Tag Renamed", EmbedColors.WARNING, category="Tag Update")
        embed.add_field(name="Forum", value=self._format_channel(forum), inline=True)
        embed.add_field(name="Before", value=f"`{old_name}`", inline=True)
        embed.add_field(name="After", value=f"`{new_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.CHANNELS, embed)

    # =========================================================================
    # Channel Category Move
    # =========================================================================

    async def log_channel_category_move(
        self,
        channel: discord.abc.GuildChannel,
        old_category: Optional[str],
        new_category: Optional[str],
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log when a channel is moved between categories."""
        if not self.enabled:
            return

        embed = self._create_embed("📂 Channel Moved", EmbedColors.WARNING, category="Category Move")
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        embed.add_field(
            name="From Category",
            value=f"`{old_category}`" if old_category else "*(no category)*",
            inline=True,
        )
        embed.add_field(
            name="To Category",
            value=f"`{new_category}`" if new_category else "*(no category)*",
            inline=True,
        )

        await self._send_log(LogCategory.CHANNELS, embed)

    # =========================================================================
    # Role Hierarchy Changes
    # =========================================================================

    async def log_role_position_change(
        self,
        role: discord.Role,
        old_position: int,
        new_position: int,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log when a role's position in hierarchy changes."""
        if not self.enabled:
            return

        # Determine if moved up or down
        if new_position > old_position:
            embed = self._create_embed("⬆️ Role Moved Up", EmbedColors.SUCCESS, category="Role Position")
            direction = "higher"
        else:
            embed = self._create_embed("⬇️ Role Moved Down", EmbedColors.WARNING, category="Role Position")
            direction = "lower"

        embed.add_field(name="Role", value=self._format_role(role), inline=True)
        embed.add_field(name="Position", value=f"`{old_position}` → `{new_position}` ({direction})", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.ROLES, embed)

    # =========================================================================
    # Raid Detection Alerts
    # =========================================================================

    async def log_raid_alert(
        self,
        join_count: int,
        time_window: int,
        recent_members: List[discord.Member],
    ) -> None:
        """Log a potential raid alert."""
        if not self.enabled:
            return

        embed = self._create_embed("🚨 POTENTIAL RAID DETECTED", EmbedColors.LOG_NEGATIVE, category="Raid Alert")
        embed.add_field(
            name="Joins Detected",
            value=f"**{join_count}** members in **{time_window}** seconds",
            inline=False,
        )

        # List recent joiners (up to 10)
        if recent_members:
            members_list = []
            for member in recent_members[:10]:
                created = int(member.created_at.timestamp())
                members_list.append(f"{member.mention} - Account: <t:{created}:R>")

            if len(recent_members) > 10:
                members_list.append(f"*...and {len(recent_members) - 10} more*")

            embed.add_field(
                name="Recent Joins",
                value="\n".join(members_list),
                inline=False,
            )

        embed.add_field(
            name="⚠️ Recommended Actions",
            value="• Enable verification level\n• Check member accounts\n• Consider lockdown if malicious",
            inline=False,
        )

        await self._send_log(LogCategory.ALERTS, embed)

    # =========================================================================
    # Lockdown Logs
    # =========================================================================

    async def log_lockdown(
        self,
        moderator: discord.Member,
        reason: Optional[str],
        channel_count: int,
        action: str,
    ) -> None:
        """
        Log a server lockdown or unlock action.

        Args:
            moderator: Moderator who initiated the action.
            reason: Reason for lockdown (None for unlock).
            channel_count: Number of channels affected.
            action: 'lock' or 'unlock'.
        """
        if not self.enabled:
            return

        if action == "lock":
            embed = self._create_embed("🔒 SERVER LOCKED", EmbedColors.LOG_NEGATIVE, category="Lockdown")
            embed.add_field(name="Status", value="**All channels locked**", inline=False)
        else:
            embed = self._create_embed("🔓 SERVER UNLOCKED", EmbedColors.SUCCESS, category="Lockdown")
            embed.add_field(name="Status", value="**All channels restored**", inline=False)

        embed.add_field(name="By", value=moderator.mention, inline=True)
        embed.add_field(name="Channels", value=f"`{channel_count}`", inline=True)

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        await self._send_log(LogCategory.ALERTS, embed)

        # Ping developer for dangerous lockdown command
        if action == "lock" and self.config.developer_id:
            thread = self._threads.get(LogCategory.ALERTS)
            if thread:
                await thread.send(f"<@{self.config.developer_id}> ⚠️ **Server lockdown initiated**")

    async def log_auto_lockdown(
        self,
        join_count: int,
        time_window: int,
        auto_unlock_in: int,
    ) -> None:
        """
        Log an automatic raid lockdown.

        Args:
            join_count: Number of joins that triggered the lockdown.
            time_window: Time window in seconds.
            auto_unlock_in: Seconds until auto-unlock.
        """
        if not self.enabled:
            return

        embed = self._create_embed("🚨 AUTO-LOCKDOWN TRIGGERED", 0xFF0000, category="Lockdown")
        embed.add_field(name="Status", value="**Server automatically locked - RAID DETECTED**", inline=False)
        embed.add_field(name="Trigger", value=f"`{join_count}` joins in `{time_window}s`", inline=True)
        embed.add_field(name="Auto-Unlock", value=f"In `{auto_unlock_in}s`", inline=True)
        embed.add_field(name="Action", value="Use `/unlock` to unlock manually", inline=False)

        await self._send_log(LogCategory.ALERTS, embed)

        # Ping developer for raid alert
        if self.config.developer_id:
            thread = self._threads.get(LogCategory.ALERTS)
            if thread:
                await thread.send(
                    f"<@{self.config.developer_id}> 🚨 **RAID DETECTED - AUTO-LOCKDOWN TRIGGERED!**\n"
                    f"Detected {join_count} joins in {time_window}s. Auto-unlock in {auto_unlock_in}s."
                )

    async def log_auto_unlock(self) -> None:
        """Log an automatic unlock after raid lockdown expires."""
        if not self.enabled:
            return

        embed = self._create_embed("🔓 AUTO-UNLOCK", EmbedColors.SUCCESS, category="Lockdown")
        embed.add_field(name="Status", value="**Raid lockdown has expired**", inline=False)
        embed.add_field(name="Action", value="Server permissions restored automatically", inline=False)

        await self._send_log(LogCategory.ALERTS, embed)

    # =========================================================================
    # Tickets
    # =========================================================================

    async def log_ticket_created(
        self,
        ticket_id: str,
        user: discord.User,
        category: str,
        subject: str,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log a ticket creation."""
        if not self.enabled:
            return

        embed = self._create_embed(
            "🎫 Ticket Created",
            EmbedColors.SUCCESS,
            category="Ticket",
            user_id=user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Subject", value=subject[:200] if subject else "No subject", inline=False)
        self._set_user_thumbnail(embed, user)

        view = TicketLogView(guild_id, thread_id)
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_claimed(
        self,
        ticket_id: str,
        user: discord.User,
        staff: discord.Member,
        category: str,
        thread_id: int,
        guild_id: int,
        created_at: float,
    ) -> None:
        """Log a ticket claim."""
        if not self.enabled:
            return

        # Calculate response time
        import time
        response_seconds = int(time.time() - created_at)
        if response_seconds < 60:
            response_time = f"{response_seconds}s"
        elif response_seconds < 3600:
            response_time = f"{response_seconds // 60}m {response_seconds % 60}s"
        elif response_seconds < 86400:
            hours = response_seconds // 3600
            mins = (response_seconds % 3600) // 60
            response_time = f"{hours}h {mins}m"
        else:
            days = response_seconds // 86400
            hours = (response_seconds % 86400) // 3600
            response_time = f"{days}d {hours}h"

        embed = self._create_embed(
            "✋ Ticket Claimed",
            EmbedColors.GOLD,
            category="Ticket",
            user_id=user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Response Time", value=f"⏱️ {response_time}", inline=True)
        embed.add_field(name="Opened By", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Claimed By", value=self._format_user_field(staff), inline=True)
        self._set_user_thumbnail(embed, staff)

        view = TicketLogView(guild_id, thread_id)
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_closed(
        self,
        ticket_id: str,
        user: discord.User,
        closed_by: discord.Member,
        category: str,
        thread_id: int,
        guild_id: int,
        reason: Optional[str] = None,
    ) -> None:
        """Log a ticket close."""
        if not self.enabled:
            return

        embed = self._create_embed(
            "🔒 Ticket Closed",
            EmbedColors.LOG_NEGATIVE,
            category="Ticket",
            user_id=user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Opened By", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Closed By", value=self._format_user_field(closed_by), inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason[:500], inline=False)
        self._set_user_thumbnail(embed, closed_by)

        # Create view with Open Ticket + Transcript + Case buttons
        view = TicketLogView(guild_id, thread_id)
        transcript_url = f"https://trippixn.com/api/azab/transcripts/{ticket_id}"
        view.add_item(discord.ui.Button(
            label="Transcript",
            url=transcript_url,
            style=discord.ButtonStyle.link,
            emoji=TRANSCRIPT_EMOJI,
        ))
        # Add case button if user has a case log
        db = get_db()
        case = db.get_case_log(user.id)
        if case:
            case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
            view.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_reopened(
        self,
        ticket_id: str,
        user: discord.User,
        reopened_by: discord.Member,
        category: str,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log a ticket reopen."""
        if not self.enabled:
            return

        embed = self._create_embed(
            "🔓 Ticket Reopened",
            EmbedColors.SUCCESS,
            category="Ticket",
            user_id=user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Opened By", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Reopened By", value=self._format_user_field(reopened_by), inline=True)
        self._set_user_thumbnail(embed, reopened_by)

        view = TicketLogView(guild_id, thread_id)
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_user_added(
        self,
        ticket_id: str,
        ticket_user: discord.User,
        added_user: discord.User,
        added_by: discord.Member,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log a user being added to a ticket."""
        if not self.enabled:
            return

        embed = self._create_embed(
            "👤 User Added to Ticket",
            EmbedColors.BLUE,
            category="Ticket",
            user_id=added_user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Ticket Owner", value=self._format_user_field(ticket_user), inline=True)
        embed.add_field(name="User Added", value=self._format_user_field(added_user), inline=True)
        embed.add_field(name="Added By", value=self._format_user_field(added_by), inline=True)
        self._set_user_thumbnail(embed, added_user)

        view = TicketLogView(guild_id, thread_id)
        view.add_item(UserIdButton(added_user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_transferred(
        self,
        ticket_id: str,
        ticket_user: discord.User,
        new_staff: discord.Member,
        transferred_by: discord.Member,
        category: str,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log a ticket transfer."""
        if not self.enabled:
            return

        embed = self._create_embed(
            "↔️ Ticket Transferred",
            EmbedColors.BLUE,
            category="Ticket",
            user_id=ticket_user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Ticket Owner", value=self._format_user_field(ticket_user), inline=True)
        embed.add_field(name="Transferred To", value=self._format_user_field(new_staff), inline=True)
        embed.add_field(name="Transferred By", value=self._format_user_field(transferred_by), inline=True)
        self._set_user_thumbnail(embed, new_staff)

        view = TicketLogView(guild_id, thread_id)
        view.add_item(UserIdButton(ticket_user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_priority_changed(
        self,
        ticket_id: str,
        ticket_user: discord.User,
        changed_by: discord.Member,
        old_priority: str,
        new_priority: str,
        category: str,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log a ticket priority change."""
        if not self.enabled:
            return

        priority_colors = {
            "low": 0x808080,
            "normal": EmbedColors.BLUE,
            "high": 0xFFA500,
            "urgent": EmbedColors.LOG_NEGATIVE,
        }

        embed = self._create_embed(
            "📊 Ticket Priority Changed",
            priority_colors.get(new_priority, EmbedColors.BLUE),
            category="Ticket",
            user_id=ticket_user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Priority", value=f"{old_priority.title()} → **{new_priority.title()}**", inline=True)
        embed.add_field(name="Ticket Owner", value=self._format_user_field(ticket_user), inline=True)
        embed.add_field(name="Changed By", value=self._format_user_field(changed_by), inline=True)
        self._set_user_thumbnail(embed, changed_by)

        view = TicketLogView(guild_id, thread_id)
        view.add_item(UserIdButton(ticket_user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_transcript(
        self,
        ticket_id: str,
        user: discord.User,
        category: str,
        subject: str,
        messages: list,
        closed_by: discord.Member,
        created_at: float,
        closed_at: float,
    ) -> None:
        """Log a ticket transcript when closed."""
        if not self.enabled:
            return

        # Format timestamps
        from datetime import datetime
        import html as html_lib
        created_dt = datetime.fromtimestamp(created_at, tz=NY_TZ)
        closed_dt = datetime.fromtimestamp(closed_at, tz=NY_TZ)
        duration = closed_dt - created_dt

        # Calculate duration string
        days = duration.days
        hours, remainder = divmod(duration.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if days > 0:
            duration_str = f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            duration_str = f"{hours}h {minutes}m"
        else:
            duration_str = f"{minutes}m"

        embed = self._create_embed(
            f"📜 Ticket Transcript - {ticket_id}",
            EmbedColors.BLUE,
            category="Transcript",
            user_id=user.id,
        )

        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Messages", value=str(len(messages)), inline=True)
        embed.add_field(name="Opened By", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Closed By", value=self._format_user_field(closed_by), inline=True)
        embed.add_field(name="Duration", value=duration_str, inline=True)
        embed.add_field(name="Subject", value=subject[:200] if subject else "No subject", inline=False)

        # Generate HTML transcript
        html_content = self._generate_transcript_html(
            ticket_id=ticket_id,
            category=category,
            subject=subject,
            user=user,
            closed_by=closed_by,
            created_dt=created_dt,
            closed_dt=closed_dt,
            duration_str=duration_str,
            messages=messages,
        )

        # Create HTML file attachment
        transcript_file = discord.File(
            io.BytesIO(html_content.encode("utf-8")),
            filename=f"transcript_{ticket_id}.html",
        )

        self._set_user_thumbnail(embed, user)

        # Create view with link button to website transcript
        transcript_url = f"https://trippixn.com/api/azab/transcripts/{ticket_id}"
        view = TranscriptLinkView(transcript_url)

        await self._send_log(LogCategory.TICKET_TRANSCRIPTS, embed, files=[transcript_file], view=view, user_id=user.id)

    def _generate_transcript_html(
        self,
        ticket_id: str,
        category: str,
        subject: str,
        user: discord.User,
        closed_by: discord.Member,
        created_dt,
        closed_dt,
        duration_str: str,
        messages: list,
    ) -> str:
        """Generate a beautiful HTML transcript."""
        import html as html_lib

        html_output = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ticket {ticket_id} - Transcript</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e4e4e4;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 40px rgba(102, 126, 234, 0.3);
        }}
        .header h1 {{
            font-size: 28px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .header h1 .emoji {{ font-size: 32px; }}
        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        .meta-item {{
            background: rgba(255,255,255,0.1);
            padding: 12px 16px;
            border-radius: 8px;
        }}
        .meta-item .label {{
            font-size: 12px;
            text-transform: uppercase;
            opacity: 0.7;
            margin-bottom: 4px;
        }}
        .meta-item .value {{
            font-size: 16px;
            font-weight: 600;
        }}
        .messages {{
            background: #0d1117;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }}
        .messages-header {{
            background: #161b22;
            padding: 16px 20px;
            border-bottom: 1px solid #30363d;
            font-weight: 600;
            color: #8b949e;
        }}
        .message {{
            display: flex;
            padding: 16px 20px;
            border-bottom: 1px solid #21262d;
            transition: background 0.2s;
        }}
        .message:hover {{
            background: rgba(255,255,255,0.02);
        }}
        .message:last-child {{
            border-bottom: none;
        }}
        .avatar {{
            width: 44px;
            height: 44px;
            border-radius: 50%;
            margin-right: 16px;
            flex-shrink: 0;
            background: #30363d;
        }}
        .message-content {{
            flex: 1;
            min-width: 0;
        }}
        .message-header {{
            display: flex;
            align-items: baseline;
            gap: 8px;
            margin-bottom: 6px;
        }}
        .author {{
            font-weight: 600;
            color: #58a6ff;
        }}
        .author.staff {{
            color: #f0883e;
        }}
        .author.bot {{
            color: #a371f7;
        }}
        .timestamp {{
            font-size: 12px;
            color: #8b949e;
        }}
        .content {{
            line-height: 1.5;
            word-wrap: break-word;
            white-space: pre-wrap;
        }}
        .attachments {{
            margin-top: 10px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .attachment {{
            background: #21262d;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 13px;
            color: #58a6ff;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .attachment:hover {{
            background: #30363d;
        }}
        .footer {{
            text-align: center;
            padding: 30px;
            color: #8b949e;
            font-size: 14px;
        }}
        .empty-message {{
            color: #8b949e;
            font-style: italic;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><span class="emoji">🎫</span> Ticket {ticket_id}</h1>
            <div class="meta-grid">
                <div class="meta-item">
                    <div class="label">Category</div>
                    <div class="value">{category.title()}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Status</div>
                    <div class="value">Closed</div>
                </div>
                <div class="meta-item">
                    <div class="label">Opened By</div>
                    <div class="value">{html_lib.escape(user.display_name)}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Closed By</div>
                    <div class="value">{html_lib.escape(closed_by.display_name)}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Created</div>
                    <div class="value">{created_dt.strftime("%b %d, %Y %I:%M %p")}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Duration</div>
                    <div class="value">{duration_str}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Subject</div>
                    <div class="value">{html_lib.escape(subject[:50])}{"..." if len(subject) > 50 else ""}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Messages</div>
                    <div class="value">{len(messages)}</div>
                </div>
            </div>
        </div>

        <div class="messages">
            <div class="messages-header">📝 Conversation</div>
'''

        for msg in messages:
            author = msg.get("author", "Unknown")
            author_id = msg.get("author_id", "0")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")
            attachments = msg.get("attachments", [])
            avatar_url = msg.get("avatar_url", "")
            is_staff = msg.get("is_staff", False)

            # Determine author class
            author_class = "staff" if is_staff else ""
            if "Bot" in author:
                author_class = "bot"

            # Escape HTML in content
            safe_content = html_lib.escape(content) if content else '<span class="empty-message">(no text content)</span>'

            html_output += f'''
            <div class="message">
                <img class="avatar" src="{avatar_url or 'https://cdn.discordapp.com/embed/avatars/0.png'}" alt="avatar" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
                <div class="message-content">
                    <div class="message-header">
                        <span class="author {author_class}">{html_lib.escape(author)}</span>
                        <span class="timestamp">{timestamp}</span>
                    </div>
                    <div class="content">{safe_content}</div>
'''
            if attachments:
                html_output += '                    <div class="attachments">\n'
                for att in attachments:
                    filename = att.split("/")[-1].split("?")[0] if att else "attachment"
                    html_output += f'                        <a class="attachment" href="{att}" target="_blank">📎 {html_lib.escape(filename[:30])}</a>\n'
                html_output += '                    </div>\n'

            html_output += '''                </div>
            </div>
'''

        html_output += f'''        </div>

        <div class="footer">
            Generated on {closed_dt.strftime("%B %d, %Y at %I:%M %p %Z")}<br>
            🎫 AzabBot Ticket System
        </div>
    </div>
</body>
</html>'''

        return html_output

    # =========================================================================
    # Appeal Logging
    # =========================================================================

    async def log_appeal_created(
        self,
        appeal_id: str,
        case_id: str,
        user: discord.User,
        action_type: str,
        reason: Optional[str] = None,
    ) -> None:
        """Log an appeal creation."""
        if not self.enabled:
            return

        emoji = "🔨" if action_type == "ban" else "🔇"
        embed = self._create_embed(
            f"{emoji} Appeal Created",
            EmbedColors.GOLD,
            category="Appeal",
            user_id=user.id,
        )
        embed.add_field(name="Appeal ID", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Case ID", value=f"`{case_id}`", inline=True)
        embed.add_field(name="Type", value=action_type.title(), inline=True)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if reason:
            embed.add_field(name="Appeal Reason", value=reason[:500], inline=False)
        self._set_user_thumbnail(embed, user)

        # Create view with Case button
        view = discord.ui.View(timeout=None)
        db = get_db()
        case = db.get_case_log(user.id)
        if case:
            case_url = f"https://discord.com/channels/{case['guild_id']}/{case['thread_id']}"
            view.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.APPEALS, embed, view=view, user_id=user.id)

    async def log_appeal_approved(
        self,
        appeal_id: str,
        case_id: str,
        user: discord.User,
        action_type: str,
        approved_by: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        """Log an appeal approval."""
        if not self.enabled:
            return

        embed = self._create_embed(
            "✅ Appeal Approved",
            EmbedColors.SUCCESS,
            category="Appeal",
            user_id=user.id,
        )
        embed.add_field(name="Appeal ID", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Case ID", value=f"`{case_id}`", inline=True)
        embed.add_field(name="Type", value=action_type.title(), inline=True)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Approved By", value=self._format_user_field(approved_by), inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason[:500], inline=False)
        self._set_user_thumbnail(embed, approved_by)

        # Create view with Case button
        view = discord.ui.View(timeout=None)
        db = get_db()
        case = db.get_case_log(user.id)
        if case:
            case_url = f"https://discord.com/channels/{case['guild_id']}/{case['thread_id']}"
            view.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.APPEALS, embed, view=view, user_id=user.id)

    async def log_appeal_denied(
        self,
        appeal_id: str,
        case_id: str,
        user: discord.User,
        action_type: str,
        denied_by: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        """Log an appeal denial."""
        if not self.enabled:
            return

        embed = self._create_embed(
            "❌ Appeal Denied",
            EmbedColors.LOG_NEGATIVE,
            category="Appeal",
            user_id=user.id,
        )
        embed.add_field(name="Appeal ID", value=f"`{appeal_id}`", inline=True)
        embed.add_field(name="Case ID", value=f"`{case_id}`", inline=True)
        embed.add_field(name="Type", value=action_type.title(), inline=True)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Denied By", value=self._format_user_field(denied_by), inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason[:500], inline=False)
        self._set_user_thumbnail(embed, denied_by)

        # Create view with Case button
        view = discord.ui.View(timeout=None)
        db = get_db()
        case = db.get_case_log(user.id)
        if case:
            case_url = f"https://discord.com/channels/{case['guild_id']}/{case['thread_id']}"
            view.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.APPEALS, embed, view=view, user_id=user.id)

    # =========================================================================
    # Modmail Logging
    # =========================================================================

    async def log_modmail_created(
        self,
        user: discord.User,
        thread_id: int,
    ) -> None:
        """Log a modmail thread creation."""
        if not self.enabled:
            return

        embed = self._create_embed(
            "📬 Modmail Created",
            EmbedColors.SUCCESS,
            category="Modmail",
            user_id=user.id,
        )
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Status", value="Banned User", inline=True)
        self._set_user_thumbnail(embed, user)

        # Create view with Thread and UserID buttons
        view = discord.ui.View(timeout=None)
        guild_id = self.config.logging_guild_id or self.config.mod_guild_id or 0
        if guild_id and thread_id:
            thread_url = f"https://discord.com/channels/{guild_id}/{thread_id}"
            view.add_item(discord.ui.Button(
                label="Thread",
                url=thread_url,
                style=discord.ButtonStyle.link,
                emoji=MESSAGE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.MODMAIL, embed, view=view, user_id=user.id)

    async def log_modmail_closed(
        self,
        user: discord.User,
        closed_by: discord.Member,
        thread_id: int,
    ) -> None:
        """Log a modmail thread close."""
        if not self.enabled:
            return

        embed = self._create_embed(
            "🔒 Modmail Closed",
            EmbedColors.LOG_NEGATIVE,
            category="Modmail",
            user_id=user.id,
        )
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Closed By", value=self._format_user_field(closed_by), inline=True)
        self._set_user_thumbnail(embed, closed_by)

        # Create view with Thread and UserID buttons
        view = discord.ui.View(timeout=None)
        guild_id = self.config.logging_guild_id or self.config.mod_guild_id or 0
        if guild_id and thread_id:
            thread_url = f"https://discord.com/channels/{guild_id}/{thread_id}"
            view.add_item(discord.ui.Button(
                label="Thread",
                url=thread_url,
                style=discord.ButtonStyle.link,
                emoji=MESSAGE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.MODMAIL, embed, view=view, user_id=user.id)

    async def log_modmail_message(
        self,
        user: discord.User,
        direction: str,
        content: str,
        staff: Optional[discord.Member] = None,
    ) -> None:
        """Log a modmail message relay."""
        if not self.enabled:
            return

        if direction == "incoming":
            title = "📥 Modmail Received"
            color = EmbedColors.BLUE
        else:
            title = "📤 Modmail Sent"
            color = EmbedColors.SUCCESS

        embed = self._create_embed(
            title,
            color,
            category="Modmail",
            user_id=user.id,
        )
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if staff:
            embed.add_field(name="Staff", value=self._format_user_field(staff), inline=True)
        embed.add_field(name="Content", value=content[:500] if content else "*No content*", inline=False)
        self._set_user_thumbnail(embed, user)

        # Create view with UserID button
        view = discord.ui.View(timeout=None)
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.MODMAIL, embed, view=view, user_id=user.id)

    # =========================================================================
    # Warning Logging
    # =========================================================================

    async def log_warning_issued(
        self,
        user: discord.User,
        moderator: discord.Member,
        reason: str,
        warning_count: int,
        guild_id: int,
    ) -> None:
        """Log a warning issued to a user."""
        if not self.enabled:
            return

        embed = self._create_embed(
            "⚠️ Warning Issued",
            EmbedColors.GOLD,
            category="Warning",
            user_id=user.id,
        )
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Moderator", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Total Warnings", value=str(warning_count), inline=True)
        embed.add_field(name="Reason", value=reason[:500] if reason else "No reason provided", inline=False)
        self._set_user_thumbnail(embed, user)

        # Create view with Case and UserID buttons
        view = discord.ui.View(timeout=None)
        db = get_db()
        case = db.get_case_log(user.id)
        if case:
            case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
            view.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.WARNINGS, embed, view=view, user_id=user.id)

    async def log_warning_removed(
        self,
        user: discord.User,
        moderator: discord.Member,
        warning_id: int,
        remaining_count: int,
    ) -> None:
        """Log a warning removal."""
        if not self.enabled:
            return

        embed = self._create_embed(
            "🗑️ Warning Removed",
            EmbedColors.SUCCESS,
            category="Warning",
            user_id=user.id,
        )
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Removed By", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Warning ID", value=f"`#{warning_id}`", inline=True)
        embed.add_field(name="Remaining", value=str(remaining_count), inline=True)
        self._set_user_thumbnail(embed, moderator)

        # Create view with Case and UserID buttons
        view = discord.ui.View(timeout=None)
        db = get_db()
        case = db.get_case_log(user.id)
        if case:
            guild_id = self.config.logging_guild_id or case.get('guild_id', 0)
            case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
            view.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.WARNINGS, embed, view=view, user_id=user.id)

    # =========================================================================
    # Audit Raw Logging
    # =========================================================================

    async def log_audit_raw(
        self,
        action: str,
        user: Optional[discord.User],
        target: Optional[discord.User],
        details: str,
        audit_id: Optional[int] = None,
    ) -> None:
        """Log an uncategorized audit log event."""
        if not self.enabled:
            return

        embed = self._create_embed(
            f"🔍 {action}",
            EmbedColors.BLUE,
            category="Audit",
            user_id=user.id if user else None,
        )
        if user:
            embed.add_field(name="Actor", value=self._format_user_field(user), inline=True)
        if target:
            embed.add_field(name="Target", value=self._format_user_field(target), inline=True)
        if audit_id:
            embed.add_field(name="Audit ID", value=f"`{audit_id}`", inline=True)
        embed.add_field(name="Details", value=details[:1000], inline=False)
        if user:
            self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.AUDIT_RAW, embed, user_id=user.id if user else None)

    # =========================================================================
    # Log Retention / Cleanup
    # =========================================================================

    async def start_retention_cleanup(self) -> None:
        """Start the scheduled log retention cleanup task."""
        if not self.enabled or self.config.log_retention_days <= 0:
            logger.debug("Log retention cleanup disabled")
            return

        create_safe_task(self._retention_cleanup_loop(), "Log Retention Cleanup")
        logger.tree("Log Retention Started", [
            ("Retention", f"{self.config.log_retention_days} days"),
            ("Schedule", "Daily at 3:00 AM EST"),
        ], emoji="🗑️")

    async def _retention_cleanup_loop(self) -> None:
        """Loop that runs retention cleanup daily at 3 AM EST."""
        from datetime import timedelta

        while True:
            try:
                # Calculate time until 3 AM EST
                now = datetime.now(NY_TZ)
                target = now.replace(hour=3, minute=0, second=0, microsecond=0)
                if now >= target:
                    target = target + timedelta(days=1)

                wait_seconds = (target - now).total_seconds()
                await asyncio.sleep(wait_seconds)

                # Run cleanup
                await self._cleanup_old_logs()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Log Retention Loop Error", [("Error", str(e))])
                await asyncio.sleep(3600)  # Wait 1 hour on error

    async def _cleanup_old_logs(self) -> None:
        """Delete log messages older than retention period."""
        from datetime import timedelta

        if not self.enabled or self.config.log_retention_days <= 0:
            return

        if not self._forum:
            return

        retention_days = self.config.log_retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        total_deleted = 0
        threads_cleaned = 0

        try:
            # Get all threads in the forum
            threads = []
            for thread in self._forum.threads:
                threads.append(thread)

            # Also get archived threads
            async for thread in self._forum.archived_threads(limit=50):
                threads.append(thread)

            for thread in threads:
                try:
                    deleted_in_thread = 0

                    # Iterate messages older than cutoff
                    async for message in thread.history(limit=500, before=cutoff, oldest_first=True):
                        # Skip pinned messages
                        if message.pinned:
                            continue

                        try:
                            await message.delete()
                            deleted_in_thread += 1
                            total_deleted += 1

                            # Rate limit - use bulk_operation bucket
                            await rate_limit("bulk_operation")

                        except (discord.NotFound, discord.Forbidden):
                            pass
                        except Exception as e:
                            logger.debug(f"Retention delete failed: {e}")

                    if deleted_in_thread > 0:
                        threads_cleaned += 1
                        logger.debug(f"Retention: Cleaned {deleted_in_thread} from #{thread.name}")

                except Exception as e:
                    logger.debug(f"Retention thread error ({thread.name}): {e}")

            if total_deleted > 0:
                logger.tree("Log Retention Cleanup Complete", [
                    ("Threads", str(threads_cleaned)),
                    ("Messages Deleted", str(total_deleted)),
                    ("Retention", f"{retention_days} days"),
                ], emoji="🗑️")

        except Exception as e:
            logger.error("Log Retention Cleanup Failed", [("Error", str(e))])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["LoggingService", "LogCategory", "LogView", "UserIdButton", "setup_log_views"]
