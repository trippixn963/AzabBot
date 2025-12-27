"""
Azab Discord Bot - History Command Cog
=======================================

View moderation history for a user.

DESIGN:
    Shows all cases, warnings, and mutes for a user.
    Displays summary counts and recent actions.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.views import CASE_EMOJI, InfoButton, DownloadButton

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

# Action type emojis
ACTION_EMOJIS = {
    "mute": "<:mute:1337255401531154432>",
    "ban": "<:ban:1337255389103284284>",
    "warn": "<:warn:1337255414315393065>",
    "timeout": "<:timeout:1337255426600611840>",
    "kick": "<:kick:1337255404907593759>",
}

FALLBACK_EMOJIS = {
    "mute": "🔇",
    "ban": "🔨",
    "warn": "⚠️",
    "timeout": "⏱️",
    "kick": "👢",
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
            ("Shows", "Cases, warns, mutes, bans"),
        ], emoji="📜")

    def _get_emoji(self, action: str) -> str:
        """Get emoji for action type, falling back to unicode if custom not available."""
        return ACTION_EMOJIS.get(action, FALLBACK_EMOJIS.get(action, "📋"))

    @app_commands.command(name="history", description="View moderation history for a user")
    @app_commands.describe(user="The user to view history for")
    @app_commands.default_permissions(moderate_members=True)
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
            cases = self.db.get_user_cases(user.id, guild_id, limit=10)

            # Get recent warnings
            warnings = self.db.get_user_warnings(user.id, guild_id, limit=5)

            # Tree logging
            logger.tree("HISTORY VIEWED", [
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                ("Target", f"{user} ({user.id})"),
                ("Mutes", str(mute_count)),
                ("Bans", str(ban_count)),
                ("Warns", f"{active_warns} active / {total_warns} total"),
                ("Cases", str(len(cases))),
            ], emoji="📜")

            # Build embed
            embed = discord.Embed(
                title=f"Moderation History",
                color=EmbedColors.GOLD,
                timestamp=datetime.now(NY_TZ),
            )

            # User info
            embed.set_author(
                name=f"{user.display_name} ({user.name})",
                icon_url=user.display_avatar.url,
            )
            embed.set_thumbnail(url=user.display_avatar.url)

            # Summary counts
            summary_lines = []
            if mute_count > 0:
                summary_lines.append(f"{self._get_emoji('mute')} **Mutes:** `{mute_count}`")
            if ban_count > 0:
                summary_lines.append(f"{self._get_emoji('ban')} **Bans:** `{ban_count}`")
            if total_warns > 0:
                summary_lines.append(f"{self._get_emoji('warn')} **Warns:** `{active_warns}` active / `{total_warns}` total")

            if summary_lines:
                embed.add_field(
                    name="Summary",
                    value="\n".join(summary_lines),
                    inline=False,
                )
            else:
                embed.description = "No moderation history found for this user."
                embed.set_footer(text=f"User ID: {user.id}")

                # Still add buttons for no-history case
                view = discord.ui.View(timeout=None)
                view.add_item(InfoButton(user.id, guild_id))
                view.add_item(DownloadButton(user.id))

                await interaction.followup.send(embed=embed, view=view, ephemeral=True)

                # Log to server logs (even for clean users)
                await self._log_history_usage(
                    interaction=interaction,
                    target=user,
                    mute_count=0,
                    ban_count=0,
                    warn_count=0,
                    case_count=0,
                )
                return

            # Recent cases
            if cases:
                case_lines = []
                for case in cases[:5]:
                    action = case.get("action_type", "unknown")
                    case_id = case.get("case_id", "????")
                    created_at = case.get("created_at", 0)
                    status = case.get("status", "open")

                    # Format timestamp
                    if created_at:
                        ts = f"<t:{int(created_at)}:R>"
                    else:
                        ts = "Unknown"

                    # Status indicator
                    status_icon = "🟢" if status == "open" else "⚪"

                    case_lines.append(
                        f"{status_icon} `{case_id}` {self._get_emoji(action)} {action.title()} • {ts}"
                    )

                embed.add_field(
                    name="Recent Cases",
                    value="\n".join(case_lines),
                    inline=False,
                )

            # Recent warnings (if any that aren't in cases)
            if warnings:
                warn_lines = []
                for warn in warnings[:3]:
                    warned_at = warn.get("warned_at", 0)
                    reason = warn.get("reason", "No reason provided")

                    # Truncate reason
                    if len(reason) > 50:
                        reason = reason[:47] + "..."

                    # Format timestamp
                    if warned_at:
                        ts = f"<t:{int(warned_at)}:R>"
                    else:
                        ts = "Unknown"

                    warn_lines.append(f"• {ts}: {reason}")

                if warn_lines:
                    embed.add_field(
                        name="Recent Warnings",
                        value="\n".join(warn_lines),
                        inline=False,
                    )

            # Footer with user ID
            embed.set_footer(text=f"User ID: {user.id}")

            # Build view with buttons
            view = discord.ui.View(timeout=None)

            # Case button (if user has a case)
            case_log = self.db.get_case_log(user.id)
            if case_log:
                thread_id = case_log.get("thread_id")
                if thread_id:
                    case_url = f"https://discord.com/channels/{guild_id}/{thread_id}"
                    view.add_item(discord.ui.Button(
                        label="Case",
                        url=case_url,
                        style=discord.ButtonStyle.link,
                        emoji=CASE_EMOJI,
                    ))

            # Info button
            view.add_item(InfoButton(user.id, guild_id))

            # Avatar button
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
            )

        except discord.HTTPException as e:
            logger.error("History Command Failed (HTTP)", [
                ("Error", str(e)),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Target", f"{user} ({user.id})"),
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
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Target", f"{user} ({user.id})"),
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
