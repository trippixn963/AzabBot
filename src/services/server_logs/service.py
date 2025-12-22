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
from src.utils.views import DownloadButton, CASE_EMOJI

# Import from local package
from .categories import LogCategory, THREAD_DESCRIPTIONS

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# UI Constants
# =============================================================================

USERID_EMOJI = "<:userid:1452512424354643969>"


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


def setup_log_views(bot: "AzabBot") -> None:
    """Register persistent views for log buttons. Call this on bot startup."""
    # Add a dynamic view that handles all log_userid:* patterns
    bot.add_dynamic_items(UserIdButton)


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
        # Cache to track join log messages for later editing (user_id -> message_id)
        self._join_messages: Dict[int, int] = {}

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
        """Format channel reference with fallback to name if mention fails."""
        if channel is None:
            return "#unknown"
        try:
            if hasattr(channel, 'name') and channel.name:
                return f"#{channel.name}"
            elif hasattr(channel, 'id'):
                return f"#channel-{channel.id}"
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

            self._initialized = True
            logger.tree("Logging Service Initialized", [
                ("Forum", self._forum.name),
                ("Threads", str(len(self._threads))),
            ], emoji="✅")

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
                    await asyncio.sleep(self.config.rate_limit_delay / 2)  # Rate limit
                except Exception as e:
                    logger.warning(f"Logging Service: Failed to create thread {thread_name}: {e}")

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
        """Format user field without ID (ID goes in footer)."""
        return f"{user.mention}\n`{user.name}`"

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
    ) -> Optional[discord.Message]:
        """Send a log to the appropriate thread. Returns the message if successful."""
        if not self._initialized or category not in self._threads:
            return None

        try:
            thread = self._threads[category]
            # Create view with Case/UserID/Download buttons if user_id is provided
            view = LogView(user_id, thread.guild.id) if user_id else None
            message = await thread.send(embed=embed, files=files or [], view=view)
            return message
        except discord.Forbidden:
            return None
        except Exception as e:
            logger.debug(f"Logging Service: Send failed: {e}")
            return None

    # =========================================================================
    # Bans & Kicks
    # =========================================================================

    async def log_ban(
        self,
        user: discord.User,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Log a ban."""
        if not self.enabled:
            return

        embed = self._create_embed("🔨 Member Banned", EmbedColors.ERROR, category="Ban", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.BANS_KICKS, embed, user_id=user.id)

    async def log_unban(
        self,
        user: discord.User,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Log an unban."""
        if not self.enabled:
            return

        embed = self._create_embed("🔓 Member Unbanned", EmbedColors.SUCCESS, category="Unban", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.BANS_KICKS, embed, user_id=user.id)

    async def log_kick(
        self,
        user: discord.User,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Log a kick."""
        if not self.enabled:
            return

        embed = self._create_embed("👢 Member Kicked", EmbedColors.WARNING, category="Kick", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.BANS_KICKS, embed, user_id=user.id)

    # =========================================================================
    # Mutes & Timeouts
    # =========================================================================

    async def log_timeout(
        self,
        user: discord.Member,
        until: Optional[datetime] = None,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Log a timeout."""
        if not self._should_log(user.guild.id):
            return

        embed = self._create_embed("⏰ Member Timed Out", EmbedColors.WARNING, category="Timeout", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="Moderator", value=moderator.mention, inline=True)

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

        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=user.id)

    async def log_timeout_remove(
        self,
        user: discord.Member,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a timeout removal."""
        if not self._should_log(user.guild.id):
            return

        embed = self._create_embed("⏰ Timeout Removed", EmbedColors.SUCCESS, category="Timeout Remove", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=user.id)

    async def log_mute(
        self,
        user: discord.Member,
        moderator: Optional[discord.Member] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Log a mute (role-based)."""
        if not self._should_log(user.guild.id):
            return

        embed = self._create_embed("🔇 Member Muted", EmbedColors.ERROR, category="Mute", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Reason", value=self._format_reason(reason), inline=False)
        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=user.id)

    async def log_unmute(
        self,
        user: discord.Member,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log an unmute (role-based)."""
        if not self._should_log(user.guild.id):
            return

        embed = self._create_embed("🔊 Member Unmuted", EmbedColors.SUCCESS, category="Unmute", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        if moderator:
            embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.MUTES_TIMEOUTS, embed, user_id=user.id)

    async def log_muted_vc_violation(
        self,
        member: discord.Member,
        channel_name: str,
        timeout_duration: "timedelta",
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
        embed.add_field(name="Attempted Channel", value=f"🔊 {channel_name}", inline=True)
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

        embed = self._create_embed("🗑️ Message Deleted", EmbedColors.ERROR, category="Message Delete", user_id=message.author.id)
        embed.add_field(name="Author", value=self._format_user_field(message.author), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(message.channel), inline=True)

        content = f"```{message.content[:900]}```" if message.content else "*(no content)*"
        embed.add_field(name="Content", value=content, inline=False)

        # Handle reply info
        if message.reference and message.reference.message_id:
            embed.add_field(
                name="Reply To",
                value=f"Message ID: `{message.reference.message_id}`",
                inline=True,
            )

        self._set_user_thumbnail(embed, message.author)

        # Prepare files
        files = []
        if attachments:
            for filename, data in attachments[:5]:  # Max 5 files
                files.append(discord.File(io.BytesIO(data), filename=filename))

        await self._send_log(LogCategory.MESSAGES, embed, files, user_id=message.author.id)

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
        embed.add_field(
            name="Jump",
            value=f"[Go to message]({after.jump_url})",
            inline=True,
        )

        before_content = f"```{before.content[:400]}```" if before.content else "*(empty)*"
        after_content = f"```{after.content[:400]}```" if after.content else "*(empty)*"

        embed.add_field(name="Before", value=before_content, inline=False)
        embed.add_field(name="After", value=after_content, inline=False)

        self._set_user_thumbnail(embed, after.author)

        await self._send_log(LogCategory.MESSAGES, embed, user_id=after.author.id)

    async def log_bulk_delete(
        self,
        channel: discord.TextChannel,
        count: int,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a bulk message delete."""
        if not self.enabled:
            return

        embed = self._create_embed("🗑️ Bulk Delete", EmbedColors.ERROR, category="Bulk Delete")
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        embed.add_field(name="Messages", value=f"**{count}**", inline=True)
        if moderator:
            embed.add_field(name="Moderator", value=moderator.mention, inline=True)

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

        # Record join and get count
        db = get_db()
        join_count = db.record_member_join(member.id, member.guild.id)

        embed = self._create_embed("📥 Member Joined", EmbedColors.SUCCESS, category="Join", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)

        # Account age
        created = int(member.created_at.timestamp())
        embed.add_field(name="Account Created", value=f"<t:{created}:R>", inline=True)

        if invite_code:
            embed.add_field(name="Invite", value=f"`{invite_code}`", inline=True)
        if inviter:
            embed.add_field(name="Invited By", value=inviter.mention, inline=True)

        # Join counter
        if join_count > 1:
            embed.add_field(name="Join #", value=f"```{join_count}```", inline=True)

        self._set_user_thumbnail(embed, member)

        message = await self._send_log(LogCategory.JOINS, embed, user_id=member.id)
        # Store message ID for later editing when member verifies
        if message:
            self._join_messages[member.id] = message.id

    # =========================================================================
    # Member Leaves
    # =========================================================================

    async def log_member_leave(
        self,
        member: discord.Member,
    ) -> None:
        """Log a member leave with detailed info."""
        # Clean up join message cache
        self._join_messages.pop(member.id, None)

        if not self._should_log(member.guild.id, member.id):
            return

        # Record leave and get count
        db = get_db()
        leave_count = db.record_member_leave(member.id, member.guild.id)

        embed = self._create_embed("📤 Member Left", EmbedColors.ERROR, category="Leave", user_id=member.id)
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
            embed.add_field(name="Leave #", value=f"```{leave_count}```", inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)
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

        embed = self._create_embed("➖ Role Removed", EmbedColors.ERROR, category="Role Remove", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Role", value=self._format_role(role), inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)
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
            except Exception:
                pass

        if after_url:
            embed.set_image(url=after_url)
            embed.add_field(name="New", value="See image below ↓", inline=True)

        await self._send_log(LogCategory.AVATAR_CHANGES, embed, files, user_id=user.id)

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

        embed = self._create_embed("🔊 Voice Join", EmbedColors.SUCCESS, category="Voice Join", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=f"🔊 {channel.name}", inline=True)
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

        embed = self._create_embed("🔇 Voice Leave", EmbedColors.ERROR, category="Voice Leave", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Channel", value=f"🔊 {channel.name}", inline=True)
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

        embed = self._create_embed("🔀 Voice Move", EmbedColors.INFO, category="Voice Move", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="From", value=f"🔊 {before.name}", inline=True)
        embed.add_field(name="To", value=f"🔊 {after.name}", inline=True)
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
            embed.add_field(name="By", value=moderator.mention, inline=True)
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
            embed.add_field(name="By", value=moderator.mention, inline=True)
        self._set_user_thumbnail(embed, member)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)

        await self._send_log(LogCategory.CHANNELS, embed)

    async def log_channel_delete(
        self,
        channel_name: str,
        channel_type: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a channel deletion."""
        if not self.enabled:
            return

        embed = self._create_embed("📁 Channel Deleted", EmbedColors.ERROR, category="Channel Delete")
        embed.add_field(name="Channel", value=f"`{channel_name}`", inline=True)
        embed.add_field(name="Type", value=channel_type.title(), inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)
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
            embed.add_field(name="By", value=moderator.mention, inline=True)

        await self._send_log(LogCategory.ROLES, embed)

    async def log_role_delete(
        self,
        role_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a role deletion."""
        if not self.enabled:
            return

        embed = self._create_embed("🎭 Role Deleted", EmbedColors.ERROR, category="Role Delete")
        role_display = f"`{role_name}`" if role_name else "unknown role"
        embed.add_field(name="Role", value=role_display, inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)
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

        embed = self._create_embed("😀 Emoji Created", EmbedColors.SUCCESS, category="Emoji Create")
        embed.add_field(name="Emoji", value=f"{emoji} `:{emoji.name}:`", inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

        embed.set_thumbnail(url=emoji.url)

        await self._send_log(LogCategory.EMOJI_STICKERS, embed)

    async def log_emoji_delete(
        self,
        emoji_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log an emoji deletion."""
        if not self.enabled:
            return

        embed = self._create_embed("😀 Emoji Deleted", EmbedColors.ERROR, category="Emoji Delete")
        embed.add_field(name="Emoji", value=f"`:{emoji_name}:`", inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

        await self._send_log(LogCategory.EMOJI_STICKERS, embed)

    async def log_sticker_create(
        self,
        sticker: discord.GuildSticker,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a sticker creation."""
        if not self.enabled:
            return

        embed = self._create_embed("🎨 Sticker Created", EmbedColors.SUCCESS, category="Sticker Create")
        embed.add_field(name="Sticker", value=sticker.name, inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

        embed.set_thumbnail(url=sticker.url)

        await self._send_log(LogCategory.EMOJI_STICKERS, embed)

    async def log_sticker_delete(
        self,
        sticker_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a sticker deletion."""
        if not self.enabled:
            return

        embed = self._create_embed("🎨 Sticker Deleted", EmbedColors.ERROR, category="Sticker Delete")
        embed.add_field(name="Sticker", value=sticker_name, inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

        await self._send_log(LogCategory.EMOJI_STICKERS, embed)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)
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
            embed.add_field(name="By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)
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

        embed = self._create_embed("🤖 Bot Removed", EmbedColors.ERROR, category="Bot Remove", user_id=bot_id)
        embed.add_field(name="Bot", value=f"`{bot_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed)

    async def log_integration_remove(
        self,
        name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log an integration being removed."""
        if not self.enabled:
            return

        embed = self._create_embed("🔗 Integration Removed", EmbedColors.ERROR, category="Integration Remove")
        embed.add_field(name="Name", value=name, inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed)

    async def log_webhook_delete(
        self,
        webhook_name: str,
        channel_name: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a webhook being deleted."""
        if not self.enabled:
            return

        embed = self._create_embed("🪝 Webhook Deleted", EmbedColors.ERROR, category="Webhook Delete")
        embed.add_field(name="Name", value=f"`{webhook_name}`", inline=True)
        embed.add_field(name="Channel", value=f"`{channel_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=creator.mention, inline=True)

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

        embed = self._create_embed("🧵 Thread Deleted", EmbedColors.ERROR, category="Thread Delete")
        embed.add_field(name="Thread", value=f"`{thread_name}`", inline=True)
        embed.add_field(name="Parent", value=f"`{parent_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)

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

        embed = self._create_embed("🛡️ Message Blocked", EmbedColors.ERROR, category="AutoMod Block", user_id=user.id)
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
            embed.add_field(name="Created By", value=creator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)
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

        embed = self._create_embed("📅 Event Deleted", EmbedColors.ERROR, category="Event Delete")
        embed.add_field(name="Event", value=f"`{event_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

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

        embed = self._create_embed("➕ Reaction Added", EmbedColors.INFO, category="Reaction Add", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Emoji", value=str(reaction.emoji), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(message.channel), inline=True)
        embed.add_field(name="Message", value=f"[Jump]({message.jump_url})", inline=True)

        # Show message preview
        if message.content:
            preview = message.content[:100] + "..." if len(message.content) > 100 else message.content
            embed.add_field(name="Message Preview", value=f"```{preview}```", inline=False)

        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.REACTIONS, embed, user_id=user.id)

    async def log_reaction_remove(
        self,
        reaction: discord.Reaction,
        user: discord.Member,
        message: discord.Message,
    ) -> None:
        """Log a reaction being removed."""
        if not self.enabled:
            return

        embed = self._create_embed("➖ Reaction Removed", EmbedColors.WARNING, category="Reaction Remove", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Emoji", value=str(reaction.emoji), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(message.channel), inline=True)
        embed.add_field(name="Message", value=f"[Jump]({message.jump_url})", inline=True)
        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.REACTIONS, embed, user_id=user.id)

    async def log_reaction_clear(
        self,
        message: discord.Message,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log all reactions being cleared from a message."""
        if not self.enabled:
            return

        embed = self._create_embed("🗑️ Reactions Cleared", EmbedColors.ERROR, category="Reaction Clear")
        embed.add_field(name="Channel", value=self._format_channel(message.channel), inline=True)
        embed.add_field(name="Message", value=f"[Jump]({message.jump_url})", inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

        await self._send_log(LogCategory.REACTIONS, embed)

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
            embed.add_field(name="Started By", value=moderator.mention, inline=True)

        await self._send_log(LogCategory.STAGE, embed)

    async def log_stage_end(
        self,
        channel_name: str,
        topic: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a stage instance ending."""
        if not self.enabled:
            return

        embed = self._create_embed("🎤 Stage Ended", EmbedColors.ERROR, category="Stage End")
        embed.add_field(name="Topic", value=f"`{topic}`", inline=True)
        embed.add_field(name="Channel", value=f"`{channel_name}`", inline=True)
        if moderator:
            embed.add_field(name="Ended By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)
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
        message: discord.Message,
        pinned: bool,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a message being pinned or unpinned."""
        if not self.enabled:
            return

        if pinned:
            embed = self._create_embed("📌 Message Pinned", EmbedColors.SUCCESS, category="Pin", user_id=message.author.id)
        else:
            embed = self._create_embed("📌 Message Unpinned", EmbedColors.WARNING, category="Unpin", user_id=message.author.id)

        embed.add_field(name="Author", value=self._format_user_field(message.author), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(message.channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

        embed.add_field(name="Message", value=f"[Jump to message]({message.jump_url})", inline=True)

        # Show message preview
        if message.content:
            preview = message.content[:200] + "..." if len(message.content) > 200 else message.content
            embed.add_field(name="Content Preview", value=f"```{preview}```", inline=False)

        self._set_user_thumbnail(embed, message.author)

        await self._send_log(LogCategory.MESSAGES, embed, user_id=message.author.id)

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

        embed = self._create_embed("💔 Boost Removed", EmbedColors.ERROR, category="Unboost", user_id=member.id)
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
            embed.add_field(name="Created By", value=moderator.mention, inline=True)
        elif invite.inviter:
            embed.add_field(name="Created By", value=invite.inviter.mention, inline=True)

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
    ) -> None:
        """Log an invite being deleted."""
        if not self.enabled:
            return

        embed = self._create_embed("🔗 Invite Deleted", EmbedColors.ERROR, category="Invite Delete")
        embed.add_field(name="Code", value=f"`{invite_code}`", inline=True)
        embed.add_field(name="Channel", value=f"`{channel_name}`", inline=True)

        if uses is not None:
            embed.add_field(name="Times Used", value=str(uses), inline=True)

        if moderator:
            embed.add_field(name="Deleted By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)

        if member.voice and member.voice.channel:
            embed.add_field(name="Channel", value=f"🔊 {member.voice.channel.name}", inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)

        if member.voice and member.voice.channel:
            embed.add_field(name="Channel", value=f"🔊 {member.voice.channel.name}", inline=True)

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

        # Check if we have the original join message cached
        message_id = self._join_messages.pop(member.id, None)
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
            embed.add_field(name="Changed By", value=moderator.mention, inline=True)

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
    ) -> None:
        """Log when a mod disconnects a user from voice."""
        if not self.enabled:
            return

        embed = self._create_embed("🔌 Voice Disconnected", EmbedColors.ERROR, category="Voice Disconnect", user_id=target.id)
        embed.add_field(name="User", value=self._format_user_field(target), inline=True)
        embed.add_field(name="From Channel", value=f"🔊 {channel_name}", inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

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

        embed = self._create_embed("🗑️ Message Deleted by Mod", EmbedColors.ERROR, category="Mod Delete", user_id=author.id)
        embed.add_field(name="Author", value=self._format_user_field(author), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        if moderator:
            embed.add_field(name="Deleted By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)

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
            embed = self._create_embed("🔒 Thread Locked", EmbedColors.ERROR, category="Thread Lock")
        else:
            embed = self._create_embed("🔓 Thread Unlocked", EmbedColors.SUCCESS, category="Thread Unlock")

        embed.add_field(name="Thread", value=f"#{thread.name}" if thread.name else "#unknown-thread", inline=True)
        if thread.parent:
            embed.add_field(name="Parent", value=self._format_channel(thread.parent), inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

        await self._send_log(LogCategory.THREADS, embed)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)

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

        embed = self._create_embed("🏷️ Forum Tag Deleted", EmbedColors.ERROR, category="Tag Delete")
        embed.add_field(name="Forum", value=self._format_channel(forum), inline=True)
        embed.add_field(name="Tag", value=f"`{tag_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)

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
            embed.add_field(name="By", value=moderator.mention, inline=True)

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

        embed = self._create_embed("🚨 POTENTIAL RAID DETECTED", EmbedColors.ERROR, category="Raid Alert")
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


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["LoggingService", "LogCategory", "LogView", "UserIdButton", "setup_log_views"]
