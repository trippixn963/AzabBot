"""
AzabBot - Purge Cog
===================

Bulk message deletion command implementation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Callable, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, has_mod_role, EmbedColors, NY_TZ
from src.api.services.event_logger import event_logger
from src.core.constants import MAX_PURGE_AMOUNT, BULK_DELETE_LIMIT
from src.utils.discord_rate_limit import log_http_error

from .constants import MESSAGE_AGE_LIMIT, URL_PATTERN, PurgeFilter, FILTER_CHOICES
from .helpers import log_purge_usage

if TYPE_CHECKING:
    from src.bot import AzabBot


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
        reason: Optional[str] = None) -> None:
        """Execute a purge operation with the given filter."""
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.followup.send(
                "Purge can only be used in text channels or threads.",
                ephemeral=True)
            return

        # Calculate cutoff time for bulk delete
        cutoff_time = datetime.now(NY_TZ) - MESSAGE_AGE_LIMIT

        # Collect messages to delete
        messages_to_delete: List[discord.Message] = []
        old_messages: List[discord.Message] = []
        scanned = 0

        try:
            async for message in channel.history(limit=amount + 50):
                scanned += 1

                if len(messages_to_delete) >= amount:
                    break

                if check and not check(message):
                    continue

                msg_time = message.created_at.replace(tzinfo=NY_TZ) if message.created_at.tzinfo is None else message.created_at
                if msg_time < cutoff_time:
                    old_messages.append(message)
                else:
                    messages_to_delete.append(message)

        except discord.Forbidden:
            logger.tree("PURGE BLOCKED", [
                ("Reason", "Missing permissions"),
                ("Channel", f"{channel.name} ({channel.id})"),
                ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("Mod ID", str(interaction.user.id)),
            ], emoji="🚫")
            await interaction.followup.send(
                "I don't have permission to read message history in this channel.",
                ephemeral=True)
            return
        except discord.HTTPException as e:
            log_http_error(e, "Purge History Fetch", [
                ("Channel", f"{channel.name} ({channel.id})"),
            ])
            await interaction.followup.send(
                "Failed to fetch messages. Please try again.",
                ephemeral=True)
            return

        if not messages_to_delete and not old_messages:
            await interaction.followup.send(
                f"No {description} found to delete.",
                ephemeral=True)
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
                    ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                    ("Mod ID", str(interaction.user.id)),
                ], emoji="🚫")
                await interaction.followup.send(
                    "I don't have permission to delete messages in this channel.",
                    ephemeral=True)
                return
            except discord.HTTPException as e:
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
                    old_deleted += 1
                except (discord.Forbidden, discord.HTTPException):
                    failed_count += 1

        total_deleted = deleted_count + old_deleted

        # Build response embed
        embed = discord.Embed(
            title="🗑️ Messages Purged",
            color=EmbedColors.SUCCESS
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
                inline=False)

        if failed_count > 0:
            embed.add_field(
                name="Failed",
                value=f"`{failed_count}` messages could not be deleted",
                inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

        # Log the purge action
        logger.tree("MESSAGES PURGED", [
            ("Channel", f"#{channel.name} ({channel.id})"),
            ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
            ("Mod ID", str(interaction.user.id)),
            ("Type", description),
            ("Deleted", str(total_deleted)),
            ("Old (14d+)", str(old_deleted)),
            ("Failed", str(failed_count)),
            ("Scanned", str(scanned)),
            ("Reason", reason or "None"),
        ], emoji="🗑️")

        # Log to dashboard events
        if total_deleted > 0 and isinstance(interaction.user, discord.Member):
            event_logger.log_bulk_delete(
                guild=interaction.guild,
                channel=channel,
                count=total_deleted,
                moderator=interaction.user)

        # Log to server logs (embed)
        await log_purge_usage(
            bot=self.bot,
            interaction=interaction,
            channel=channel,
            deleted_count=total_deleted,
            purge_type=description,
            old_deleted=old_deleted,
            failed_count=failed_count,
            reason=reason)

        # Log to mod tracker (pings owner for review)
        if self.bot.mod_tracker and isinstance(interaction.user, discord.Member):
            if self.bot.mod_tracker.is_tracked(interaction.user.id):
                await self.bot.mod_tracker.log_purge(
                    mod=interaction.user,
                    channel=channel,
                    deleted_count=total_deleted,
                    purge_type=description,
                    reason=reason)

    # =========================================================================
    # Purge Command
    # =========================================================================

    @app_commands.command(name="purge", description="Bulk delete messages from the channel")
    @app_commands.describe(
        amount="Number of messages to delete (1-500)",
        filter_type="Type of messages to delete",
        user="User to delete messages from (only for 'From User' filter)",
        text="Text to search for (only for 'Containing Text' filter)",
        reason="Reason for the purge")
    @app_commands.choices(filter_type=FILTER_CHOICES)
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, MAX_PURGE_AMOUNT],
        filter_type: Optional[app_commands.Choice[str]] = None,
        user: Optional[discord.Member] = None,
        text: Optional[str] = None,
        reason: Optional[str] = None) -> None:
        """Delete messages from the channel with optional filters."""
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except discord.HTTPException:
            pass  # Interaction already responded or expired

        # Determine filter value
        if filter_type:
            filter_value = filter_type.value
        elif user:
            filter_value = PurgeFilter.USER
        elif text:
            filter_value = PurgeFilter.CONTAINS
        else:
            filter_value = PurgeFilter.ALL

        # Build the check function based on filter
        check: Optional[Callable[[discord.Message], bool]] = None
        description = "messages"

        if filter_value == PurgeFilter.ALL:
            check = None
            description = "all messages"

        elif filter_value == PurgeFilter.USER:
            if not user:
                logger.tree("PURGE VALIDATION FAILED", [
                    ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                    ("Mod ID", str(interaction.user.id)),
                    ("Filter", "From User"),
                    ("Reason", "User parameter not provided"),
                ], emoji="⚠️")
                await interaction.followup.send(
                    "You must specify a user when using the 'From User' filter.",
                    ephemeral=True)
                return
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
                    ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                    ("Mod ID", str(interaction.user.id)),
                    ("Filter", "Containing Text"),
                    ("Reason", "Text parameter not provided"),
                ], emoji="⚠️")
                await interaction.followup.send(
                    "You must specify text when using the 'Containing Text' filter.",
                    ephemeral=True)
                return
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


__all__ = ["PurgeCog"]
