"""
AzabBot - Clearsnipe Command Mixin
==================================

/clearsnipe command implementation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands

from src.core.logger import logger

if TYPE_CHECKING:
    from .cog import SnipeCog


class ClearsnipeCmdMixin:
    """Mixin for /clearsnipe command."""

    @app_commands.command(name="clearsnipe", description="Clear snipe caches for this channel")
    @app_commands.describe(
        target="Clear snipes from a specific user, or leave empty for all",
    )
    async def clearsnipe(
        self: "SnipeCog",
        interaction: discord.Interaction,
        target: Optional[discord.User] = None,
    ) -> None:
        """Clear both deleted and edited snipe caches."""
        if not interaction.guild or not interaction.channel:
            await interaction.response.send_message(
                "This command can only be used in a server channel.",
                ephemeral=True,
            )
            return

        try:
            channel_id = interaction.channel.id

            # Clear deleted snipes from database
            if target:
                cleared_deleted = self.db.clear_snipes(channel_id, user_id=target.id)
            else:
                cleared_deleted = self.db.clear_snipes(channel_id)

            # Clear edit snipes from memory
            cleared_edits = 0
            edit_cache = getattr(self.bot, "_editsnipe_cache", {})
            if channel_id in edit_cache:
                if target:
                    # Filter out edits from specific user
                    original_len = len(edit_cache[channel_id])
                    edit_cache[channel_id] = type(edit_cache[channel_id])(
                        e for e in edit_cache[channel_id]
                        if e.get("author_id") != target.id
                    )
                    cleared_edits = original_len - len(edit_cache[channel_id])
                else:
                    # Clear all edits for this channel
                    cleared_edits = len(edit_cache[channel_id])
                    edit_cache[channel_id].clear()

            total_cleared = cleared_deleted + cleared_edits

            if target:
                # Tree logging
                logger.tree("SNIPE CACHE CLEARED (User)", [
                    ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                        ("Mod ID", str(interaction.user.id)),
                    ("Channel", f"#{interaction.channel.name} ({channel_id})"),
                    ("Target", f"{target.name} ({target.nick})" if hasattr(target, 'nick') and target.nick else target.name),
                    ("Target ID", str(target.id)),
                    ("Deleted", f"{cleared_deleted} messages"),
                    ("Edits", f"{cleared_edits} messages"),
                ], emoji="🧹")

                await interaction.response.send_message(
                    f"Cleared **{cleared_deleted}** deleted + **{cleared_edits}** edited message(s) from {target.mention}.",
                    ephemeral=True,
                )
            else:
                # Tree logging
                logger.tree("SNIPE CACHE CLEARED (All)", [
                    ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                        ("Mod ID", str(interaction.user.id)),
                    ("Channel", f"#{interaction.channel.name} ({channel_id})"),
                    ("Deleted", f"{cleared_deleted} messages"),
                    ("Edits", f"{cleared_edits} messages"),
                ], emoji="🧹")

                await interaction.response.send_message(
                    f"Cleared **{cleared_deleted}** deleted + **{cleared_edits}** edited message(s) from this channel.",
                    ephemeral=True,
                )

            # Log to server logs
            await self._log_clearsnipe_usage(
                interaction=interaction,
                target=target,
                cleared_deleted=cleared_deleted,
                cleared_edits=cleared_edits,
            )

        except Exception as e:
            logger.error("Clear Snipe Command Failed", [
                ("Error", str(e)),
                ("Type", type(e).__name__),
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("User ID", str(interaction.user.id)),
            ])
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "An error occurred while clearing snipe cache.",
                        ephemeral=True,
                    )
            except Exception:
                pass


__all__ = ["ClearsnipeCmdMixin"]
