"""
AzabBot - Mute Action Button Views
==================================

Buttons for extending and removing mutes.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
from typing import TYPE_CHECKING

import discord

from src.core.config import get_config, EmbedColors
from src.core.database import get_db
from src.core.logger import logger
from src.core.constants import CASE_LOG_TIMEOUT
from src.utils.footer import set_footer
from src.utils.duration import parse_duration

from .constants import EXTEND_EMOJI, UNMUTE_EMOJI

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Extend Mute Button + Modal
# =============================================================================

class ExtendModal(discord.ui.Modal, title="Extend Mute"):
    """Modal for extending a mute duration."""

    duration = discord.ui.TextInput(
        label="Additional Duration",
        placeholder="e.g., 1h, 30m, 2h30m, 1d",
        required=True,
        max_length=20,
    )

    reason = discord.ui.TextInput(
        label="Reason (optional)",
        placeholder="Why are you extending this mute?",
        required=False,
        max_length=200,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, user_id: int, guild_id: int) -> None:
        """Initialize the extend modal with target user context."""
        super().__init__()
        self.user_id = user_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Process mute extension when modal is submitted."""
        logger.tree("Extend Modal Submitted", [
            ("Submitted By", f"{interaction.user} ({interaction.user.id})"),
            ("Target User ID", str(self.user_id)),
            ("Duration Input", self.duration.value),
            ("Reason", self.reason.value[:50] if self.reason.value else "None"),
        ], emoji="⏱️")

        db = get_db()

        # Parse duration
        duration_str = self.duration.value.lower().strip()
        total_seconds = parse_duration(duration_str)

        if total_seconds is None or total_seconds <= 0:
            await interaction.response.send_message(
                "Invalid duration format. Use formats like: `30m`, `1h`, `2h30m`, `1d`",
                ephemeral=True,
            )
            return

        # Try to extend the mute
        new_expires = db.extend_mute(
            user_id=self.user_id,
            guild_id=self.guild_id,
            additional_seconds=total_seconds,
            moderator_id=interaction.user.id,
            reason=self.reason.value if self.reason.value else None,
        )

        if new_expires is None:
            await interaction.response.send_message(
                "Could not extend mute. User may not have an active timed mute.",
                ephemeral=True,
            )
            return

        # Success message (public so other mods can see)
        await interaction.response.send_message(
            f"⏰ **Mute Extended** by {interaction.user.mention}\n"
            f"Extended by **{duration_str}**. New expiration: <t:{int(new_expires)}:R>",
        )

        # Log the extension to case thread if possible
        try:
            case_log = db.get_case_log(self.user_id)
            if case_log and interaction.guild:
                thread = interaction.guild.get_thread(case_log["thread_id"])
                if thread:
                    reason_text = self.reason.value if self.reason.value else "No reason provided"
                    embed = discord.Embed(
                        title="⏱️ Mute Extended",
                        color=EmbedColors.WARNING,
                    )
                    embed.add_field(name="Extended By", value=f"{interaction.user.mention}\n`{interaction.user.name}`", inline=True)
                    embed.add_field(name="Additional Time", value=f"`{duration_str}`", inline=True)
                    embed.add_field(name="New Expiration", value=f"<t:{int(new_expires)}:R>", inline=True)
                    embed.add_field(name="Reason", value=reason_text, inline=False)
                    set_footer(embed)
                    await thread.send(embed=embed)
        except Exception:
            pass  # Silently fail if can't log


class ExtendButton(discord.ui.DynamicItem[discord.ui.Button], template=r"mod_extend:(?P<user_id>\d+):(?P<guild_id>\d+)"):
    """
    Persistent extend button that opens a modal to extend mute duration.
    """

    def __init__(self, user_id: int, guild_id: int) -> None:
        """Initialize the extend button with target user context."""
        super().__init__(
            discord.ui.Button(
                label="Extend",
                style=discord.ButtonStyle.secondary,
                emoji=EXTEND_EMOJI,
                custom_id=f"mod_extend:{user_id}:{guild_id}",
            )
        )
        self.user_id = user_id
        self.guild_id = guild_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "ExtendButton":
        """Reconstruct button from custom_id regex match."""
        user_id = int(match.group("user_id"))
        guild_id = int(match.group("guild_id"))
        return cls(user_id, guild_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle button click - opens extend modal."""
        logger.tree("Extend Button Clicked", [
            ("Clicked By", f"{interaction.user} ({interaction.user.id})"),
            ("Target User ID", str(self.user_id)),
            ("Guild ID", str(self.guild_id)),
        ], emoji="⏱️")

        # Check if user is currently muted
        db = get_db()
        active_mute = db.get_active_mute(self.user_id, self.guild_id)

        if not active_mute:
            # Check if there's a resolved mute case for context
            resolved_case = db.get_most_recent_resolved_case(self.user_id, self.guild_id, "mute")
            resolved_at = resolved_case.get("resolved_at") if resolved_case else None
            if resolved_at:
                resolved_timestamp = int(resolved_at)
                resolved_by = resolved_case.get("resolved_by")
                if resolved_by and resolved_by != 0:
                    await interaction.response.send_message(
                        f"✅ **Case Resolved**\n\n"
                        f"This user was unmuted <t:{resolved_timestamp}:R> by <@{resolved_by}>.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        f"✅ **Case Resolved**\n\n"
                        f"This user's mute expired <t:{resolved_timestamp}:R>.",
                        ephemeral=True,
                    )
            else:
                await interaction.response.send_message(
                    "This user is not currently muted.",
                    ephemeral=True,
                )
            return

        if active_mute["expires_at"] is None:
            await interaction.response.send_message(
                "Cannot extend a permanent mute.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(ExtendModal(self.user_id, self.guild_id))


# =============================================================================
# Unmute Button + Modal
# =============================================================================

class UnmuteModal(discord.ui.Modal, title="Unmute User"):
    """Modal for unmuting with a reason."""

    reason = discord.ui.TextInput(
        label="Reason (optional)",
        placeholder="Why are you unmuting this user?",
        required=False,
        max_length=200,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, user_id: int, guild_id: int) -> None:
        """Initialize the unmute modal with target user context."""
        super().__init__()
        self.user_id = user_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Process unmute when modal is submitted."""
        logger.tree("Unmute Modal Submitted", [
            ("Submitted By", f"{interaction.user} ({interaction.user.id})"),
            ("Target User ID", str(self.user_id)),
            ("Target Guild ID", str(self.guild_id)),
            ("Reason", self.reason.value[:50] if self.reason.value else "None"),
        ], emoji="🔊")

        db = get_db()
        config = get_config()

        # Check if still muted
        if not db.is_user_muted(self.user_id, self.guild_id):
            await interaction.response.send_message(
                "This user is not currently muted.",
                ephemeral=True,
            )
            return

        # Get the TARGET guild (main server) - not interaction.guild (mods server)
        # The guild_id stored in the button is the main server where the user is muted
        guild = interaction.client.get_guild(self.guild_id)
        if not guild:
            await interaction.response.send_message(
                "Could not find the target server.",
                ephemeral=True,
            )
            return

        member = guild.get_member(self.user_id)
        if not member:
            await interaction.response.send_message(
                "User is no longer in the server.",
                ephemeral=True,
            )
            return

        mute_role = guild.get_role(config.muted_role_id)
        if not mute_role:
            await interaction.response.send_message(
                "Muted role not found.",
                ephemeral=True,
            )
            return

        try:
            # Remove mute role
            await member.remove_roles(mute_role, reason=f"Unmuted by {interaction.user.name}")

            # Update database
            db.remove_mute(
                user_id=self.user_id,
                guild_id=self.guild_id,
                moderator_id=interaction.user.id,
                reason=self.reason.value if self.reason.value else None,
            )

            await interaction.response.send_message(
                f"✅ **Unmuted** {member.mention} by {interaction.user.mention}",
            )

            # Log to case thread using case_log_service (handles per-action cases)
            bot = interaction.client
            if hasattr(bot, 'case_log_service') and bot.case_log_service:
                try:
                    await asyncio.wait_for(
                        bot.case_log_service.log_unmute(
                            user_id=self.user_id,
                            moderator=interaction.user,
                            display_name=member.display_name,
                            reason=self.reason.value if self.reason.value else None,
                            user_avatar_url=member.display_avatar.url,
                        ),
                        timeout=CASE_LOG_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Case Log Timeout", [
                        ("Action", "Unmute (Button)"),
                        ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                        ("ID", str(member.id)),
                    ])
                except Exception as e:
                    logger.error("Case Log Failed", [
                        ("Action", "Unmute (Button)"),
                        ("User", f"{member.name} ({member.nick})" if member.nick else member.name),
                        ("ID", str(member.id)),
                        ("Error", str(e)[:100]),
                    ])

        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to remove roles from this user.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Failed to unmute user: {str(e)}",
                ephemeral=True,
            )


class UnmuteButton(discord.ui.DynamicItem[discord.ui.Button], template=r"mod_unmute:(?P<user_id>\d+):(?P<guild_id>\d+)"):
    """
    Persistent unmute button that opens a modal to unmute with reason.
    """

    def __init__(self, user_id: int, guild_id: int) -> None:
        """Initialize the unmute button with target user context."""
        super().__init__(
            discord.ui.Button(
                label="Unmute",
                style=discord.ButtonStyle.secondary,
                emoji=UNMUTE_EMOJI,
                custom_id=f"mod_unmute:{user_id}:{guild_id}",
            )
        )
        self.user_id = user_id
        self.guild_id = guild_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "UnmuteButton":
        """Reconstruct button from custom_id regex match."""
        user_id = int(match.group("user_id"))
        guild_id = int(match.group("guild_id"))
        return cls(user_id, guild_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle button click - opens unmute modal."""
        logger.tree("Unmute Button Clicked", [
            ("Clicked By", f"{interaction.user} ({interaction.user.id})"),
            ("Target User ID", str(self.user_id)),
            ("Guild ID", str(self.guild_id)),
        ], emoji="🔊")

        db = get_db()

        if not db.is_user_muted(self.user_id, self.guild_id):
            # Check if there's a resolved mute case for context
            resolved_case = db.get_most_recent_resolved_case(self.user_id, self.guild_id, "mute")
            resolved_at = resolved_case.get("resolved_at") if resolved_case else None
            if resolved_at:
                resolved_timestamp = int(resolved_at)
                resolved_by = resolved_case.get("resolved_by")
                if resolved_by and resolved_by != 0:
                    await interaction.response.send_message(
                        f"✅ **Case Resolved**\n\n"
                        f"This user was unmuted <t:{resolved_timestamp}:R> by <@{resolved_by}>.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        f"✅ **Case Resolved**\n\n"
                        f"This user's mute expired <t:{resolved_timestamp}:R>.",
                        ephemeral=True,
                    )
            else:
                await interaction.response.send_message(
                    "This user is not currently muted.",
                    ephemeral=True,
                )
            return

        await interaction.response.send_modal(UnmuteModal(self.user_id, self.guild_id))


__all__ = [
    "ExtendModal",
    "ExtendButton",
    "UnmuteModal",
    "UnmuteButton",
]
