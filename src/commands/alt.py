"""
AzabBot - Alt Detection Command
===============================

Manual alt detection command to check if a user might be an alt.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional, List, Dict

import discord
from discord import app_commands
from discord.ext import commands

from src.core.logger import logger
from src.core.config import get_config, has_mod_role, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Alt Command Cog
# =============================================================================

class AltCog(commands.Cog):
    """Cog for manual alt detection."""

    def __init__(self, bot: "AzabBot") -> None:
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

        logger.tree("Alt Cog Loaded", [
            ("Command", "/alt <user_id>"),
            ("Function", "Check alt detection score"),
        ], emoji="🔍")

    # =========================================================================
    # Permission Check
    # =========================================================================

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has permission to use alt command."""
        return has_mod_role(interaction.user)

    # =========================================================================
    # Alt Command
    # =========================================================================

    @app_commands.command(name="alt", description="Check alt detection score for a user")
    @app_commands.describe(user_id="The user ID to check")
    async def alt(
        self,
        interaction: discord.Interaction,
        user_id: str,
    ) -> None:
        """Check alt detection score for a user against all main server members."""
        await interaction.response.defer(ephemeral=True)

        # Always use main server for alt detection
        if not self.config.logging_guild_id:
            await interaction.followup.send(
                "❌ Main server not configured.",
                ephemeral=True,
            )
            return

        main_guild = self.bot.get_guild(self.config.logging_guild_id)
        if not main_guild:
            await interaction.followup.send(
                "❌ Cannot access main server.",
                ephemeral=True,
            )
            return

        # Parse user ID
        try:
            target_id = int(user_id.strip())
        except ValueError:
            await interaction.followup.send(
                "❌ Invalid user ID. Please provide a valid numeric ID.",
                ephemeral=True,
            )
            return

        # Get the target member from main server
        target = main_guild.get_member(target_id)
        if not target:
            await interaction.followup.send(
                f"❌ User `{target_id}` is not in the main server.",
                ephemeral=True,
            )
            return

        if target.bot:
            await interaction.followup.send(
                "❌ Cannot check bots for alt detection.",
                ephemeral=True,
            )
            return

        logger.tree("Alt Check Started", [
            ("Target", f"{target.name} ({target.id})"),
            ("Moderator", f"{interaction.user.name} ({interaction.user.id})"),
            ("Guild", main_guild.name),
        ], emoji="🔍")

        # Run alt detection
        if not self.bot.alt_detection:
            await interaction.followup.send(
                "❌ Alt detection service is not available.",
                ephemeral=True,
            )
            return

        # Gather target's data
        target_data = await self.bot.alt_detection._gather_user_data(target, main_guild)

        # Scan all members in main server
        potential_matches: List[Dict] = []
        member_count = 0

        for member in main_guild.members:
            if member.id == target.id:
                continue
            if member.bot:
                continue
            if member_count >= 500:  # Limit scan for performance
                break

            member_count += 1

            # Analyze this member against target
            result = await self.bot.alt_detection._analyze_potential_alt(
                banned_data=target_data,
                candidate=member,
                guild=main_guild,
            )

            if result and result['total_score'] >= 30:  # LOW threshold
                potential_matches.append(result)

        # Sort by score
        potential_matches.sort(key=lambda x: x['total_score'], reverse=True)

        # Build response embed
        embed = self._build_result_embed(target, potential_matches, member_count)

        logger.tree("Alt Check Complete", [
            ("Target", f"{target.name} ({target.id})"),
            ("Members Scanned", str(member_count)),
            ("Matches Found", str(len(potential_matches))),
            ("Moderator", f"{interaction.user.name}"),
        ], emoji="✅")

        await interaction.followup.send(embed=embed, ephemeral=True)

    def _build_result_embed(
        self,
        target: discord.Member,
        matches: List[Dict],
        scanned: int,
    ) -> discord.Embed:
        """Build the alt check result embed."""
        if not matches:
            embed = discord.Embed(
                title="🔍 Alt Detection Results",
                description=(
                    f"**Target:** {target.mention} (`{target.name}`)\n\n"
                    f"✅ No potential alts found.\n"
                    f"Scanned {scanned} members."
                ),
                color=EmbedColors.SUCCESS,
                timestamp=datetime.now(NY_TZ),
            )
            set_footer(embed)
            return embed

        # Group by confidence
        high = [m for m in matches if m['confidence'] == 'HIGH']
        medium = [m for m in matches if m['confidence'] == 'MEDIUM']
        low = [m for m in matches if m['confidence'] == 'LOW']

        embed = discord.Embed(
            title="🔍 Alt Detection Results",
            description=(
                f"**Target:** {target.mention} (`{target.name}`)\n\n"
                f"Found **{len(matches)}** potential alt(s).\n"
                f"Scanned {scanned} members."
            ),
            color=EmbedColors.WARNING if high else EmbedColors.INFO,
            timestamp=datetime.now(NY_TZ),
        )

        if high:
            embed.add_field(
                name="🔴 High Confidence",
                value=self._format_matches(high[:5]),
                inline=False,
            )

        if medium:
            embed.add_field(
                name="🟡 Medium Confidence",
                value=self._format_matches(medium[:5]),
                inline=False,
            )

        if low:
            embed.add_field(
                name="🟢 Low Confidence",
                value=self._format_matches(low[:3]),
                inline=False,
            )

        set_footer(embed)
        return embed

    def _format_matches(self, matches: List[Dict]) -> str:
        """Format match list for embed."""
        lines = []
        for m in matches:
            signals = list(m['signals'].keys())
            signal_str = ", ".join(signals[:3])
            if len(signals) > 3:
                signal_str += f" +{len(signals)-3}"
            lines.append(
                f"<@{m['user_id']}> • Score: **{m['total_score']}**\n"
                f"└ {signal_str}"
            )
        return "\n".join(lines) or "None"


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the AltCog."""
    await bot.add_cog(AltCog(bot))
