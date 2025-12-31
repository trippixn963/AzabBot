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
import time
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from src.core.logger import logger
from src.core.config import get_config, is_developer, has_mod_role, EmbedColors, NY_TZ
from src.core.database import get_db
from src.core.moderation_validation import (
    validate_moderation_target,
    get_target_guild,
    is_cross_server,
    send_management_blocked_embed,
)
from src.utils.footer import set_footer
from src.utils.views import CaseButtonView
from src.utils.async_utils import gather_with_logging
from src.utils.dm_helpers import send_moderation_dm, safe_send_dm, build_appeal_dm
from src.utils.duration import parse_duration, format_duration

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
# Mute Cog
# =============================================================================

class MuteCog(commands.Cog):
    """
    Moderation commands for muting and unmuting users.

    DESIGN:
        Uses role-based muting for more control than Discord timeouts.
        Stores mute records in database for persistence across restarts.
        Integrates with mute scheduler for automatic unmutes.
        Supports cross-server moderation from mod server to main server.

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

        logger.tree("Mute Cog Loaded", [
            ("Commands", "/mute, /unmute"),
            ("Context Menus", "Mute Author, Unmute Author"),
            ("Cross-Server", "Enabled"),
        ], emoji="🔇")

    # =========================================================================
    # Permission Check
    # =========================================================================

    async def cog_check(self, interaction: discord.Interaction) -> bool:
        """
        Check if user has permission to use mute commands.

        DESIGN:
            Uses role-based permission check (has_mod_role).
            Allows developers, admins, moderator IDs, and moderation role.

        Args:
            interaction: Discord interaction to check.

        Returns:
            True if user has permission.
        """
        return has_mod_role(interaction.user)

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
        user: discord.User,
        duration: Optional[str] = None,
        reason: Optional[str] = None,
        evidence: Optional[str] = None,
    ) -> None:
        """
        Execute mute logic (shared by /mute command and context menu).

        Supports cross-server moderation: when run from mod server,
        the mute is executed on the main server.

        Args:
            interaction: Discord interaction (must be deferred).
            user: User to mute.
            duration: Optional duration string.
            reason: Optional reason for mute.
            evidence: Optional evidence link/description.
        """
        # -----------------------------------------------------------------
        # Get Target Guild (for cross-server moderation)
        # -----------------------------------------------------------------

        target_guild = get_target_guild(interaction, self.bot)
        cross_server = is_cross_server(interaction)

        # Get member from target guild (required for role-based mute)
        target_member = target_guild.get_member(user.id)
        if not target_member:
            guild_name = target_guild.name if cross_server else "this server"
            await interaction.followup.send(
                f"User is not a member of {guild_name}.",
                ephemeral=True,
            )
            return

        # ---------------------------------------------------------------------
        # Validation (using centralized validation module)
        # ---------------------------------------------------------------------

        result = await validate_moderation_target(
            interaction=interaction,
            target=user,
            bot=self.bot,
            action="mute",
            require_member=True,
            check_bot_hierarchy=False,  # We check muted role instead
        )

        if not result.is_valid:
            if result.should_log_attempt:
                await send_management_blocked_embed(interaction, "mute")
            else:
                await interaction.followup.send(result.error_message, ephemeral=True)
            return

        # Muted role specific checks
        muted_role = target_guild.get_role(self.config.muted_role_id)
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

        if muted_role >= target_guild.me.top_role:
            logger.tree("MUTE BLOCKED", [
                ("Reason", "Bot role too low"),
                ("Muted Role", muted_role.name),
                ("Bot Top Role", target_guild.me.top_role.name),
            ], emoji="🚫")
            await interaction.followup.send(
                "I cannot assign the muted role because it's higher than my highest role.",
                ephemeral=True,
            )
            return

        # ---------------------------------------------------------------------
        # Apply Mute
        # ---------------------------------------------------------------------

        is_extension = muted_role in target_member.roles
        duration_seconds = parse_duration(duration) if duration else None
        duration_display = format_duration(duration_seconds)

        try:
            if not is_extension:
                await target_member.add_roles(muted_role, reason=f"Muted by {interaction.user}: {reason or 'No reason'}")

            self.db.add_mute(
                user_id=user.id,
                guild_id=target_guild.id,
                moderator_id=interaction.user.id,
                reason=reason,
                duration_seconds=duration_seconds,
            )

            action = "EXTENDED" if is_extension else "MUTED"
            log_items = [
                ("User", f"{user} ({user.id})"),
                ("Moderator", str(interaction.user)),
                ("Duration", duration_display),
                ("Reason", (reason or "None")[:50]),
            ]
            if cross_server:
                log_items.insert(1, ("Cross-Server", f"From {interaction.guild.name} → {target_guild.name}"))
            logger.tree(f"USER {action}", log_items, emoji="🔇")

        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to mute this user.", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"Failed to mute user: {e}", ephemeral=True)
            return

        # ---------------------------------------------------------------------
        # Log to Case Forum (creates per-action case)
        # ---------------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            try:
                case_info = await asyncio.wait_for(
                    self.bot.case_log_service.log_mute(
                        user=target_member,
                        moderator=interaction.user,
                        duration=duration_display,
                        reason=reason,
                        is_extension=is_extension,
                        evidence=evidence,
                    ),
                    timeout=10.0,  # 10 second timeout for case logging
                )
            except asyncio.TimeoutError:
                logger.warning("Case Log Timeout", [
                    ("Action", "Mute"),
                    ("User", f"{target_member} ({target_member.id})"),
                ])
            except Exception as e:
                logger.error("Case Log Failed", [
                    ("Action", "Mute"),
                    ("User", f"{target_member} ({target_member.id})"),
                    ("Error", str(e)[:100]),
                ])

        # ---------------------------------------------------------------------
        # Build & Send Embed
        # ---------------------------------------------------------------------

        embed_title = "🔇 Mute Extended" if is_extension else "🔇 User Muted"
        action_desc = "mute has been extended" if is_extension else "has been muted"
        embed = discord.Embed(
            title=embed_title,
            description=f"**{target_member.display_name}**'s {action_desc}." if is_extension else f"**{target_member.display_name}** has been muted.",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="User", value=f"`{user.name}`\n{user.mention}", inline=True)
        embed.add_field(name="Moderator", value=f"`{interaction.user.display_name}`\n{interaction.user.mention}", inline=True)
        embed.add_field(name="Duration", value=f"`{duration_display}`", inline=True)

        if case_info:
            embed.add_field(name="Case", value=f"`#{case_info['case_id']}`", inline=True)

        # Note: Reason/Evidence intentionally not shown in public embed
        # Only visible in DMs, case logs, and mod logs

        embed.set_thumbnail(url=target_member.display_avatar.url)
        set_footer(embed)

        sent_message = None
        try:
            if case_info:
                view = CaseButtonView(target_guild.id, case_info["thread_id"], user.id)
                sent_message = await interaction.followup.send(embed=embed, view=view)
            else:
                sent_message = await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Mute followup failed: {e}")

        # ---------------------------------------------------------------------
        # Concurrent Post-Response Operations
        # ---------------------------------------------------------------------

        await gather_with_logging(
            ("DM User", self._send_mute_dm(
                target=target_member,
                guild=target_guild,
                moderator=interaction.user,
                duration_display=duration_display,
                duration_seconds=duration_seconds,
                reason=reason,
                evidence=evidence,
                case_info=case_info,
                is_extension=is_extension,
            )),
            ("Post Mod Logs", self._post_mod_log(
                action="Mute Extended" if is_extension else "Mute",
                user=target_member,
                moderator=interaction.user,
                reason=reason,
                duration=duration_display,
                color=EmbedColors.ERROR,
            )),
            ("Mod Tracker", self._log_mute_to_tracker(
                moderator=interaction.user,
                target=target_member,
                duration=duration_display,
                reason=reason,
                case_id=case_info["case_id"] if case_info else None,
            )),
            context="Mute Command",
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
        user: discord.User,
        duration: str,
        reason: str,
        evidence: Optional[discord.Attachment] = None,
    ) -> None:
        """Mute a user by assigning the muted role (supports cross-server from mod server)."""
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

        # Defer and execute unmute (validation already done)
        await interaction.response.defer(ephemeral=False)
        await self.execute_unmute(interaction, user, reason=None, skip_validation=True)

    # =========================================================================
    # Shared Unmute Logic
    # =========================================================================

    async def execute_unmute(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: Optional[str] = None,
        skip_validation: bool = False,
    ) -> None:
        """
        Execute unmute logic (shared by /unmute command and context menu).

        Supports cross-server moderation: when run from mod server,
        the unmute is executed on the main server.

        Args:
            interaction: Discord interaction (must be deferred).
            user: User to unmute.
            reason: Optional reason for unmute.
            skip_validation: Skip validation if already done by caller.
        """
        # -----------------------------------------------------------------
        # Get Target Guild (for cross-server moderation)
        # -----------------------------------------------------------------

        target_guild = get_target_guild(interaction, self.bot)
        cross_server = is_cross_server(interaction)

        # Get member from target guild
        target_member = target_guild.get_member(user.id)
        if not skip_validation:
            if not target_member:
                guild_name = target_guild.name if cross_server else "this server"
                await interaction.followup.send(
                    f"User is not a member of {guild_name}.",
                    ephemeral=True,
                )
                return

        muted_role = target_guild.get_role(self.config.muted_role_id)
        if not skip_validation:
            if not muted_role:
                await interaction.followup.send(
                    f"Muted role not found (ID: {self.config.muted_role_id}).",
                    ephemeral=True,
                )
                return

            if muted_role not in target_member.roles:
                await interaction.followup.send(
                    f"**{target_member.display_name}** is not muted.",
                    ephemeral=True,
                )
                return

        # ---------------------------------------------------------------------
        # Get Mute Info (before removing)
        # ---------------------------------------------------------------------

        mute_info = self.db.get_active_mute(user.id, target_guild.id)
        muted_duration = None
        if mute_info and mute_info["muted_at"]:
            muted_seconds = int(time.time() - mute_info["muted_at"])
            muted_duration = format_duration(muted_seconds)

        # ---------------------------------------------------------------------
        # Remove Mute
        # ---------------------------------------------------------------------

        try:
            await target_member.remove_roles(muted_role, reason=f"Unmuted by {interaction.user}: {reason or 'No reason'}")

            self.db.remove_mute(
                user_id=user.id,
                guild_id=target_guild.id,
                moderator_id=interaction.user.id,
                reason=reason,
            )

            log_items = [
                ("User", f"{user} ({user.id})"),
                ("Moderator", str(interaction.user)),
                ("Was Muted For", muted_duration or "Unknown"),
                ("Reason", (reason or "None")[:50]),
            ]
            if cross_server:
                log_items.insert(1, ("Cross-Server", f"From {interaction.guild.name} → {target_guild.name}"))
            logger.tree("USER UNMUTED", log_items, emoji="🔊")

        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to unmute this user.", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"Failed to unmute user: {e}", ephemeral=True)
            return

        # ---------------------------------------------------------------------
        # Log to Case Forum (finds active mute case and resolves it)
        # ---------------------------------------------------------------------

        case_info = None
        if self.bot.case_log_service:
            try:
                case_info = await asyncio.wait_for(
                    self.bot.case_log_service.log_unmute(
                        user_id=user.id,
                        moderator=interaction.user,
                        display_name=target_member.display_name,
                        reason=reason,
                        user_avatar_url=target_member.display_avatar.url,
                    ),
                    timeout=10.0,
                )
            except asyncio.TimeoutError:
                logger.warning("Case Log Timeout", [
                    ("Action", "Unmute"),
                    ("User", f"{target_member} ({target_member.id})"),
                ])
            except Exception as e:
                logger.error("Case Log Failed", [
                    ("Action", "Unmute"),
                    ("User", f"{target_member} ({target_member.id})"),
                    ("Error", str(e)[:100]),
                ])

        # ---------------------------------------------------------------------
        # Build & Send Embed
        # ---------------------------------------------------------------------

        embed = discord.Embed(
            title="🔊 User Unmuted",
            description=f"**{target_member.display_name}** has been unmuted.",
            color=EmbedColors.SUCCESS,
        )
        embed.add_field(name="User", value=f"`{user.name}`\n{user.mention}", inline=True)
        embed.add_field(name="Moderator", value=f"`{interaction.user.display_name}`\n{interaction.user.mention}", inline=True)
        embed.add_field(name="Was Muted For", value=f"`{muted_duration or 'Unknown'}`", inline=True)

        if case_info:
            embed.add_field(name="Case", value=f"`#{case_info['case_id']}`", inline=True)

        # Note: Reason intentionally not shown in public embed
        # Only visible in DMs, case logs, and mod logs

        embed.set_thumbnail(url=target_member.display_avatar.url)
        set_footer(embed)

        sent_message = None
        try:
            if case_info:
                view = CaseButtonView(target_guild.id, case_info["thread_id"], user.id)
                sent_message = await interaction.followup.send(embed=embed, view=view)
            else:
                sent_message = await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"execute_unmute: Followup.send failed: {e}")

        # ---------------------------------------------------------------------
        # Concurrent Post-Response Operations
        # ---------------------------------------------------------------------

        await gather_with_logging(
            ("DM User", self._send_unmute_dm(
                target=target_member,
                guild=target_guild,
                moderator=interaction.user,
                reason=reason,
            )),
            ("Post Mod Logs", self._post_mod_log(
                action="Unmute",
                user=target_member,
                moderator=interaction.user,
                reason=reason,
                color=EmbedColors.SUCCESS,
            )),
            ("Mod Tracker", self._log_unmute_to_tracker(
                moderator=interaction.user,
                target=target_member,
                reason=reason,
                case_id=case_info["case_id"] if case_info else None,
            )),
            context="Unmute Command",
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
        user: discord.User,
        reason: Optional[str] = None,
    ) -> None:
        """Unmute a user by removing the muted role (supports cross-server from mod server)."""
        # Pre-validate before deferring (so errors can be ephemeral)
        target_guild = get_target_guild(interaction, self.bot)
        target_member = target_guild.get_member(user.id)

        if not target_member:
            guild_name = target_guild.name if is_cross_server(interaction) else "this server"
            await interaction.response.send_message(
                f"User is not a member of {guild_name}.",
                ephemeral=True,
            )
            return

        muted_role = target_guild.get_role(self.config.muted_role_id)
        if not muted_role:
            await interaction.response.send_message(
                f"Muted role not found (ID: {self.config.muted_role_id}).",
                ephemeral=True,
            )
            return

        if muted_role not in target_member.roles:
            await interaction.response.send_message(
                f"**{target_member.display_name}** is not muted.",
                ephemeral=True,
            )
            return

        # All validation passed - now defer and execute
        await interaction.response.defer(ephemeral=False)
        await self.execute_unmute(interaction, user, reason, skip_validation=True)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def _send_mute_dm(
        self,
        target: discord.Member,
        guild: discord.Guild,
        moderator: discord.Member,
        duration_display: str,
        duration_seconds: Optional[int],
        reason: Optional[str],
        evidence: Optional[str],
        case_info: Optional[dict],
        is_extension: bool = False,
    ) -> None:
        """Send DM notification to muted user with optional appeal button."""
        dm_title = "Your mute has been extended" if is_extension else "You have been muted"

        sent = await send_moderation_dm(
            user=target,
            title=dm_title,
            color=EmbedColors.ERROR,
            guild=guild,
            moderator=moderator,
            reason=reason,
            evidence=evidence,
            thumbnail_url=target.display_avatar.url,
            fields=[("Duration", f"`{duration_display}`", True)],
            context="Mute DM",
        )

        if not sent:
            return  # User has DMs disabled, skip appeal

        # Send appeal button for eligible mutes (>= 6 hours or permanent)
        MIN_APPEAL_SECONDS = 6 * 60 * 60  # 6 hours
        if case_info and (duration_seconds is None or duration_seconds >= MIN_APPEAL_SECONDS):
            try:
                from src.services.appeal_service import SubmitAppealButton
                appeal_view = discord.ui.View(timeout=None)
                appeal_btn = SubmitAppealButton(case_info["case_id"], target.id)
                appeal_view.add_item(appeal_btn)

                appeal_embed = build_appeal_dm("Mute", case_info["case_id"], guild)
                await safe_send_dm(target, embed=appeal_embed, view=appeal_view, context="Mute Appeal")
            except Exception as e:
                logger.debug(f"Appeal button send failed: {e}")

    async def _send_unmute_dm(
        self,
        target: discord.Member,
        guild: discord.Guild,
        moderator: discord.Member,
        reason: Optional[str],
    ) -> None:
        """Send DM notification to unmuted user."""
        await send_moderation_dm(
            user=target,
            title="You have been unmuted",
            color=EmbedColors.SUCCESS,
            guild=guild,
            moderator=moderator,
            reason=reason,
            thumbnail_url=target.display_avatar.url,
            context="Unmute DM",
        )

    async def _log_mute_to_tracker(
        self,
        moderator: discord.Member,
        target: discord.Member,
        duration: str,
        reason: Optional[str],
        case_id: Optional[int],
    ) -> None:
        """Log mute action to mod tracker if moderator is tracked."""
        if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(moderator.id):
            await self.bot.mod_tracker.log_mute(
                mod=moderator,
                target=target,
                duration=duration,
                reason=reason,
                case_id=case_id,
            )

    async def _log_unmute_to_tracker(
        self,
        moderator: discord.Member,
        target: discord.Member,
        reason: Optional[str],
        case_id: Optional[int],
    ) -> None:
        """Log unmute action to mod tracker if moderator is tracked."""
        if self.bot.mod_tracker and self.bot.mod_tracker.is_tracked(moderator.id):
            await self.bot.mod_tracker.log_unmute(
                mod=moderator,
                target=target,
                reason=reason,
                case_id=case_id,
            )

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
        set_footer(embed)
        embed.set_footer(text=f"User ID: {user.id} • {embed.footer.text}" if embed.footer and embed.footer.text else f"User ID: {user.id}")

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
    if not has_mod_role(interaction.user):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True,
        )
        return

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
    if not has_mod_role(interaction.user):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True,
        )
        return

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
