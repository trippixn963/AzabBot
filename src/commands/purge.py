"""
Azab Discord Bot - Purge Command Cog
=====================================

Bulk message deletion commands for channel moderation.

DESIGN:
    Uses Discord's bulk_delete for efficient message removal.
    Messages older than 14 days cannot be bulk deleted (Discord limitation).
    All purge actions are logged for accountability.

Features:
    - /purge <amount>: Delete recent messages
    - /purge user <user> [amount]: Delete messages from specific user
    - /purge bots [amount]: Delete messages from bots
    - /purge contains <text> [amount]: Delete messages containing text
    - /purge attachments [amount]: Delete messages with attachments
    - /purge embeds [amount]: Delete messages with embeds
    - /purge links [amount]: Delete messages containing links
    - Permission checks (manage_messages required)
    - Mod log integration

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from typing import Optional, List, Callable, TYPE_CHECKING
import re

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

MAX_PURGE_AMOUNT = 500
"""Maximum messages that can be purged in a single command."""

DEFAULT_PURGE_AMOUNT = 100
"""Default number of messages to scan when not specified."""

BULK_DELETE_LIMIT = 100
"""Discord's limit for bulk delete operations."""

MESSAGE_AGE_LIMIT = timedelta(days=14)
"""Messages older than this cannot be bulk deleted."""

URL_PATTERN = re.compile(
    r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*',
    re.IGNORECASE
)
"""Regex pattern for detecting URLs in messages."""


# =============================================================================
# Purge Cog
# =============================================================================

class PurgeCog(commands.Cog):
    """Cog for bulk message deletion commands."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()

        logger.tree("Purge Cog Loaded", [
            ("Commands", "/purge, /purge user, /purge bots, etc."),
            ("Max Amount", str(MAX_PURGE_AMOUNT)),
        ], emoji="🗑️")

    # =========================================================================
    # Command Group
    # =========================================================================

    purge_group = app_commands.Group(
        name="purge",
        description="Bulk delete messages from the channel",
        default_permissions=discord.Permissions(manage_messages=True),
    )

    # =========================================================================
    # Core Purge Logic
    # =========================================================================

    async def _execute_purge(
        self,
        interaction: discord.Interaction,
        amount: int,
        check: Optional[Callable[[discord.Message], bool]] = None,
        description: str = "messages",
    ) -> None:
        """
        Execute a purge operation with the given filter.

        Args:
            interaction: Discord interaction context.
            amount: Maximum number of messages to delete.
            check: Optional filter function for messages.
            description: Description of what's being purged for logging.
        """
        # Validate amount
        if amount < 1:
            await interaction.followup.send(
                "Amount must be at least 1.",
                ephemeral=True,
            )
            return

        if amount > MAX_PURGE_AMOUNT:
            await interaction.followup.send(
                f"Cannot purge more than {MAX_PURGE_AMOUNT} messages at once.",
                ephemeral=True,
            )
            return

        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.followup.send(
                "Purge can only be used in text channels or threads.",
                ephemeral=True,
            )
            return

        # Calculate cutoff time for bulk delete
        cutoff_time = datetime.now(NY_TZ) - MESSAGE_AGE_LIMIT

        # Collect messages to delete
        messages_to_delete: List[discord.Message] = []
        old_messages: List[discord.Message] = []
        scanned = 0

        try:
            async for message in channel.history(limit=amount + 50):  # Buffer for filtered messages
                scanned += 1

                # Skip if we have enough messages
                if len(messages_to_delete) >= amount:
                    break

                # Apply filter if provided
                if check and not check(message):
                    continue

                # Check message age
                msg_time = message.created_at.replace(tzinfo=NY_TZ) if message.created_at.tzinfo is None else message.created_at
                if msg_time < cutoff_time:
                    old_messages.append(message)
                else:
                    messages_to_delete.append(message)

        except discord.Forbidden:
            logger.tree("PURGE BLOCKED", [
                ("Reason", "Missing permissions"),
                ("Channel", f"{channel.name} ({channel.id})"),
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
            ], emoji="🚫")
            await interaction.followup.send(
                "I don't have permission to read message history in this channel.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            logger.error(f"Purge history fetch failed: {e}")
            await interaction.followup.send(
                "Failed to fetch messages. Please try again.",
                ephemeral=True,
            )
            return

        if not messages_to_delete and not old_messages:
            await interaction.followup.send(
                f"No {description} found to delete.",
                ephemeral=True,
            )
            return

        # Bulk delete messages (in chunks of 100)
        deleted_count = 0
        failed_count = 0

        try:
            for i in range(0, len(messages_to_delete), BULK_DELETE_LIMIT):
                chunk = messages_to_delete[i:i + BULK_DELETE_LIMIT]
                if chunk:
                    await channel.delete_messages(chunk)
                    deleted_count += len(chunk)

        except discord.Forbidden:
            logger.tree("PURGE BLOCKED", [
                ("Reason", "Cannot delete messages"),
                ("Channel", f"{channel.name} ({channel.id})"),
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
            ], emoji="🚫")
            await interaction.followup.send(
                "I don't have permission to delete messages in this channel.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            logger.error(f"Bulk delete failed: {e}")
            failed_count = len(messages_to_delete) - deleted_count

        # Handle old messages (delete individually if any)
        old_deleted = 0
        if old_messages and deleted_count < amount:
            for msg in old_messages[:amount - deleted_count]:
                try:
                    await msg.delete()
                    old_deleted += 1
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    failed_count += 1

        total_deleted = deleted_count + old_deleted

        # Build response embed
        embed = discord.Embed(
            title="🗑️ Messages Purged",
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ),
        )
        embed.add_field(name="Deleted", value=f"`{total_deleted}`", inline=True)
        embed.add_field(name="Type", value=f"`{description}`", inline=True)
        embed.add_field(name="Moderator", value=f"{interaction.user.mention}", inline=True)

        if old_deleted > 0:
            embed.add_field(
                name="Note",
                value=f"`{old_deleted}` messages were older than 14 days (deleted individually)",
                inline=False,
            )

        if failed_count > 0:
            embed.add_field(
                name="Failed",
                value=f"`{failed_count}` messages could not be deleted",
                inline=False,
            )

        set_footer(embed)

        # Send response (auto-deletes after 10 seconds)
        await interaction.followup.send(embed=embed, delete_after=10)

        # Log the purge action
        logger.tree("MESSAGES PURGED", [
            ("Channel", f"#{channel.name} ({channel.id})"),
            ("Moderator", f"{interaction.user} ({interaction.user.id})"),
            ("Type", description),
            ("Deleted", str(total_deleted)),
            ("Old (14d+)", str(old_deleted)),
            ("Failed", str(failed_count)),
            ("Scanned", str(scanned)),
        ], emoji="🗑️")

        # Post to mod log
        await self._post_mod_log(
            channel=channel,
            moderator=interaction.user,
            deleted_count=total_deleted,
            description=description,
        )

    async def _post_mod_log(
        self,
        channel: discord.abc.GuildChannel,
        moderator: discord.Member,
        deleted_count: int,
        description: str,
    ) -> None:
        """Post purge action to mod log channel."""
        log_channel = self.bot.get_channel(self.config.logs_channel_id)
        if not log_channel:
            return

        embed = discord.Embed(
            title="Moderation: Purge",
            color=EmbedColors.INFO,
            timestamp=datetime.now(NY_TZ),
        )
        embed.add_field(name="Channel", value=f"{channel.mention}\n`#{channel.name}`", inline=True)
        embed.add_field(name="Moderator", value=f"{moderator.mention}\n`{moderator.display_name}`", inline=True)
        embed.add_field(name="Deleted", value=f"`{deleted_count}` {description}", inline=True)
        set_footer(embed)

        try:
            await log_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to post purge to mod log: {e}")

    # =========================================================================
    # Purge Commands
    # =========================================================================

    @purge_group.command(name="messages", description="Delete a number of recent messages")
    @app_commands.describe(amount="Number of messages to delete (1-500)")
    async def purge_messages(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, MAX_PURGE_AMOUNT],
    ) -> None:
        """Delete recent messages from the channel."""
        await interaction.response.defer(ephemeral=True)
        await self._execute_purge(interaction, amount, description="messages")

    @purge_group.command(name="user", description="Delete messages from a specific user")
    @app_commands.describe(
        user="The user whose messages to delete",
        amount="Number of messages to scan (1-500)",
    )
    async def purge_user(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        amount: app_commands.Range[int, 1, MAX_PURGE_AMOUNT] = DEFAULT_PURGE_AMOUNT,
    ) -> None:
        """Delete messages from a specific user."""
        await interaction.response.defer(ephemeral=True)

        def check(msg: discord.Message) -> bool:
            return msg.author.id == user.id

        await self._execute_purge(
            interaction,
            amount,
            check=check,
            description=f"messages from {user.display_name}",
        )

    @purge_group.command(name="bots", description="Delete messages from bots")
    @app_commands.describe(amount="Number of messages to scan (1-500)")
    async def purge_bots(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, MAX_PURGE_AMOUNT] = DEFAULT_PURGE_AMOUNT,
    ) -> None:
        """Delete messages from bots."""
        await interaction.response.defer(ephemeral=True)

        def check(msg: discord.Message) -> bool:
            return msg.author.bot

        await self._execute_purge(
            interaction,
            amount,
            check=check,
            description="bot messages",
        )

    @purge_group.command(name="humans", description="Delete messages from humans (non-bots)")
    @app_commands.describe(amount="Number of messages to scan (1-500)")
    async def purge_humans(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, MAX_PURGE_AMOUNT] = DEFAULT_PURGE_AMOUNT,
    ) -> None:
        """Delete messages from humans (non-bots)."""
        await interaction.response.defer(ephemeral=True)

        def check(msg: discord.Message) -> bool:
            return not msg.author.bot

        await self._execute_purge(
            interaction,
            amount,
            check=check,
            description="human messages",
        )

    @purge_group.command(name="contains", description="Delete messages containing specific text")
    @app_commands.describe(
        text="Text to search for in messages",
        amount="Number of messages to scan (1-500)",
    )
    async def purge_contains(
        self,
        interaction: discord.Interaction,
        text: str,
        amount: app_commands.Range[int, 1, MAX_PURGE_AMOUNT] = DEFAULT_PURGE_AMOUNT,
    ) -> None:
        """Delete messages containing specific text."""
        await interaction.response.defer(ephemeral=True)

        search_text = text.lower()

        def check(msg: discord.Message) -> bool:
            return search_text in msg.content.lower()

        await self._execute_purge(
            interaction,
            amount,
            check=check,
            description=f"messages containing '{text[:20]}...' " if len(text) > 20 else f"messages containing '{text}'",
        )

    @purge_group.command(name="attachments", description="Delete messages with attachments")
    @app_commands.describe(amount="Number of messages to scan (1-500)")
    async def purge_attachments(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, MAX_PURGE_AMOUNT] = DEFAULT_PURGE_AMOUNT,
    ) -> None:
        """Delete messages with attachments (images, files, etc.)."""
        await interaction.response.defer(ephemeral=True)

        def check(msg: discord.Message) -> bool:
            return len(msg.attachments) > 0

        await self._execute_purge(
            interaction,
            amount,
            check=check,
            description="messages with attachments",
        )

    @purge_group.command(name="embeds", description="Delete messages with embeds")
    @app_commands.describe(amount="Number of messages to scan (1-500)")
    async def purge_embeds(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, MAX_PURGE_AMOUNT] = DEFAULT_PURGE_AMOUNT,
    ) -> None:
        """Delete messages with embeds."""
        await interaction.response.defer(ephemeral=True)

        def check(msg: discord.Message) -> bool:
            return len(msg.embeds) > 0

        await self._execute_purge(
            interaction,
            amount,
            check=check,
            description="messages with embeds",
        )

    @purge_group.command(name="links", description="Delete messages containing links")
    @app_commands.describe(amount="Number of messages to scan (1-500)")
    async def purge_links(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, MAX_PURGE_AMOUNT] = DEFAULT_PURGE_AMOUNT,
    ) -> None:
        """Delete messages containing URLs/links."""
        await interaction.response.defer(ephemeral=True)

        def check(msg: discord.Message) -> bool:
            return bool(URL_PATTERN.search(msg.content))

        await self._execute_purge(
            interaction,
            amount,
            check=check,
            description="messages with links",
        )

    @purge_group.command(name="reactions", description="Delete messages with reactions")
    @app_commands.describe(amount="Number of messages to scan (1-500)")
    async def purge_reactions(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, MAX_PURGE_AMOUNT] = DEFAULT_PURGE_AMOUNT,
    ) -> None:
        """Delete messages that have reactions."""
        await interaction.response.defer(ephemeral=True)

        def check(msg: discord.Message) -> bool:
            return len(msg.reactions) > 0

        await self._execute_purge(
            interaction,
            amount,
            check=check,
            description="messages with reactions",
        )

    @purge_group.command(name="mentions", description="Delete messages with mentions")
    @app_commands.describe(amount="Number of messages to scan (1-500)")
    async def purge_mentions(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, MAX_PURGE_AMOUNT] = DEFAULT_PURGE_AMOUNT,
    ) -> None:
        """Delete messages that mention users or roles."""
        await interaction.response.defer(ephemeral=True)

        def check(msg: discord.Message) -> bool:
            return len(msg.mentions) > 0 or len(msg.role_mentions) > 0

        await self._execute_purge(
            interaction,
            amount,
            check=check,
            description="messages with mentions",
        )


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the Purge cog."""
    await bot.add_cog(PurgeCog(bot))
