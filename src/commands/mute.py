"""
Azab Discord Bot - Mute Command Cog
====================================

Server moderation mute/unmute commands with role-based muting.

DESIGN:
    Uses role-based muting instead of Discord's native timeout.
    Role ID is configured via MUTED_ROLE_ID environment variable.
    Supports timed mutes with auto-unmute via background scheduler.

Features:
    - /mute <user> [duration] [reason]: Assign muted role
    - /unmute <user> [reason]: Remove muted role
    - Duration autocomplete with common options
    - Reason autocomplete with common moderation reasons
    - Permission checks (moderator/admin only)
    - DM notification to muted user
    - Mod log channel posting

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
import re

from src.core.logger import logger
from src.core.config import get_config, is_developer, EmbedColors, NY_TZ
from src.core.database import get_db

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Constants
# =============================================================================

DURATION_CHOICES = [
    ("10 minutes", "10m"),
    ("30 minutes", "30m"),
    ("1 hour", "1h"),
    ("6 hours", "6h"),
    ("12 hours", "12h"),
    ("1 day", "1d"),
    ("3 days", "3d"),
    ("7 days", "7d"),
    ("30 days", "30d"),
    ("Permanent", "permanent"),
]
"""Common duration options for autocomplete."""

REASON_CHOICES = [
    "Spam",
    "Inappropriate content",
    "Harassment",
    "Advertising",
    "NSFW content",
    "Trolling",
    "Disrespect",
    "Rule violation",
    "Bypassing filters",
    "Excessive mentions",
]
"""Common moderation reasons for autocomplete."""


# =============================================================================
# Duration Parser
# =============================================================================

def parse_duration(duration_str: str) -> Optional[int]:
    """
    Parse a duration string into seconds.

    DESIGN:
        Supports multiple formats:
        - "10m", "30m" for minutes
        - "1h", "6h" for hours
        - "1d", "7d" for days
        - "1w" for weeks
        - Combined like "1d12h30m"
        - "permanent" or "perm" for None (no expiry)

    Args:
        duration_str: Duration string to parse.

    Returns:
        Duration in seconds, or None for permanent.
    """
    if not duration_str:
        return None

    duration_str = duration_str.lower().strip()

    # Permanent mute
    if duration_str in ("permanent", "perm", "forever", "indefinite"):
        return None

    # Parse combined format like "1d12h30m"
    pattern = r"(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?"
    match = re.fullmatch(pattern, duration_str)

    if not match or not any(match.groups()):
        # Try single unit format
        single_match = re.match(r"^(\d+)\s*(w|d|h|m|s)?$", duration_str)
        if single_match:
            value = int(single_match.group(1))
            unit = single_match.group(2) or "m"  # Default to minutes

            multipliers = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
            return value * multipliers.get(unit, 60)
        return None

    weeks = int(match.group(1) or 0)
    days = int(match.group(2) or 0)
    hours = int(match.group(3) or 0)
    minutes = int(match.group(4) or 0)
    seconds = int(match.group(5) or 0)

    total_seconds = (
        weeks * 604800 +
        days * 86400 +
        hours * 3600 +
        minutes * 60 +
        seconds
    )

    return total_seconds if total_seconds > 0 else None


def format_duration(seconds: Optional[int]) -> str:
    """
    Format seconds into a human-readable duration string.

    Args:
        seconds: Duration in seconds, or None for permanent.

    Returns:
        Formatted string like "1d 2h 30m" or "Permanent".
    """
    if seconds is None:
        return "Permanent"

    parts = []
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 and not parts:
        parts.append(f"{secs}s")

    return " ".join(parts) if parts else "0s"


# =============================================================================
# Mute Cog
# =============================================================================

class MuteCog(commands.Cog):
    """
    Moderation commands for muting and unmuting users.

    DESIGN:
        Uses role-based muting for more control than Discord timeouts.
        Stores mute records in database for persistence across restarts.
        Integrates with mute scheduler for automatic unmutes.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
        db: Database manager.
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self, bot: "AzabBot") -> None:
        """
        Initialize the mute cog.

        Args:
            bot: Main bot instance.
        """
        self.bot = bot
        self.config = get_config()
        self.db = get_db()

    # =========================================================================
    # Permission Check
    # =========================================================================

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """
        Check if user has permission to use mute commands.

        DESIGN:
            Allows developers, admins, and users with manage_roles permission.

        Args:
            interaction: Discord interaction to check.

        Returns:
            True if user has permission.
        """
        if is_developer(interaction.user.id):
            return True

        if isinstance(interaction.user, discord.Member):
            # Check for admin or manage roles permission
            if interaction.user.guild_permissions.administrator:
                return True
            if interaction.user.guild_permissions.manage_roles:
                return True
            if interaction.user.guild_permissions.moderate_members:
                return True

        return False

    # =========================================================================
    # Autocomplete Handlers
    # =========================================================================

    async def duration_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """
        Autocomplete for duration parameter.

        Args:
            interaction: Discord interaction.
            current: Current input value.

        Returns:
            List of duration choices.
        """
        choices = []

        # Filter based on current input
        current_lower = current.lower()

        for label, value in DURATION_CHOICES:
            if current_lower in label.lower() or current_lower in value.lower():
                choices.append(app_commands.Choice(name=label, value=value))

        # If user typed a custom value, validate and include it
        if current and not choices:
            parsed = parse_duration(current)
            if parsed is not None:
                formatted = format_duration(parsed)
                choices.append(app_commands.Choice(name=f"Custom: {formatted}", value=current))
            elif current.lower() in ("perm", "permanent"):
                choices.append(app_commands.Choice(name="Permanent", value="permanent"))

        return choices[:25]  # Discord limit

    async def reason_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """
        Autocomplete for reason parameter.

        Args:
            interaction: Discord interaction.
            current: Current input value.

        Returns:
            List of reason choices.
        """
        choices = []
        current_lower = current.lower()

        for reason in REASON_CHOICES:
            if current_lower in reason.lower():
                choices.append(app_commands.Choice(name=reason, value=reason))

        # Include custom input if provided
        if current and current not in REASON_CHOICES:
            choices.insert(0, app_commands.Choice(name=current, value=current))

        return choices[:25]

    # =========================================================================
    # Mute Command
    # =========================================================================

    @app_commands.command(name="mute", description="Mute a user by assigning the muted role")
    @app_commands.describe(
        user="The user to mute",
        duration="How long to mute (e.g., 10m, 1h, 1d, permanent)",
        reason="Reason for the mute",
    )
    @app_commands.autocomplete(duration=duration_autocomplete, reason=reason_autocomplete)
    async def mute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """
        Mute a user by assigning the muted role.

        DESIGN:
            Validates permissions and target before muting.
            Stores mute in database for persistence.
            Sends DM to user (silently fails if blocked).
            Posts to mod log channel.

        Args:
            interaction: Discord interaction context.
            user: Member to mute.
            duration: Optional duration string.
            reason: Optional reason for mute.
        """
        await interaction.response.defer(ephemeral=True)

        # -------------------------------------------------------------------------
        # Validation
        # -------------------------------------------------------------------------

        # Can't mute yourself
        if user.id == interaction.user.id:
            await interaction.followup.send(
                "You cannot mute yourself.",
                ephemeral=True,
            )
            return

        # Can't mute the bot
        if user.id == self.bot.user.id:
            await interaction.followup.send(
                "I cannot mute myself.",
                ephemeral=True,
            )
            return

        # Can't mute bots
        if user.bot:
            await interaction.followup.send(
                "I cannot mute bots.",
                ephemeral=True,
            )
            return

        # Check role hierarchy
        if isinstance(interaction.user, discord.Member):
            if user.top_role >= interaction.user.top_role and not is_developer(interaction.user.id):
                await interaction.followup.send(
                    "You cannot mute someone with an equal or higher role.",
                    ephemeral=True,
                )
                return

        # Check if bot can assign the role
        muted_role = interaction.guild.get_role(self.config.muted_role_id)
        if not muted_role:
            await interaction.followup.send(
                f"Muted role not found (ID: {self.config.muted_role_id}). Please check configuration.",
                ephemeral=True,
            )
            return

        if muted_role >= interaction.guild.me.top_role:
            await interaction.followup.send(
                "I cannot assign the muted role because it's higher than my highest role.",
                ephemeral=True,
            )
            return

        # Check if already muted
        if muted_role in user.roles:
            await interaction.followup.send(
                f"**{user.display_name}** is already muted.",
                ephemeral=True,
            )
            return

        # -------------------------------------------------------------------------
        # Parse Duration
        # -------------------------------------------------------------------------

        duration_seconds = parse_duration(duration) if duration else None
        duration_display = format_duration(duration_seconds)

        # -------------------------------------------------------------------------
        # Apply Mute
        # -------------------------------------------------------------------------

        try:
            # Add muted role
            await user.add_roles(muted_role, reason=f"Muted by {interaction.user}: {reason or 'No reason'}")

            # Store in database
            self.db.add_mute(
                user_id=user.id,
                guild_id=interaction.guild.id,
                moderator_id=interaction.user.id,
                reason=reason,
                duration_seconds=duration_seconds,
            )

            logger.tree("USER MUTED", [
                ("User", str(user)),
                ("User ID", str(user.id)),
                ("Moderator", str(interaction.user)),
                ("Duration", duration_display),
                ("Reason", (reason or "None")[:50]),
            ], emoji="🔇")

        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to mute this user.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"Failed to mute user: {e}",
                ephemeral=True,
            )
            return

        # -------------------------------------------------------------------------
        # Build Response Embed
        # -------------------------------------------------------------------------

        embed = discord.Embed(
            title="User Muted",
            color=EmbedColors.ERROR,
            timestamp=datetime.now(NY_TZ),
        )

        embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=False)
        embed.add_field(name="Duration", value=duration_display, inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"Mute #{self.db.get_user_mute_count(user.id, interaction.guild.id)}")

        await interaction.followup.send(embed=embed)

        # -------------------------------------------------------------------------
        # DM User (Silent Fail)
        # -------------------------------------------------------------------------

        try:
            dm_embed = discord.Embed(
                title="You have been muted",
                color=EmbedColors.ERROR,
                timestamp=datetime.now(NY_TZ),
            )
            dm_embed.add_field(name="Server", value=f"{interaction.guild.name}", inline=False)
            dm_embed.add_field(name="Duration", value=duration_display, inline=True)
            dm_embed.add_field(name="Moderator", value=f"{interaction.user.display_name}", inline=True)
            dm_embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
            dm_embed.set_thumbnail(url=user.display_avatar.url)

            await user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass  # User has DMs disabled

        # -------------------------------------------------------------------------
        # Post to Mod Log
        # -------------------------------------------------------------------------

        await self._post_mod_log(
            action="Mute",
            user=user,
            moderator=interaction.user,
            reason=reason,
            duration=duration_display,
            color=EmbedColors.ERROR,
        )

        # -------------------------------------------------------------------------
        # Log to Case Forum
        # -------------------------------------------------------------------------

        if self.bot.case_log_service:
            await self.bot.case_log_service.log_mute(
                user=user,
                moderator=interaction.user,
                duration=duration_display,
                reason=reason,
            )

        # -------------------------------------------------------------------------
        # Log to Mod Tracker
        # -------------------------------------------------------------------------

        if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(interaction.user.id):
            await self.bot.mod_tracker.log_mute(
                mod=interaction.user,
                target=user,
                duration=duration_display,
                reason=reason,
            )

    # =========================================================================
    # Unmute Command
    # =========================================================================

    @app_commands.command(name="unmute", description="Unmute a user by removing the muted role")
    @app_commands.describe(
        user="The user to unmute",
        reason="Reason for the unmute",
    )
    @app_commands.autocomplete(reason=reason_autocomplete)
    async def unmute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        """
        Unmute a user by removing the muted role.

        Args:
            interaction: Discord interaction context.
            user: Member to unmute.
            reason: Optional reason for unmute.
        """
        await interaction.response.defer(ephemeral=True)

        # -------------------------------------------------------------------------
        # Validation
        # -------------------------------------------------------------------------

        muted_role = interaction.guild.get_role(self.config.muted_role_id)
        if not muted_role:
            await interaction.followup.send(
                f"Muted role not found (ID: {self.config.muted_role_id}). Please check configuration.",
                ephemeral=True,
            )
            return

        # Check if user is muted
        if muted_role not in user.roles:
            await interaction.followup.send(
                f"**{user.display_name}** is not muted.",
                ephemeral=True,
            )
            return

        # -------------------------------------------------------------------------
        # Remove Mute
        # -------------------------------------------------------------------------

        try:
            # Remove muted role
            await user.remove_roles(muted_role, reason=f"Unmuted by {interaction.user}: {reason or 'No reason'}")

            # Update database
            self.db.remove_mute(
                user_id=user.id,
                guild_id=interaction.guild.id,
                moderator_id=interaction.user.id,
                reason=reason,
            )

            logger.tree("USER UNMUTED", [
                ("User", str(user)),
                ("User ID", str(user.id)),
                ("Moderator", str(interaction.user)),
                ("Reason", (reason or "None")[:50]),
            ], emoji="🔊")

        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to unmute this user.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"Failed to unmute user: {e}",
                ephemeral=True,
            )
            return

        # -------------------------------------------------------------------------
        # Build Response Embed
        # -------------------------------------------------------------------------

        embed = discord.Embed(
            title="User Unmuted",
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ),
        )

        embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=False)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)

        embed.set_thumbnail(url=user.display_avatar.url)

        await interaction.followup.send(embed=embed)

        # -------------------------------------------------------------------------
        # DM User (Silent Fail)
        # -------------------------------------------------------------------------

        try:
            dm_embed = discord.Embed(
                title="You have been unmuted",
                color=EmbedColors.SUCCESS,
                timestamp=datetime.now(NY_TZ),
            )
            dm_embed.add_field(name="Server", value=f"{interaction.guild.name}", inline=False)
            dm_embed.add_field(name="Moderator", value=f"{interaction.user.display_name}", inline=True)
            dm_embed.add_field(name="Reason", value=reason or "No reason provided", inline=False)
            dm_embed.set_thumbnail(url=user.display_avatar.url)

            await user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

        # -------------------------------------------------------------------------
        # Post to Mod Log
        # -------------------------------------------------------------------------

        await self._post_mod_log(
            action="Unmute",
            user=user,
            moderator=interaction.user,
            reason=reason,
            color=EmbedColors.SUCCESS,
        )

        # -------------------------------------------------------------------------
        # Log to Case Forum
        # -------------------------------------------------------------------------

        if self.bot.case_log_service:
            await self.bot.case_log_service.log_unmute(
                user_id=user.id,
                moderator=interaction.user,
                display_name=user.display_name,
                reason=reason,
            )

        # -------------------------------------------------------------------------
        # Log to Mod Tracker
        # -------------------------------------------------------------------------

        if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(interaction.user.id):
            await self.bot.mod_tracker.log_unmute(
                mod=interaction.user,
                target=user,
                reason=reason,
            )

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def _post_mod_log(
        self,
        action: str,
        user: discord.Member,
        moderator: discord.Member,
        reason: Optional[str] = None,
        duration: Optional[str] = None,
        color: int = EmbedColors.INFO,
    ) -> None:
        """
        Post an action to the mod log channel.

        Args:
            action: Action name (Mute/Unmute).
            user: Target user.
            moderator: Moderator who performed action.
            reason: Optional reason.
            duration: Optional duration string.
            color: Embed color.
        """
        log_channel = self.bot.get_channel(self.config.logs_channel_id)
        if not log_channel:
            return

        embed = discord.Embed(
            title=f"Moderation: {action}",
            color=color,
            timestamp=datetime.now(NY_TZ),
        )

        embed.add_field(name="User", value=f"{user.mention} ({user})", inline=True)
        embed.add_field(name="Moderator", value=f"{moderator.mention}", inline=True)

        if duration:
            embed.add_field(name="Duration", value=duration, inline=True)

        embed.add_field(
            name="Reason",
            value=reason or "No reason provided",
            inline=False,
        )

        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"User ID: {user.id}")

        try:
            await log_channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error("Failed to Post Mod Log", [
                ("Channel", str(self.config.logs_channel_id)),
                ("Error", str(e)[:50]),
            ])


# =============================================================================
# Cog Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """
    Load the mute cog.

    Args:
        bot: Main bot instance.
    """
    await bot.add_cog(MuteCog(bot))


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["MuteCog", "setup", "parse_duration", "format_duration"]
