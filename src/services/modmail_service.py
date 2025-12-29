"""
Azab Discord Bot - Modmail Service
===================================

Service for handling modmail from banned users.

Features:
    - Banned users can DM the bot to contact staff
    - Creates forum threads in mods server
    - Relays messages between DM and thread
    - Staff can close modmail threads

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional, Dict

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.retry import safe_fetch_channel, safe_send

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

MODMAIL_EMOJI = "<:modmail:1455197399621750876>"  # Ticket emoji
CLOSE_EMOJI = "<:close:1452963782208032768>"


# =============================================================================
# Modmail Service
# =============================================================================

class ModmailService:
    """
    Service for managing modmail from banned users.

    DESIGN:
        Banned users can DM the bot to create a modmail thread.
        Each banned user gets one thread in the modmail forum.
        Messages are relayed both ways (DM <-> thread).
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
        """Check if modmail is enabled."""
        return (
            self.config.modmail_forum_id is not None
            and self.config.logging_guild_id is not None
        )

    # =========================================================================
    # Forum Access
    # =========================================================================

    async def _get_forum(self) -> Optional[discord.ForumChannel]:
        """Get the modmail forum channel with caching."""
        if not self.config.modmail_forum_id:
            return None

        now = datetime.now(NY_TZ)

        # Check cache
        if self._forum is not None and self._forum_cache_time is not None:
            if now - self._forum_cache_time < self.THREAD_CACHE_TTL:
                return self._forum

        # Fetch forum
        channel = await safe_fetch_channel(self.bot, self.config.modmail_forum_id)
        if channel is None:
            logger.warning(f"Modmail Forum Not Found: {self.config.modmail_forum_id}")
            return None

        if isinstance(channel, discord.ForumChannel):
            self._forum = channel
            self._forum_cache_time = now
            return self._forum

        logger.warning(f"Channel {self.config.modmail_forum_id} is not a ForumChannel")
        return None

    async def _get_thread(self, thread_id: int) -> Optional[discord.Thread]:
        """Get a modmail thread by ID with caching."""
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
    # Ban Check
    # =========================================================================

    async def is_user_banned(self, user_id: int) -> bool:
        """Check if a user is banned from the main server."""
        if not self.config.logging_guild_id:
            return False

        guild = self.bot.get_guild(self.config.logging_guild_id)
        if not guild:
            return False

        try:
            await guild.fetch_ban(discord.Object(id=user_id))
            return True
        except discord.NotFound:
            return False
        except discord.HTTPException:
            return False

    # =========================================================================
    # Thread Creation
    # =========================================================================

    async def create_thread(self, user: discord.User) -> Optional[discord.Thread]:
        """
        Create a modmail thread for a banned user.

        Args:
            user: The banned user.

        Returns:
            The created thread, or None on failure.
        """
        if not self.enabled:
            return None

        forum = await self._get_forum()
        if not forum:
            logger.error("Modmail Forum Unavailable")
            return None

        # Check for existing thread
        existing = self.db.get_modmail_by_user(user.id, self.config.logging_guild_id)
        if existing:
            thread = await self._get_thread(existing["thread_id"])
            if thread:
                return thread

        # Build thread name
        thread_name = f"Modmail | {user.name}"
        if len(thread_name) > 100:
            thread_name = thread_name[:97] + "..."

        # Build initial embed
        embed = discord.Embed(
            title=f"{MODMAIL_EMOJI} New Modmail",
            description=(
                f"**User:** {user.mention} (`{user.id}`)\n"
                f"**Username:** {user.name}\n"
                f"**Status:** Banned from main server\n\n"
                "Reply in this thread to respond to the user."
            ),
            color=EmbedColors.WARNING,
            timestamp=datetime.now(NY_TZ)
        )
        if user.avatar:
            embed.set_thumbnail(url=user.display_avatar.url)
        set_footer(embed)

        try:
            # Create the thread
            thread_with_message = await forum.create_thread(
                name=thread_name,
                embed=embed,
                view=ModmailCloseView(user.id)
            )
            thread = thread_with_message.thread

            # Save to database
            self.db.create_modmail(
                user_id=user.id,
                guild_id=self.config.logging_guild_id,
                thread_id=thread.id
            )

            logger.tree("Modmail Thread Created", [
                ("User", f"{user.name} ({user.id})"),
                ("Thread", str(thread.id)),
            ], emoji=MODMAIL_EMOJI)

            # Log to server logs
            if self.bot.logging_service and self.bot.logging_service.enabled:
                await self.bot.logging_service.log_modmail_created(user, thread.id)

            return thread

        except discord.HTTPException as e:
            logger.error(f"Failed to create modmail thread: {e}")
            return None

    # =========================================================================
    # Message Relay
    # =========================================================================

    async def relay_dm_to_thread(
        self,
        message: discord.Message,
        thread: discord.Thread
    ) -> bool:
        """
        Relay a DM message to the modmail thread.

        Args:
            message: The DM message.
            thread: The modmail thread.

        Returns:
            True if relayed successfully.
        """
        embed = discord.Embed(
            description=message.content or "*No text content*",
            color=EmbedColors.INFO,
            timestamp=datetime.now(NY_TZ)
        )
        embed.set_author(
            name=f"{message.author.name}",
            icon_url=message.author.display_avatar.url if message.author.avatar else None
        )

        # Handle attachments
        files = []
        for attachment in message.attachments:
            try:
                file = await attachment.to_file()
                files.append(file)
            except discord.HTTPException:
                embed.add_field(
                    name="Attachment",
                    value=f"[{attachment.filename}]({attachment.url})",
                    inline=False
                )

        try:
            await thread.send(embed=embed, files=files if files else None)
            return True
        except discord.HTTPException as e:
            logger.error(f"Failed to relay DM to modmail thread: {e}")
            return False

    async def relay_thread_to_dm(
        self,
        message: discord.Message,
        user: discord.User
    ) -> bool:
        """
        Relay a thread message to the user's DMs.

        Args:
            message: The thread message.
            user: The user to DM.

        Returns:
            True if relayed successfully.
        """
        embed = discord.Embed(
            title="Staff Response",
            description=message.content or "*No text content*",
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ)
        )
        embed.set_author(
            name=f"{message.author.name} (Staff)",
            icon_url=message.author.display_avatar.url if message.author.avatar else None
        )
        set_footer(embed)

        # Handle attachments
        files = []
        for attachment in message.attachments:
            try:
                file = await attachment.to_file()
                files.append(file)
            except discord.HTTPException:
                embed.add_field(
                    name="Attachment",
                    value=f"[{attachment.filename}]({attachment.url})",
                    inline=False
                )

        try:
            await user.send(embed=embed, files=files if files else None)
            return True
        except discord.Forbidden:
            await message.channel.send(
                f"Could not DM user - they may have DMs disabled.",
                delete_after=10
            )
            return False
        except discord.HTTPException as e:
            logger.error(f"Failed to relay thread message to DM: {e}")
            return False

    # =========================================================================
    # DM Handler
    # =========================================================================

    async def handle_dm(self, message: discord.Message) -> bool:
        """
        Handle a DM message from a potentially banned user.

        Args:
            message: The DM message.

        Returns:
            True if handled (user is banned), False otherwise.
        """
        if not self.enabled:
            return False

        user = message.author

        # Check if user is banned
        is_banned = await self.is_user_banned(user.id)
        if not is_banned:
            return False

        # Get or create modmail thread
        existing = self.db.get_modmail_by_user(user.id, self.config.logging_guild_id)
        if existing:
            thread = await self._get_thread(existing["thread_id"])
            if not thread:
                # Thread was deleted, create new one
                thread = await self.create_thread(user)
        else:
            thread = await self.create_thread(user)
            # Send welcome message to user
            welcome_embed = discord.Embed(
                title=f"{MODMAIL_EMOJI} Modmail Created",
                description=(
                    "Your message has been sent to the moderation team.\n\n"
                    "Please be patient while they review your message. "
                    "All your messages in this DM will be forwarded to staff."
                ),
                color=EmbedColors.SUCCESS
            )
            set_footer(welcome_embed)
            try:
                await user.send(embed=welcome_embed)
            except discord.HTTPException:
                pass

        if not thread:
            logger.error(f"Failed to get/create modmail thread for {user.id}")
            return False

        # Relay the message
        await self.relay_dm_to_thread(message, thread)

        logger.tree("Modmail DM Relayed", [
            ("User", f"{user.name} ({user.id})"),
            ("Content", message.content[:50] + "..." if len(message.content) > 50 else message.content),
        ], emoji=MODMAIL_EMOJI)

        return True

    # =========================================================================
    # Thread Message Handler
    # =========================================================================

    async def handle_thread_message(self, message: discord.Message) -> bool:
        """
        Handle a message in a modmail thread (staff reply).

        Args:
            message: The thread message.

        Returns:
            True if handled, False if not a modmail thread.
        """
        if not self.enabled:
            return False

        if not isinstance(message.channel, discord.Thread):
            return False

        # Check if this is a modmail thread
        modmail = self.db.get_modmail_by_thread(message.channel.id)
        if not modmail:
            return False

        # Don't relay bot messages
        if message.author.bot:
            return False

        # Get the user
        try:
            user = await self.bot.fetch_user(modmail["user_id"])
        except discord.HTTPException:
            await message.channel.send(
                "Could not find user to relay message.",
                delete_after=10
            )
            return True

        # Relay to user DM
        success = await self.relay_thread_to_dm(message, user)
        if success:
            # Add reaction to confirm delivery
            try:
                await message.add_reaction("\u2709\ufe0f")  # Envelope emoji
            except discord.HTTPException:
                pass

        logger.tree("Modmail Reply Relayed", [
            ("Staff", f"{message.author.name}"),
            ("To User", f"{user.name} ({user.id})"),
        ], emoji=MODMAIL_EMOJI)

        return True

    # =========================================================================
    # Close Modmail
    # =========================================================================

    async def close_modmail(
        self,
        thread: discord.Thread,
        closed_by: discord.Member,
        notify_user: bool = True
    ) -> bool:
        """
        Close a modmail thread.

        Args:
            thread: The thread to close.
            closed_by: The staff member closing it.
            notify_user: Whether to DM the user.

        Returns:
            True if closed successfully.
        """
        modmail = self.db.get_modmail_by_thread(thread.id)
        if not modmail:
            return False

        # Update database
        self.db.close_modmail(thread.id, closed_by.id)

        # Notify user
        if notify_user:
            try:
                user = await self.bot.fetch_user(modmail["user_id"])
                close_embed = discord.Embed(
                    title=f"{CLOSE_EMOJI} Modmail Closed",
                    description=(
                        "Your modmail conversation has been closed by staff.\n\n"
                        "If you need further assistance, you can send another message "
                        "to start a new conversation."
                    ),
                    color=EmbedColors.WARNING
                )
                set_footer(close_embed)
                await user.send(embed=close_embed)
            except discord.HTTPException:
                pass

        # Archive and lock thread
        try:
            await thread.edit(archived=True, locked=True)
        except discord.HTTPException:
            pass

        logger.tree("Modmail Closed", [
            ("Thread", str(thread.id)),
            ("Closed By", f"{closed_by.name}"),
            ("User", str(modmail["user_id"])),
        ], emoji=CLOSE_EMOJI)

        # Log to server logs
        if self.bot.logging_service and self.bot.logging_service.enabled:
            try:
                user = await self.bot.fetch_user(modmail["user_id"])
                await self.bot.logging_service.log_modmail_closed(user, closed_by, thread.id)
            except discord.HTTPException:
                pass

        return True


# =============================================================================
# Views
# =============================================================================

class ModmailCloseView(discord.ui.View):
    """View with close button for modmail threads."""

    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.add_item(ModmailCloseButton(user_id))


class ModmailCloseButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"modmail_close:(?P<user_id>\d+)"
):
    """Button to close a modmail thread."""

    def __init__(self, user_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Close",
                style=discord.ButtonStyle.danger,
                emoji=CLOSE_EMOJI,
                custom_id=f"modmail_close:{user_id}"
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str]
    ) -> "ModmailCloseButton":
        user_id = int(match.group("user_id"))
        return cls(user_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client

        if not hasattr(bot, "modmail_service"):
            logger.warning("ModmailCloseButton: modmail_service not available")
            await interaction.response.send_message(
                "Modmail service unavailable.",
                ephemeral=True
            )
            return

        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "This can only be used in a thread.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        success = await bot.modmail_service.close_modmail(
            thread=interaction.channel,
            closed_by=interaction.user,
            notify_user=True
        )

        if success:
            # Log to webhook
            if hasattr(bot, "interaction_logger") and bot.interaction_logger:
                try:
                    user = await bot.fetch_user(self.user_id)
                    await bot.interaction_logger.log_modmail_closed(
                        interaction.user, user, interaction.channel.id
                    )
                except Exception:
                    pass

            await interaction.followup.send(
                f"{CLOSE_EMOJI} Modmail closed by {interaction.user.mention}",
                allowed_mentions=discord.AllowedMentions.none()
            )
        else:
            await interaction.followup.send(
                "Failed to close modmail.",
                ephemeral=True
            )


# =============================================================================
# Setup
# =============================================================================

def setup_modmail_views(bot: "AzabBot") -> None:
    """Register modmail dynamic items."""
    bot.add_dynamic_items(ModmailCloseButton)
    logger.tree("Modmail Views Registered", [
        ("Close Button", "ModmailCloseButton"),
    ], emoji=MODMAIL_EMOJI)
