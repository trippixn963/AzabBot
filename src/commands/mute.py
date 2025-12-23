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

import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
import re

from src.core.logger import logger
from src.core.config import get_config, is_developer, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer
from src.utils.views import CaseButtonView

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# View Classes
# =============================================================================

class MuteModal(discord.ui.Modal, title="Mute User"):
    """Modal for muting a user from context menu."""

    duration_input = discord.ui.TextInput(
        label="Duration",
        placeholder="e.g., 10m, 1h, 1d, permanent",
        required=False,
        max_length=50,
    )

    reason_input = discord.ui.TextInput(
        label="Reason",
        placeholder="Reason for the mute",
        required=False,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )

    def __init__(
        self,
        bot: "AzabBot",
        target_user: discord.Member,
        evidence: Optional[str],
        cog: "MuteCog",
    ):
        super().__init__()
        self.bot = bot
        self.target_user = target_user
        self.evidence = evidence
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        duration = self.duration_input.value or None
        reason = self.reason_input.value or None

        # Defer the response
        await interaction.response.defer(ephemeral=False)

        # Get the target as a Member
        user = interaction.guild.get_member(self.target_user.id)
        if not user:
            await interaction.followup.send(
                "User not found in this server.",
                ephemeral=True,
            )
            return

        # Use shared mute logic from cog
        await self.cog.execute_mute(
            interaction=interaction,
            user=user,
            duration=duration,
            reason=reason,
            evidence=self.evidence,
        )


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
        - "1y", "99y" for years
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

    # Parse combined format like "1y2w3d12h30m"
    pattern = r"(?:(\d+)y)?(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?"
    match = re.fullmatch(pattern, duration_str)

    if not match or not any(match.groups()):
        # Try single unit format (including years)
        single_match = re.match(r"^(\d+)\s*(y|w|d|h|m|s)?$", duration_str)
        if single_match:
            value = int(single_match.group(1))
            unit = single_match.group(2) or "m"  # Default to minutes

            multipliers = {"y": 31536000, "w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
            return value * multipliers.get(unit, 60)
        return None

    years = int(match.group(1) or 0)
    weeks = int(match.group(2) or 0)
    days = int(match.group(3) or 0)
    hours = int(match.group(4) or 0)
    minutes = int(match.group(5) or 0)
    seconds = int(match.group(6) or 0)

    total_seconds = (
        years * 31536000 +
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
        Formatted string like "1y 2d 3h" or "Permanent".
    """
    if seconds is None:
        return "Permanent"

    parts = []
    years, remainder = divmod(seconds, 31536000)
    days, remainder = divmod(remainder, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    if years > 0:
        parts.append(f"{years}y")
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
        current_lower = current.lower().strip()

        # Always add user's custom input first if it's a valid duration
        if current:
            parsed = parse_duration(current)
            if parsed is not None:
                formatted = format_duration(parsed)
                choices.append(app_commands.Choice(name=f"{formatted}", value=current))
            elif current_lower in ("perm", "permanent", "forever"):
                choices.append(app_commands.Choice(name="Permanent", value="permanent"))

        # Add matching preset choices
        for label, value in DURATION_CHOICES:
            # Skip if we already added this exact value as custom
            if current_lower == value.lower():
                continue
            if current_lower in label.lower() or current_lower in value.lower():
                choices.append(app_commands.Choice(name=label, value=value))

        # If no input, show all choices
        if not current:
            choices = [app_commands.Choice(name=label, value=value) for label, value in DURATION_CHOICES]

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
    # Shared Mute Logic
    # =========================================================================

    async def execute_mute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration: Optional[str] = None,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
    ) -> None:
        """
        Execute mute logic (shared by /mute command and context menu).

        Args:
            interaction: Discord interaction (must be deferred).
            user: Member to mute.
            duration: Optional duration string.
            reason: Optional reason for mute.
            evidence: Optional evidence link/description.
        """
        # ---------------------------------------------------------------------
        # Validation
        # ---------------------------------------------------------------------

        if user.id == interaction.user.id:
            logger.tree("MUTE BLOCKED", [
                ("Reason", "Self-mute attempt"),
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
            ], emoji="🚫")
            await interaction.followup.send("You cannot mute yourself.", ephemeral=True)
            return

        if user.id == self.bot.user.id:
            logger.tree("MUTE BLOCKED", [
                ("Reason", "Bot self-mute attempt"),
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
            ], emoji="🚫")
            await interaction.followup.send("I cannot mute myself.", ephemeral=True)
            return

        if user.bot:
            logger.tree("MUTE BLOCKED", [
                ("Reason", "Target is a bot"),
                ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                ("Target", f"{user} ({user.id})"),
            ], emoji="🚫")
            await interaction.followup.send("I cannot mute bots.", ephemeral=True)
            return

        if isinstance(interaction.user, discord.Member):
            if user.top_role >= interaction.user.top_role and not is_developer(interaction.user.id):
                logger.tree("MUTE BLOCKED", [
                    ("Reason", "Role hierarchy"),
                    ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                    ("Mod Role", interaction.user.top_role.name),
                    ("Target", f"{user} ({user.id})"),
                    ("Target Role", user.top_role.name),
                ], emoji="🚫")
                await interaction.followup.send(
                    "You cannot mute someone with an equal or higher role.",
                    ephemeral=True,
                )
                return

        # Check management protection
        if self.config.management_role_id and isinstance(interaction.user, discord.Member):
            management_role = interaction.guild.get_role(self.config.management_role_id)
            if management_role:
                user_has_management = management_role in user.roles
                mod_has_management = management_role in interaction.user.roles
                if user_has_management and mod_has_management and not is_developer(interaction.user.id):
                    logger.tree("MUTE BLOCKED", [
                        ("Reason", "Management protection"),
                        ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                        ("Target", f"{user} ({user.id})"),
                    ], emoji="🚫")
                    # Secret log to mod tracker
                    if self.bot.mod_tracker:
                        await self.bot.mod_tracker.log_management_mute_attempt(
                            mod=interaction.user,
                            target=user,
                        )

                    warning_embed = discord.Embed(
                        title="⚠️ Action Blocked",
                        description="Management members cannot mute each other.",
                        color=EmbedColors.WARNING,
                    )
                    set_footer(warning_embed)
                    await interaction.followup.send(embed=warning_embed, ephemeral=True)
                    return

        muted_role = interaction.guild.get_role(self.config.muted_role_id)
        if not muted_role:
            logger.tree("MUTE BLOCKED", [
                ("Reason", "Muted role not found"),
                ("Role ID", str(self.config.muted_role_id)),
            ], emoji="🚫")
            await interaction.followup.send(
                f"Muted role not found (ID: {self.config.muted_role_id}).",
                ephemeral=True,
            )
            return

        if muted_role >= interaction.guild.me.top_role:
            logger.tree("MUTE BLOCKED", [
                ("Reason", "Bot role too low"),
                ("Muted Role", muted_role.name),
                ("Bot Top Role", interaction.guild.me.top_role.name),
            ], emoji="🚫")
            await interaction.followup.send(
                "I cannot assign the muted role because it's higher than my highest role.",
                ephemeral=True,
            )
            return

        # ---------------------------------------------------------------------
        # Apply Mute
        # ---------------------------------------------------------------------

        is_extension = muted_role in user.roles
        duration_seconds = parse_duration(duration) if duration else None
        duration_display = format_duration(duration_seconds)

        try:
            if not is_extension:
                await user.add_roles(muted_role, reason=f"Muted by {interaction.user}: {reason or 'No reason'}")

            self.db.add_mute(
                user_id=user.id,
                guild_id=interaction.guild.id,
                moderator_id=interaction.user.id,
                reason=reason,
                duration_seconds=duration_seconds,
            )

            action = "EXTENDED" if is_extension else "MUTED"
            logger.tree(f"USER {action}", [
                ("User", f"{user} ({user.id})"),
                ("Moderator", str(interaction.user)),
                ("Duration", duration_display),
                ("Reason", (reason or "None")[:50]),
            ], emoji="🔇")

        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to mute this user.", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"Failed to mute user: {e}", ephemeral=True)
            return

        # ---------------------------------------------------------------------
        # Prepare Case
        # ---------------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            case_info = await self.bot.case_log_service.prepare_case(user)

        # ---------------------------------------------------------------------
        # Build & Send Embed
        # ---------------------------------------------------------------------

        embed_title = "🔇 Mute Extended" if is_extension else "🔇 User Muted"
        embed = discord.Embed(title=embed_title, color=EmbedColors.ERROR)
        embed.add_field(name="User", value=f"`{user.name}` ({user.mention})", inline=False)
        embed.add_field(name="Duration", value=f"`{duration_display}`", inline=True)
        embed.add_field(name="Moderator", value=f"{interaction.user.mention}\n`{interaction.user.display_name}`", inline=True)

        if case_info:
            embed.add_field(name="Case ID", value=f"`{case_info['case_id']}`", inline=True)

        # Note: Evidence is intentionally not shown in public embed
        # It's only visible in DMs, case logs, and mod logs

        embed.set_thumbnail(url=user.display_avatar.url)
        set_footer(embed)

        sent_message = None
        try:
            if case_info:
                view = CaseButtonView(interaction.guild.id, case_info["thread_id"], user.id)
                sent_message = await interaction.followup.send(embed=embed, view=view)
            else:
                sent_message = await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Mute followup failed: {e}")

        # ---------------------------------------------------------------------
        # Concurrent Post-Response Operations
        # ---------------------------------------------------------------------

        async def _log_to_case_forum():
            if self.bot.case_log_service and case_info and sent_message:
                await self.bot.case_log_service.log_mute(
                    user=user,
                    moderator=interaction.user,
                    duration=duration_display,
                    reason=reason,
                    source_message_url=sent_message.jump_url,
                    is_extension=is_extension,
                    evidence=evidence,
                )

        async def _dm_user():
            try:
                dm_title = "Your mute has been extended" if is_extension else "You have been muted"
                dm_embed = discord.Embed(title=dm_title, color=EmbedColors.ERROR)
                dm_embed.add_field(name="Server", value=f"`{interaction.guild.name}`", inline=False)
                dm_embed.add_field(name="Duration", value=f"`{duration_display}`", inline=True)
                dm_embed.add_field(name="Moderator", value=f"`{interaction.user.display_name}`", inline=True)
                dm_embed.add_field(name="Reason", value=f"`{reason or 'No reason provided'}`", inline=False)
                if evidence:
                    dm_embed.add_field(name="Evidence", value=evidence, inline=False)
                dm_embed.set_thumbnail(url=user.display_avatar.url)
                set_footer(dm_embed)
                await user.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

        async def _post_logs():
            await self._post_mod_log(
                action="Mute Extended" if is_extension else "Mute",
                user=user,
                moderator=interaction.user,
                reason=reason,
                duration=duration_display,
                color=EmbedColors.ERROR,
            )

        async def _mod_tracker():
            if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(interaction.user.id):
                await self.bot.mod_tracker.log_mute(
                    mod=interaction.user,
                    target=user,
                    duration=duration_display,
                    reason=reason,
                )

        # Run all post-response operations concurrently
        await asyncio.gather(
            _log_to_case_forum(),
            _dm_user(),
            _post_logs(),
            _mod_tracker(),
            return_exceptions=True,
        )

    # =========================================================================
    # Mute Command
    # =========================================================================

    @app_commands.command(name="mute", description="Mute a user by assigning the muted role")
    @app_commands.describe(
        user="The user to mute",
        duration="How long to mute (e.g., 10m, 1h, 1d, permanent)",
        reason="Reason for the mute (required)",
        evidence="Screenshot or video evidence (image/video only)",
    )
    @app_commands.autocomplete(duration=duration_autocomplete, reason=reason_autocomplete)
    async def mute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration: str,
        reason: str,
        evidence: Optional[discord.Attachment] = None,
    ) -> None:
        """Mute a user by assigning the muted role."""
        # Validate attachment is image/video if provided
        evidence_url = None
        if evidence:
            valid_types = ('image/', 'video/')
            if not evidence.content_type or not evidence.content_type.startswith(valid_types):
                await interaction.response.send_message(
                    "Evidence must be an image or video file.",
                    ephemeral=True,
                )
                return
            evidence_url = evidence.url

        await interaction.response.defer(ephemeral=False)
        await self.execute_mute(interaction, user, duration, reason, evidence_url)

    # =========================================================================
    # Mute Context Menu (Right-click message)
    # =========================================================================

    async def _mute_from_message(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> None:
        """
        Mute the author of a message (context menu handler).

        DESIGN:
            Opens a modal for duration/reason input.
            Evidence is auto-filled from message attachment if image/video.

        Args:
            interaction: Discord interaction context.
            message: The message whose author to mute.
        """
        # Can't mute bots
        if message.author.bot:
            await interaction.response.send_message(
                "I cannot mute bots.",
                ephemeral=True,
            )
            return

        # Get evidence from message attachment if it's an image/video
        evidence = None
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith(('image/', 'video/')):
                evidence = attachment.url
                break

        # Show modal for duration and reason
        modal = MuteModal(
            bot=self.bot,
            target_user=message.author,
            evidence=evidence,
            cog=self,
        )
        await interaction.response.send_modal(modal)

    # =========================================================================
    # Unmute Context Menu (Right-click message)
    # =========================================================================

    async def _unmute_from_message(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> None:
        """
        Unmute the author of a message (context menu handler).

        Args:
            interaction: Discord interaction context.
            message: The message whose author to unmute.
        """
        if message.author.bot:
            await interaction.response.send_message(
                "I cannot unmute bots.",
                ephemeral=True,
            )
            return

        # Get member from guild
        user = interaction.guild.get_member(message.author.id)
        if not user:
            await interaction.response.send_message(
                "User not found in this server.",
                ephemeral=True,
            )
            return

        # Check if user is muted
        muted_role = interaction.guild.get_role(self.config.muted_role_id)
        if not muted_role or muted_role not in user.roles:
            await interaction.response.send_message(
                f"**{user.display_name}** is not muted.",
                ephemeral=True,
            )
            return

        # Defer and execute unmute
        await interaction.response.defer(ephemeral=False)
        await self.execute_unmute(interaction, user, reason=None)

    # =========================================================================
    # Shared Unmute Logic
    # =========================================================================

    async def execute_unmute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        """
        Execute unmute logic (shared by /unmute command and context menu).

        Args:
            interaction: Discord interaction (must be deferred).
            user: Member to unmute.
            reason: Optional reason for unmute.
        """
        muted_role = interaction.guild.get_role(self.config.muted_role_id)
        if not muted_role:
            await interaction.followup.send(
                f"Muted role not found (ID: {self.config.muted_role_id}).",
                ephemeral=True,
            )
            return

        if muted_role not in user.roles:
            await interaction.followup.send(
                f"**{user.display_name}** is not muted.",
                ephemeral=True,
            )
            return

        # ---------------------------------------------------------------------
        # Remove Mute
        # ---------------------------------------------------------------------

        try:
            await user.remove_roles(muted_role, reason=f"Unmuted by {interaction.user}: {reason or 'No reason'}")

            self.db.remove_mute(
                user_id=user.id,
                guild_id=interaction.guild.id,
                moderator_id=interaction.user.id,
                reason=reason,
            )

            logger.tree("USER UNMUTED", [
                ("User", f"{user} ({user.id})"),
                ("Moderator", str(interaction.user)),
                ("Reason", (reason or "None")[:50]),
            ], emoji="🔊")

        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to unmute this user.", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"Failed to unmute user: {e}", ephemeral=True)
            return

        # ---------------------------------------------------------------------
        # Get Case Info
        # ---------------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            case_info = self.bot.case_log_service.get_case_info(user.id)

        # ---------------------------------------------------------------------
        # Build & Send Embed
        # ---------------------------------------------------------------------

        embed = discord.Embed(title="🔊 User Unmuted", color=EmbedColors.SUCCESS)
        embed.add_field(name="User", value=f"`{user.name}` ({user.mention})", inline=False)
        embed.add_field(name="Moderator", value=f"{interaction.user.mention}\n`{interaction.user.display_name}`", inline=True)

        if case_info:
            embed.add_field(name="Case ID", value=f"`{case_info['case_id']}`", inline=True)

        embed.set_thumbnail(url=user.display_avatar.url)
        set_footer(embed)

        sent_message = None
        try:
            if case_info:
                view = CaseButtonView(interaction.guild.id, case_info["thread_id"], user.id)
                sent_message = await interaction.followup.send(embed=embed, view=view)
            else:
                sent_message = await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"execute_unmute: Followup.send failed: {e}")

        # ---------------------------------------------------------------------
        # Concurrent Post-Response Operations
        # ---------------------------------------------------------------------

        async def _log_to_case_forum():
            if self.bot.case_log_service and case_info and sent_message:
                await self.bot.case_log_service.log_unmute(
                    user_id=user.id,
                    moderator=interaction.user,
                    display_name=user.display_name,
                    reason=reason,
                    source_message_url=sent_message.jump_url,
                    user_avatar_url=user.display_avatar.url,
                )

        async def _dm_user():
            try:
                dm_embed = discord.Embed(title="You have been unmuted", color=EmbedColors.SUCCESS)
                dm_embed.add_field(name="Server", value=f"`{interaction.guild.name}`", inline=False)
                dm_embed.add_field(name="Moderator", value=f"`{interaction.user.display_name}`", inline=True)
                dm_embed.add_field(name="Reason", value=f"`{reason or 'No reason provided'}`", inline=False)
                dm_embed.set_thumbnail(url=user.display_avatar.url)
                set_footer(dm_embed)
                await user.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

        async def _post_logs():
            await self._post_mod_log(
                action="Unmute",
                user=user,
                moderator=interaction.user,
                reason=reason,
                color=EmbedColors.SUCCESS,
            )

        async def _mod_tracker():
            if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(interaction.user.id):
                await self.bot.mod_tracker.log_unmute(
                    mod=interaction.user,
                    target=user,
                    reason=reason,
                )

        # Run all post-response operations concurrently
        await asyncio.gather(
            _log_to_case_forum(),
            _dm_user(),
            _post_logs(),
            _mod_tracker(),
            return_exceptions=True,
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
        """Unmute a user by removing the muted role."""
        await interaction.response.defer(ephemeral=False)
        await self.execute_unmute(interaction, user, reason)

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

        embed.add_field(name="User", value=f"{user.mention}\n`{user.name}`", inline=True)
        embed.add_field(name="Moderator", value=f"{moderator.mention}\n`{moderator.display_name}`", inline=True)

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
# Context Menu Command
# =============================================================================

@app_commands.context_menu(name="Mute Author")
async def mute_author_context(interaction: discord.Interaction, message: discord.Message) -> None:
    """
    Context menu command to mute the author of a message.

    DESIGN:
        Right-click a message -> Apps -> Mute Author
        Opens modal with duration/reason, auto-fills evidence with message link.
    """
    cog = interaction.client.get_cog("MuteCog")
    if cog:
        await cog._mute_from_message(interaction, message)
    else:
        await interaction.response.send_message(
            "Mute command not available.",
            ephemeral=True,
        )


@app_commands.context_menu(name="Unmute Author")
async def unmute_author_context(interaction: discord.Interaction, message: discord.Message) -> None:
    """
    Context menu command to unmute the author of a message.

    DESIGN:
        Right-click a message -> Apps -> Unmute Author
        Immediately unmutes if user is muted.
    """
    cog = interaction.client.get_cog("MuteCog")
    if cog:
        await cog._unmute_from_message(interaction, message)
    else:
        await interaction.response.send_message(
            "Unmute command not available.",
            ephemeral=True,
        )


# =============================================================================
# Cog Setup
# =============================================================================

async def setup(bot: "AzabBot") -> None:
    """Load the mute cog and context menus."""
    await bot.add_cog(MuteCog(bot))
    bot.tree.add_command(mute_author_context)
    bot.tree.add_command(unmute_author_context)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["MuteCog", "setup", "parse_duration", "format_duration"]
