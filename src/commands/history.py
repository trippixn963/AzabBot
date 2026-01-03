"""
Azab Discord Bot - History Command Cog
=======================================

View moderation history for a user.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, has_mod_role, EmbedColors, NY_TZ
from src.core.database import get_db
from src.core.constants import (
    EMOJI_MUTE,
    EMOJI_BAN,
    EMOJI_WARN,
    EMOJI_TIMEOUT,
    EMOJI_KICK,
)
from src.utils.footer import set_footer
from src.utils.views import CASE_EMOJI, InfoButton, DownloadButton, build_history_embed, build_history_view

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Action type emojis (from constants.py)
ACTION_EMOJIS = {
    "mute": EMOJI_MUTE,
    "ban": EMOJI_BAN,
    "warn": EMOJI_WARN,
    "timeout": EMOJI_TIMEOUT,
    "kick": EMOJI_KICK,
}

FALLBACK_EMOJIS = {
    "mute": "🔇",
    "ban": "🔨",
    "warn": "⚠️",
    "timeout": "⏱️",
    "kick": "👢",
}

# Forbid restriction emojis
FORBID_EMOJIS = {
    "reactions": "🚫",
    "attachments": "📎",
    "voice": "🔇",
    "streaming": "📺",
    "embeds": "🔗",
    "threads": "🧵",
    "external_emojis": "😀",
    "stickers": "🎨",
}


# =============================================================================
# History Cog
# =============================================================================

class HistoryCog(commands.Cog):
    """Cog for viewing user moderation history."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        logger.tree("History Cog Loaded", [
            ("Command", "/history @user"),
            ("Shows", "Cases, warns, mutes, bans, forbids"),
        ], emoji="📜")

    # =========================================================================
    # Permission Check
    # =========================================================================

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has permission to use history command."""
        return has_mod_role(interaction.user)

    def _get_emoji(self, action: str) -> str:
        """Get emoji for action type, falling back to unicode if custom not available."""
        return ACTION_EMOJIS.get(action, FALLBACK_EMOJIS.get(action, "📋"))

    @app_commands.command(name="history", description="View moderation history for a user")
    @app_commands.describe(user="The user to view history for")
    async def history(
        self,
        interaction: discord.Interaction,
        user: discord.User,
    ) -> None:
        """Show moderation history for a user."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        try:
            await interaction.response.defer(ephemeral=True)

            guild_id = interaction.guild.id

            # Get case counts
            case_counts = self.db.get_user_case_counts(user.id, guild_id)
            mute_count = case_counts.get("mute_count", 0)
            ban_count = case_counts.get("ban_count", 0)
            case_warn_count = case_counts.get("warn_count", 0)

            # Get warning counts (from warnings table)
            active_warns, total_warns = self.db.get_warn_counts(user.id, guild_id)

            # Get recent cases
            cases = self.db.get_user_cases(user.id, guild_id, limit=10) or []

            # Get recent warnings
            warnings = self.db.get_user_warnings(user.id, guild_id, limit=5)

            # Get active forbids and forbid history
            active_forbids = self.db.get_user_forbids(user.id, guild_id)
            forbid_history = self.db.get_forbid_history(user.id, guild_id, limit=10)

            # Get mod notes
            mod_notes = self.db.get_mod_notes(user.id, guild_id, limit=5)
            note_count = self.db.get_note_count(user.id, guild_id)

            # Tree logging
            logger.tree("HISTORY VIEWED", [
                ("Moderator", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("Mod ID", str(interaction.user.id)),
                ("Target", user.name),
                ("Target ID", str(user.id)),
                ("Mutes", str(mute_count)),
                ("Bans", str(ban_count)),
                ("Warns", f"{active_warns} active / {total_warns} total"),
                ("Forbids", f"{len(active_forbids)} active / {len(forbid_history)} total"),
                ("Notes", str(note_count)),
                ("Cases", str(len(cases))),
            ], emoji="📜")

            # Build embed using shared format
            embed = await build_history_embed(
                client=self.bot,
                user_id=user.id,
                guild_id=guild_id,
                cases=cases,
            )

            # Build view with case link buttons
            view = build_history_view(cases, guild_id)
            if view is None:
                view = discord.ui.View(timeout=None)

            # Add Info and Avatar buttons
            view.add_item(InfoButton(user.id, guild_id))
            view.add_item(DownloadButton(user.id))

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

            # Log to server logs
            await self._log_history_usage(
                interaction=interaction,
                target=user,
                mute_count=mute_count,
                ban_count=ban_count,
                warn_count=total_warns,
                case_count=len(cases),
                forbid_count=len(forbid_history),
                note_count=note_count,
            )

        except discord.HTTPException as e:
            logger.error("History Command Failed (HTTP)", [
                ("Error", str(e)),
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("User ID", str(interaction.user.id)),
                ("Target", user.name),
                ("Target ID", str(user.id)),
            ])
            try:
                await interaction.followup.send(
                    "Failed to fetch history. Please try again.",
                    ephemeral=True,
                )
            except Exception:
                pass

        except Exception as e:
            logger.error("History Command Failed", [
                ("Error", str(e)),
                ("Type", type(e).__name__),
                ("User", f"{interaction.user.name} ({interaction.user.nick})" if hasattr(interaction.user, 'nick') and interaction.user.nick else interaction.user.name),
                ("User ID", str(interaction.user.id)),
                ("Target", user.name),
                ("Target ID", str(user.id)),
            ])
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "An error occurred while fetching history.",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        "An error occurred while fetching history.",
                        ephemeral=True,
                    )
            except Exception:
                pass

    # =========================================================================
    # Server Logs Integration
    # =========================================================================

    async def _log_history_usage(
        self,
        interaction: discord.Interaction,
        target: discord.User,
        mute_count: int,
        ban_count: int,
        warn_count: int,
        case_count: int,
        forbid_count: int = 0,
        note_count: int = 0,
    ) -> None:
        """Log history command usage to server logs."""
        if not self.bot.logging_service or not self.bot.logging_service.enabled:
            return

        try:
            embed = discord.Embed(
                title="📜 History Viewed",
                color=EmbedColors.GOLD,
                timestamp=datetime.now(NY_TZ),
            )

            embed.add_field(
                name="Moderator",
                value=f"{interaction.user.mention}\n`{interaction.user.id}`",
                inline=True,
            )
            embed.add_field(
                name="Target",
                value=f"{target.mention}\n`{target.id}`",
                inline=True,
            )
            embed.add_field(
                name="Channel",
                value=f"{interaction.channel.mention}" if interaction.channel else "Unknown",
                inline=True,
            )

            # Summary
            summary = []
            if mute_count > 0:
                summary.append(f"Mutes: `{mute_count}`")
            if ban_count > 0:
                summary.append(f"Bans: `{ban_count}`")
            if warn_count > 0:
                summary.append(f"Warns: `{warn_count}`")
            if forbid_count > 0:
                summary.append(f"Forbids: `{forbid_count}`")
            if note_count > 0:
                summary.append(f"Notes: `{note_count}`")
            if case_count > 0:
                summary.append(f"Cases: `{case_count}`")

            if summary:
                embed.add_field(
                    name="Record",
                    value="\n".join(summary),
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Record",
                    value="Clean - no history",
                    inline=False,
                )

            set_footer(embed)

            await self.bot.logging_service._send_log(
                self.bot.logging_service.LogCategory.MOD_ACTIONS,
                embed,
            )

        except Exception as e:
            logger.debug(f"Failed to log history usage: {e}")


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the History cog."""
    await bot.add_cog(HistoryCog(bot))
