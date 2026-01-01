"""
Azab Discord Bot - Purge Command Cog
=====================================

Bulk message deletion command for channel moderation.

DESIGN:
    Uses Discord's bulk_delete for efficient message removal.
    Messages older than 14 days cannot be bulk deleted (Discord limitation).
    All purge actions are logged for accountability.

Features:
    - /purge <amount> [filter] [user] [text] [reason]
    - Filter dropdown: all, user, bots, humans, contains, attachments, embeds, links, reactions, mentions
    - Permission checks (manage_messages required)
    - Mod log integration

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, has_mod_role, EmbedColors, NY_TZ
from src.core.constants import MAX_PURGE_AMOUNT, BULK_DELETE_LIMIT
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot

MESSAGE_AGE_LIMIT = timedelta(days=14)
"""Messages older than this cannot be bulk deleted."""

URL_PATTERN = re.compile(
    r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*',
    re.IGNORECASE
)
"""Regex pattern for detecting URLs in messages."""


# =============================================================================
# Filter Types
# =============================================================================

class PurgeFilter:
    """Available purge filter types."""
    ALL = "all"
    USER = "user"
    BOTS = "bots"
    HUMANS = "humans"
    CONTAINS = "contains"
    ATTACHMENTS = "attachments"
    EMBEDS = "embeds"
    LINKS = "links"
    REACTIONS = "reactions"
    MENTIONS = "mentions"


FILTER_CHOICES = [
    app_commands.Choice(name="All Messages", value=PurgeFilter.ALL),
    app_commands.Choice(name="From User", value=PurgeFilter.USER),
    app_commands.Choice(name="From Bots", value=PurgeFilter.BOTS),
    app_commands.Choice(name="From Humans", value=PurgeFilter.HUMANS),
    app_commands.Choice(name="Containing Text", value=PurgeFilter.CONTAINS),
    app_commands.Choice(name="With Attachments", value=PurgeFilter.ATTACHMENTS),
    app_commands.Choice(name="With Embeds", value=PurgeFilter.EMBEDS),
    app_commands.Choice(name="With Links", value=PurgeFilter.LINKS),
    app_commands.Choice(name="With Reactions", value=PurgeFilter.REACTIONS),
    app_commands.Choice(name="With Mentions", value=PurgeFilter.MENTIONS),
]


# =============================================================================
# Purge Cog
# =============================================================================

class PurgeCog(commands.Cog):
    """Cog for bulk message deletion command."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()

        logger.tree("Purge Cog Loaded", [
            ("Command", "/purge"),
            ("Filters", "all, user, bots, humans, contains, attachments, embeds, links, reactions, mentions"),
            ("Max Amount", str(MAX_PURGE_AMOUNT)),
        ], emoji="🗑️")

    # =========================================================================
    # Permission Check
    # =========================================================================

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has permission to use purge commands."""
        return has_mod_role(interaction.user)

    # =========================================================================
    # Core Purge Logic
    # =========================================================================

    async def _execute_purge(
        self,
        interaction: discord.Interaction,
        amount: int,
        check: Optional[Callable[[discord.Message], bool]] = None,
        description: str = "messages",
        reason: Optional[str] = None,
    ) -> None:
        """
        Execute a purge operation with the given filter.

        Args:
            interaction: Discord interaction context.
            amount: Maximum number of messages to delete.
            check: Optional filter function for messages.
            description: Description of what's being purged for logging.
            reason: Optional reason for the purge.
        """
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
            logger.tree("PURGE FAILED", [
                ("Reason", "History fetch failed"),
                ("Error", str(e)[:50]),
            ], emoji="❌")
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

        for i in range(0, len(messages_to_delete), BULK_DELETE_LIMIT):
            chunk = messages_to_delete[i:i + BULK_DELETE_LIMIT]
            if not chunk:
                continue

            try:
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
                # Bulk delete failed for this chunk - fall back to individual deletion
                # for accurate failure counting
                logger.warning("Bulk Delete Failed", [
                    ("Chunk", f"{i // BULK_DELETE_LIMIT + 1}"),
                    ("Size", str(len(chunk))),
                    ("Error", str(e)[:50]),
                    ("Action", "Falling back to individual deletion"),
                ])
                for msg in chunk:
                    try:
                        await msg.delete()
                        deleted_count += 1
                    except discord.NotFound:
                        # Message already deleted - count as success
                        deleted_count += 1
                    except (discord.Forbidden, discord.HTTPException):
                        failed_count += 1

        # Handle old messages (delete individually if any)
        old_deleted = 0
        if old_messages and deleted_count < amount:
            for msg in old_messages[:amount - deleted_count]:
                try:
                    await msg.delete()
                    old_deleted += 1
                except discord.NotFound:
                    # Message already deleted - count as success
                    old_deleted += 1
                except (discord.Forbidden, discord.HTTPException):
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

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

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

        # Send response (ephemeral - only visible to moderator)
        await interaction.followup.send(embed=embed, ephemeral=True)

        # Log the purge action
        logger.tree("MESSAGES PURGED", [
            ("Channel", f"#{channel.name} ({channel.id})"),
            ("Moderator", f"{interaction.user} ({interaction.user.id})"),
            ("Type", description),
            ("Deleted", str(total_deleted)),
            ("Old (14d+)", str(old_deleted)),
            ("Failed", str(failed_count)),
            ("Scanned", str(scanned)),
            ("Reason", reason or "None"),
        ], emoji="🗑️")

        # Log to server logs (embed)
        await self._log_purge_usage(
            interaction=interaction,
            channel=channel,
            deleted_count=total_deleted,
            purge_type=description,
            old_deleted=old_deleted,
            failed_count=failed_count,
            reason=reason,
        )

        # Log to mod tracker (pings owner for review)
        if self.bot.mod_tracker and isinstance(interaction.user, discord.Member):
            if self.bot.mod_tracker.is_tracked(interaction.user.id):
                await self.bot.mod_tracker.log_purge(
                    mod=interaction.user,
                    channel=channel,
                    deleted_count=total_deleted,
                    purge_type=description,
                    reason=reason,
                )

    # =========================================================================
    # Purge Command
    # =========================================================================

    @app_commands.command(name="purge", description="Bulk delete messages from the channel")
    @app_commands.describe(
        amount="Number of messages to delete (1-500)",
        filter_type="Type of messages to delete",
        user="User to delete messages from (only for 'From User' filter)",
        text="Text to search for (only for 'Containing Text' filter)",
        reason="Reason for the purge",
    )
    @app_commands.choices(filter_type=FILTER_CHOICES)
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, MAX_PURGE_AMOUNT],
        filter_type: Optional[app_commands.Choice[str]] = None,
        user: Optional[discord.Member] = None,
        text: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Delete messages from the channel with optional filters."""
        await interaction.response.defer(ephemeral=True)

        # Default to all messages if no filter specified
        filter_value = filter_type.value if filter_type else PurgeFilter.ALL

        # Build the check function based on filter
        check: Optional[Callable[[discord.Message], bool]] = None
        description = "messages"

        if filter_value == PurgeFilter.ALL:
            check = None
            description = "all messages"

        elif filter_value == PurgeFilter.USER:
            if not user:
                logger.tree("PURGE VALIDATION FAILED", [
                    ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                    ("Filter", "From User"),
                    ("Reason", "User parameter not provided"),
                ], emoji="⚠️")
                await interaction.followup.send(
                    "You must specify a user when using the 'From User' filter.",
                    ephemeral=True,
                )
                return
            # Capture user.id by value using default argument
            target_user_id = user.id
            check = lambda msg, uid=target_user_id: msg.author.id == uid
            description = f"messages from {user.display_name}"

        elif filter_value == PurgeFilter.BOTS:
            check = lambda msg: msg.author.bot
            description = "bot messages"

        elif filter_value == PurgeFilter.HUMANS:
            check = lambda msg: not msg.author.bot
            description = "human messages"

        elif filter_value == PurgeFilter.CONTAINS:
            if not text:
                logger.tree("PURGE VALIDATION FAILED", [
                    ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                    ("Filter", "Containing Text"),
                    ("Reason", "Text parameter not provided"),
                ], emoji="⚠️")
                await interaction.followup.send(
                    "You must specify text when using the 'Containing Text' filter.",
                    ephemeral=True,
                )
                return
            # Capture search_text by value using default argument
            search_text = text.lower()
            check = lambda msg, st=search_text: st in msg.content.lower()
            description = f"messages containing '{text[:20]}...'" if len(text) > 20 else f"messages containing '{text}'"

        elif filter_value == PurgeFilter.ATTACHMENTS:
            check = lambda msg: len(msg.attachments) > 0
            description = "messages with attachments"

        elif filter_value == PurgeFilter.EMBEDS:
            check = lambda msg: len(msg.embeds) > 0
            description = "messages with embeds"

        elif filter_value == PurgeFilter.LINKS:
            check = lambda msg: bool(URL_PATTERN.search(msg.content))
            description = "messages with links"

        elif filter_value == PurgeFilter.REACTIONS:
            check = lambda msg: len(msg.reactions) > 0
            description = "messages with reactions"

        elif filter_value == PurgeFilter.MENTIONS:
            check = lambda msg: len(msg.mentions) > 0 or len(msg.role_mentions) > 0
            description = "messages with mentions"

        await self._execute_purge(interaction, amount, check=check, description=description, reason=reason)

    # =========================================================================
    # Server Logs Integration
    # =========================================================================

    async def _log_purge_usage(
        self,
        interaction: discord.Interaction,
        channel: discord.abc.GuildChannel,
        deleted_count: int,
        purge_type: str,
        old_deleted: int,
        failed_count: int,
        reason: Optional[str],
    ) -> None:
        """Log purge usage to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="🗑️ Messages Purged",
                color=EmbedColors.WARNING,
                timestamp=datetime.now(NY_TZ),
            )

            embed.add_field(
                name="Moderator",
                value=f"{interaction.user.mention}\n`{interaction.user.id}`",
                inline=True,
            )
            embed.add_field(
                name="Channel",
                value=f"{channel.mention}\n`{channel.id}`",
                inline=True,
            )
            embed.add_field(
                name="Deleted",
                value=f"`{deleted_count}` messages",
                inline=True,
            )
            embed.add_field(
                name="Type",
                value=f"`{purge_type}`",
                inline=True,
            )

            if old_deleted > 0:
                embed.add_field(
                    name="Old (14d+)",
                    value=f"`{old_deleted}` (individual)",
                    inline=True,
                )

            if failed_count > 0:
                embed.add_field(
                    name="Failed",
                    value=f"`{failed_count}` messages",
                    inline=True,
                )

            if reason:
                embed.add_field(
                    name="Reason",
                    value=reason,
                    inline=False,
                )

            set_footer(embed)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.MOD_ACTIONS,
                embed,
            )

        except Exception as e:
            logger.debug(f"Failed to log purge usage: {e}")


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the Purge cog."""
    await bot.add_cog(PurgeCog(bot))
