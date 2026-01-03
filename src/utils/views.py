"""
Azab Discord Bot - Shared UI Views
===================================

Reusable UI components for moderation commands.

Features:
    - InfoButton: Persistent button showing user details
    - CaseButtonView: View with Case link and Info button

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.core.logger import logger
from src.core.constants import (
    EMOJI_ID_CASE,
    EMOJI_ID_MESSAGE,
    EMOJI_ID_INFO,
    EMOJI_ID_DOWNLOAD,
    EMOJI_ID_HISTORY,
    EMOJI_ID_EXTEND,
    EMOJI_ID_UNMUTE,
    EMOJI_ID_NOTE,
    EMOJI_ID_APPEAL,
    EMOJI_ID_DENY,
    EMOJI_ID_APPROVE,
    WARNING_DECAY_DAYS,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    CASE_LOG_TIMEOUT,
)
from src.utils.footer import set_footer
from src.utils.duration import parse_duration

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# UI Constants
# =============================================================================

# App emojis from Discord Developer Portal (IDs from constants.py)
CASE_EMOJI = discord.PartialEmoji(name="case", id=EMOJI_ID_CASE)
MESSAGE_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon14", id=EMOJI_ID_MESSAGE)
INFO_EMOJI = discord.PartialEmoji(name="info", id=EMOJI_ID_INFO)
DOWNLOAD_EMOJI = discord.PartialEmoji(name="download", id=EMOJI_ID_DOWNLOAD)
HISTORY_EMOJI = discord.PartialEmoji(name="history", id=EMOJI_ID_HISTORY)
EXTEND_EMOJI = discord.PartialEmoji(name="extend", id=EMOJI_ID_EXTEND)
UNMUTE_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon3", id=EMOJI_ID_UNMUTE)
NOTE_EMOJI = discord.PartialEmoji(name="note", id=EMOJI_ID_NOTE)
APPEAL_EMOJI = discord.PartialEmoji(name="appeal", id=EMOJI_ID_APPEAL)
DENY_EMOJI = discord.PartialEmoji(name="deny", id=EMOJI_ID_DENY)


# =============================================================================
# Shared History Embed Builder
# =============================================================================

def build_history_view(
    cases: list,
    guild_id: int,
) -> Optional[discord.ui.View]:
    """
    Build a view for history display.

    NOTE: Case link buttons have been removed. Case IDs in the embed
    are now clickable links to website transcripts directly.

    Args:
        cases: List of case dicts from database
        guild_id: Guild ID (kept for compatibility)

    Returns:
        None - buttons are added separately by the caller (Info, Avatar)
    """
    # Case buttons removed - case IDs are now inline clickable links
    # in the embed description that go directly to website transcripts
    return None


async def build_history_embed(
    client,
    user_id: int,
    guild_id: int,
    cases: list,
) -> discord.Embed:
    """
    Build a unified history embed showing cases in compact table format.

    This is the canonical format used across:
    - HistoryButton (case dropdown)
    - /history command
    - Criminal History dropdown (tickets)

    Case IDs are clickable links to website transcripts.

    Args:
        client: Discord client for fetching user info
        user_id: Target user's ID
        guild_id: Guild ID for case thread links
        cases: List of case dicts from database

    Returns:
        discord.Embed with formatted history
    """
    from datetime import datetime

    config = get_config()
    embed = discord.Embed(color=EmbedColors.INFO)

    # Try to get user info
    username = "Unknown"
    try:
        user = await client.fetch_user(user_id)
        username = user.name
        embed.set_thumbnail(url=user.display_avatar.url)
    except Exception:
        pass

    embed.title = f"📋 Case History - {username}"

    if not cases:
        embed.description = "✅ No moderation history found. Clean record!"
        embed.set_footer(text="0 cases")
        return embed

    # Pre-fetch all unique moderator names in parallel
    mod_ids = set(c.get("moderator_id") for c in cases if c.get("moderator_id"))
    mod_names = {}

    async def fetch_mod_name(mid: int) -> tuple:
        try:
            mod = await client.fetch_user(mid)
            return (mid, mod.name[:10])
        except Exception:
            return (mid, str(mid)[:8])

    if mod_ids:
        results = await asyncio.gather(*[fetch_mod_name(mid) for mid in mod_ids])
        mod_names = {mid: name for mid, name in results}

    # Build compact table
    lines = []

    # Table header
    lines.append("```")
    lines.append("ID   │ Action  │ When  │ Moderator")
    lines.append("─────┼─────────┼───────┼────────────")

    for case in cases:
        case_id = case.get("case_id", "????")[:4]
        action_type = case.get("action_type", "?")
        created_at = case.get("created_at", 0)
        moderator_id = case.get("moderator_id")

        # Action display
        action_map = {
            "mute": "Mute",
            "ban": "Ban",
            "warn": "Warn",
            "forbid": "Forbid",
            "timeout": "Timeout",
            "unmute": "Unmute",
            "unban": "Unban",
            "unforbid": "Unforbid",
        }
        action_display = action_map.get(action_type, action_type.title())[:7]

        # Format time compactly
        if created_at:
            now = datetime.now().timestamp()
            diff = now - created_at
            if diff < 60:
                time_str = "now"
            elif diff < 3600:
                time_str = f"{int(diff/60)}m"
            elif diff < 86400:
                time_str = f"{int(diff/3600)}h"
            else:
                time_str = f"{int(diff/86400)}d"
        else:
            time_str = "?"

        # Get mod name from pre-fetched cache
        mod_name = mod_names.get(moderator_id, "?") if moderator_id else "?"

        # Build row
        lines.append(f"{case_id:4} │ {action_display:7} │ {time_str:5} │ {mod_name}")

    lines.append("```")

    # Add reason section below table with clickable case IDs
    # Links go to website transcript viewer
    reason_lines = []
    for case in cases:
        case_id = case.get("case_id", "????")
        case_id_short = case_id[:4]
        reason = case.get("reason")
        action_type = case.get("action_type", "?")
        status = case.get("status", "open")

        # Action emoji
        action_emoji = {
            "mute": "🔇", "ban": "🔨", "warn": "⚠️", "forbid": "🚫",
            "timeout": "⏰", "unmute": "🔊", "unban": "✅", "unforbid": "✅",
        }.get(action_type, "📋")

        # Status emoji
        status_emoji = "🔓" if status == "resolved" else "🔒"

        # Build transcript URL - links to website transcript viewer
        transcript_url = None
        if config.case_transcript_base_url:
            transcript_url = f"{config.case_transcript_base_url}/{case_id}"

        # Build line with clickable case ID
        reason_short = reason[:20] + "..." if reason and len(reason) > 20 else (reason or "-")
        if transcript_url:
            reason_lines.append(f"{status_emoji}{action_emoji} [`{case_id_short}`]({transcript_url}) {reason_short}")
        else:
            reason_lines.append(f"{status_emoji}{action_emoji} `{case_id_short}` {reason_short}")

    embed.description = "\n".join(lines) + "\n" + "\n".join(reason_lines)

    # Get case counts for footer
    db = get_db()
    counts = db.get_user_case_counts(user_id, guild_id)
    count_parts = []
    if counts.get("mute_count", 0) > 0:
        count_parts.append(f"🔇{counts['mute_count']}")
    if counts.get("ban_count", 0) > 0:
        count_parts.append(f"🔨{counts['ban_count']}")
    if counts.get("warn_count", 0) > 0:
        count_parts.append(f"⚠️{counts['warn_count']}")

    footer_text = f"{len(cases)} cases"
    if count_parts:
        footer_text += f" • {' '.join(count_parts)}"

    embed.set_footer(text=footer_text)
    return embed


# =============================================================================
# Persistent Info Button
# =============================================================================

class InfoButton(discord.ui.DynamicItem[discord.ui.Button], template=r"mod_info:(?P<user_id>\d+):(?P<guild_id>\d+)"):
    """
    Persistent info button that shows user details when clicked.

    Works after bot restart by using DynamicItem with regex pattern.
    """

    def __init__(self, user_id: int, guild_id: int):
        super().__init__(
            discord.ui.Button(
                label="Info",
                style=discord.ButtonStyle.secondary,
                emoji=INFO_EMOJI,
                custom_id=f"mod_info:{user_id}:{guild_id}",
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
    ) -> "InfoButton":
        """Reconstruct the button from the custom_id regex match."""
        user_id = int(match.group("user_id"))
        guild_id = int(match.group("guild_id"))
        return cls(user_id, guild_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show user info embed when clicked."""
        logger.tree("Info Button Clicked", [
            ("Clicked By", f"{interaction.user} ({interaction.user.id})"),
            ("Target User ID", str(self.user_id)),
            ("Guild ID", str(self.guild_id)),
        ], emoji="ℹ️")

        db = get_db()

        # Get member from guild
        guild = interaction.client.get_guild(self.guild_id)
        if not guild:
            await interaction.response.send_message(
                "Could not find guild.",
                ephemeral=True,
            )
            return

        member = guild.get_member(self.user_id)

        # Build info embed
        embed = discord.Embed(
            title="📋 User Info",
            color=EmbedColors.INFO,
        )

        if member:
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Username", value=f"`{member.name}`", inline=True)
            embed.add_field(name="Display Name", value=f"`{member.display_name}`", inline=True)
            embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)

            # Discord account creation
            embed.add_field(
                name="Discord Joined",
                value=f"<t:{int(member.created_at.timestamp())}:R>",
                inline=True,
            )

            # Server join date
            if member.joined_at:
                embed.add_field(
                    name="Server Joined",
                    value=f"<t:{int(member.joined_at.timestamp())}:R>",
                    inline=True,
                )

            # Account age
            now = datetime.now(NY_TZ)
            created_at = member.created_at.replace(tzinfo=NY_TZ) if member.created_at.tzinfo is None else member.created_at
            age_days = (now - created_at).days
            if age_days < 30:
                age_str = f"{age_days} days"
            elif age_days < 365:
                age_str = f"{age_days // 30} months"
            else:
                age_str = f"{age_days // 365} years, {(age_days % 365) // 30} months"
            embed.add_field(name="Account Age", value=f"`{age_str}`", inline=True)
        else:
            # User not in server (banned/left)
            try:
                user = await interaction.client.fetch_user(self.user_id)
                embed.set_thumbnail(url=user.display_avatar.url)
                embed.add_field(name="Username", value=f"`{user.name}`", inline=True)
                embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)
                embed.add_field(name="Status", value="⚠️ Not in Server", inline=True)
            except Exception:
                embed.add_field(name="User ID", value=f"`{self.user_id}`", inline=True)
                embed.add_field(name="Status", value="⚠️ User Not Found", inline=True)

        # Mute count
        mute_count = db.get_user_mute_count(self.user_id, self.guild_id)
        embed.add_field(
            name="Total Mutes",
            value=f"`{mute_count}`" if mute_count > 0 else "`0`",
            inline=True,
        )

        # Ban count
        ban_count = db.get_user_ban_count(self.user_id, self.guild_id)
        embed.add_field(
            name="Total Bans",
            value=f"`{ban_count}`" if ban_count > 0 else "`0`",
            inline=True,
        )

        # Warning count (active vs total)
        active_warns, total_warns = db.get_warn_counts(self.user_id, self.guild_id)
        if active_warns != total_warns:
            embed.add_field(
                name="Warnings",
                value=f"`{active_warns}` active (`{total_warns}` total)",
                inline=True,
            )
        else:
            embed.add_field(
                name="Warnings",
                value=f"`{active_warns}`",
                inline=True,
            )

        # Last mute info
        last_mute = db.get_last_mute_info(self.user_id)
        if last_mute and last_mute.get("last_mute_at"):
            mute_timestamp = int(last_mute["last_mute_at"])
            mute_duration = last_mute.get("last_mute_duration") or "Unknown"
            mute_mod_id = last_mute.get("last_mute_moderator_id")
            mute_mod_str = f"by <@{mute_mod_id}>" if mute_mod_id else ""
            embed.add_field(
                name="Last Muted",
                value=f"<t:{mute_timestamp}:R>\n`{mute_duration}` {mute_mod_str}",
                inline=True,
            )

        # Last ban info
        last_ban = db.get_last_ban_info(self.user_id)
        if last_ban and last_ban.get("last_ban_at"):
            ban_timestamp = int(last_ban["last_ban_at"])
            ban_mod_id = last_ban.get("last_ban_moderator_id")
            ban_mod_str = f"by <@{ban_mod_id}>" if ban_mod_id else ""
            embed.add_field(
                name="Last Banned",
                value=f"<t:{ban_timestamp}:R> {ban_mod_str}",
                inline=True,
            )

        # Warning for repeat offenders
        if mute_count >= 3 or ban_count >= 2 or active_warns >= 3:
            warnings = []
            if mute_count >= 3:
                warnings.append(f"{mute_count} mutes")
            if ban_count >= 2:
                warnings.append(f"{ban_count} bans")
            if active_warns >= 3:
                warnings.append(f"{active_warns} warnings")
            embed.add_field(
                name="⚠️ Warning",
                value=f"Repeat offender: {', '.join(warnings)}",
                inline=False,
            )

        # Previous names (show up to 5 with timestamps)
        username_history = db.get_username_history(self.user_id, limit=5)
        if username_history:
            history_lines = []
            for record in username_history:
                name = record.get("username") or record.get("display_name")
                if name:
                    timestamp = int(record.get("changed_at", 0))
                    history_lines.append(f"`{name}` <t:{timestamp}:R>")
            if history_lines:
                embed.add_field(
                    name="Previous Names",
                    value="\n".join(history_lines),
                    inline=False,
                )

        set_footer(embed)

        await interaction.response.send_message(embed=embed, ephemeral=True)


# =============================================================================
# Download Avatar Button (Persistent)
# =============================================================================

class DownloadButton(discord.ui.DynamicItem[discord.ui.Button], template=r"download_pfp:(?P<user_id>\d+)"):
    """
    Persistent download button that sends avatar as ephemeral message.

    Works after bot restart by using DynamicItem with regex pattern.
    """

    def __init__(self, user_id: int):
        super().__init__(
            discord.ui.Button(
                label="Avatar",
                style=discord.ButtonStyle.secondary,
                emoji=DOWNLOAD_EMOJI,
                custom_id=f"download_pfp:{user_id}",
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "DownloadButton":
        """Reconstruct the button from the custom_id regex match."""
        user_id = int(match.group("user_id"))
        return cls(user_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Send avatar URL as ephemeral message."""
        logger.tree("Avatar Download Clicked", [
            ("Clicked By", f"{interaction.user} ({interaction.user.id})"),
            ("Target User ID", str(self.user_id)),
        ], emoji="📥")

        try:
            # Try to get member first, then fetch user if not found
            user = None
            if interaction.guild:
                user = interaction.guild.get_member(self.user_id)

            if not user:
                user = await interaction.client.fetch_user(self.user_id)

            # Get high-res avatar URL
            avatar_url = user.display_avatar.replace(size=4096).url

            # Send just the URL (Discord will embed it as an image)
            await interaction.response.send_message(avatar_url, ephemeral=True)
        except discord.NotFound:
            await interaction.response.send_message("User not found.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to fetch avatar.", ephemeral=True)


# =============================================================================
# Avatar Change Buttons (Old/New)
# =============================================================================

class OldAvatarButton(discord.ui.DynamicItem[discord.ui.Button], template=r"avatar_old:(?P<channel_id>\d+):(?P<message_id>\d+)"):
    """Button that sends old avatar URL from log message attachment."""

    def __init__(self, channel_id: int, message_id: int):
        super().__init__(
            discord.ui.Button(
                label="Avatar (Old)",
                style=discord.ButtonStyle.secondary,
                emoji=DOWNLOAD_EMOJI,
                custom_id=f"avatar_old:{channel_id}:{message_id}",
            )
        )
        self.channel_id = channel_id
        self.message_id = message_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "OldAvatarButton":
        channel_id = int(match.group("channel_id"))
        message_id = int(match.group("message_id"))
        return cls(channel_id, message_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Fetch old avatar from message attachment and send ephemeral."""
        logger.tree("Old Avatar Button Clicked", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Message ID", str(self.message_id)),
        ], emoji="🖼️")

        try:
            channel = interaction.client.get_channel(self.channel_id)
            if not channel:
                channel = await interaction.client.fetch_channel(self.channel_id)
            message = await channel.fetch_message(self.message_id)
            if message.attachments:
                await interaction.response.send_message(message.attachments[0].url, ephemeral=True)
            else:
                await interaction.response.send_message("Old avatar not found.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Failed to fetch old avatar.", ephemeral=True)


class NewAvatarButton(discord.ui.DynamicItem[discord.ui.Button], template=r"avatar_new:(?P<channel_id>\d+):(?P<message_id>\d+)"):
    """Button that sends new avatar URL from log message embed image."""

    def __init__(self, channel_id: int, message_id: int):
        super().__init__(
            discord.ui.Button(
                label="Avatar (New)",
                style=discord.ButtonStyle.secondary,
                emoji=DOWNLOAD_EMOJI,
                custom_id=f"avatar_new:{channel_id}:{message_id}",
            )
        )
        self.channel_id = channel_id
        self.message_id = message_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "NewAvatarButton":
        channel_id = int(match.group("channel_id"))
        message_id = int(match.group("message_id"))
        return cls(channel_id, message_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Fetch new avatar from message embed image and send ephemeral."""
        logger.tree("New Avatar Button Clicked", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Message ID", str(self.message_id)),
        ], emoji="🖼️")

        try:
            channel = interaction.client.get_channel(self.channel_id)
            if not channel:
                channel = await interaction.client.fetch_channel(self.channel_id)
            message = await channel.fetch_message(self.message_id)
            if message.embeds and message.embeds[0].image:
                await interaction.response.send_message(message.embeds[0].image.url, ephemeral=True)
            else:
                await interaction.response.send_message("New avatar not found.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Failed to fetch new avatar.", ephemeral=True)


# =============================================================================
# History Button with Pagination
# =============================================================================

class HistoryButton(discord.ui.DynamicItem[discord.ui.Button], template=r"mod_history:(?P<user_id>\d+):(?P<guild_id>\d+)"):
    """
    Persistent history button that shows paginated mute/ban history.
    """

    def __init__(self, user_id: int, guild_id: int):
        super().__init__(
            discord.ui.Button(
                label="History",
                style=discord.ButtonStyle.secondary,
                emoji=HISTORY_EMOJI,
                custom_id=f"mod_history:{user_id}:{guild_id}",
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
    ) -> "HistoryButton":
        user_id = int(match.group("user_id"))
        guild_id = int(match.group("guild_id"))
        return cls(user_id, guild_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show paginated history embed with per-action cases."""
        logger.tree("History Button Clicked", [
            ("Clicked By", f"{interaction.user} ({interaction.user.id})"),
            ("Target User ID", str(self.user_id)),
            ("Guild ID", str(self.guild_id)),
        ], emoji="📜")

        db = get_db()

        # Try to get per-action cases first (new system)
        cases = db.get_user_cases(self.user_id, self.guild_id, limit=10, include_resolved=True)

        if cases:
            # Show per-action cases with links to threads (using shared function)
            embed = await build_history_embed(interaction.client, self.user_id, self.guild_id, cases)
            view = build_history_view(cases, self.guild_id)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return

        # Fall back to legacy history if no per-action cases
        total_count = db.get_history_count(self.user_id, self.guild_id)
        history = db.get_combined_history(self.user_id, self.guild_id, limit=5, offset=0)

        if not history:
            await interaction.response.send_message(
                "No moderation history found for this user.",
                ephemeral=True,
            )
            return

        # Build legacy history embed
        embed = await self._build_history_embed(interaction.client, history, 0, total_count)

        # Create pagination view if needed
        if total_count > 5:
            view = HistoryPaginationView(self.user_id, self.guild_id, 0, total_count)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _build_history_embed(
        self,
        client,
        history: list,
        page: int,
        total: int,
    ) -> discord.Embed:
        """Build the history embed for a specific page."""
        embed = discord.Embed(
            title="Moderation History",
            color=EmbedColors.INFO,
        )

        # Try to get user info
        try:
            user = await client.fetch_user(self.user_id)
            embed.set_author(name=user.name, icon_url=user.display_avatar.url)
        except Exception:
            pass

        import time as time_module

        for record in history:
            # Format the entry
            action = record.get("action", "unknown")
            action_type = record.get("type", "mute")
            timestamp = record.get("timestamp", 0)
            reason = record.get("reason") or "No reason provided"
            moderator_id = record.get("moderator_id")
            duration_seconds = record.get("duration_seconds")

            # Check if warning is expired
            is_expired = False
            if action == "warn":
                decay_cutoff = time_module.time() - (WARNING_DECAY_DAYS * SECONDS_PER_DAY)
                is_expired = timestamp < decay_cutoff

            # Action emoji
            if action == "mute":
                emoji = "🔇"
            elif action == "unmute":
                emoji = "🔊"
            elif action == "extend":
                emoji = "⏱️"
            elif action == "ban":
                emoji = "🔨"
            elif action == "unban":
                emoji = "🔓"
            elif action == "warn":
                emoji = "⚠️" if not is_expired else "📋"
            else:
                emoji = "📋"

            # Format duration
            duration_str = ""
            if duration_seconds:
                hours, remainder = divmod(int(duration_seconds), SECONDS_PER_HOUR)
                minutes, _ = divmod(remainder, 60)
                if hours > 0:
                    duration_str = f" ({hours}h {minutes}m)" if minutes else f" ({hours}h)"
                else:
                    duration_str = f" ({minutes}m)"

            # Format timestamp
            time_str = f"<t:{int(timestamp)}:R>"

            # Build field value
            value = f"**Reason:** {reason[:100]}\n**By:** <@{moderator_id}>\n**When:** {time_str}"
            if duration_str:
                value += f"\n**Duration:** {duration_str}"

            # Mark expired warnings
            action_title = action.title()
            if is_expired:
                action_title = f"~~{action_title}~~ (expired)"

            embed.add_field(
                name=f"{emoji} {action_title}{duration_str}",
                value=value,
                inline=False,
            )

        # Footer with pagination info
        total_pages = (total + 4) // 5  # Ceiling division
        embed.set_footer(text=f"Page {page + 1}/{total_pages} • {total} total records")

        return embed


class PaginationPrevButton(discord.ui.DynamicItem[discord.ui.Button], template=r"hist_prev:(?P<user_id>\d+):(?P<guild_id>\d+):(?P<page>\d+):(?P<total>\d+)"):
    """Persistent Previous button for pagination."""

    def __init__(self, user_id: int, guild_id: int, page: int, total: int):
        total_pages = (total + 4) // 5
        super().__init__(
            discord.ui.Button(
                label="Previous",
                style=discord.ButtonStyle.secondary,
                custom_id=f"hist_prev:{user_id}:{guild_id}:{page}:{total}",
                disabled=(page == 0),
            )
        )
        self.user_id = user_id
        self.guild_id = guild_id
        self.page = page
        self.total = total
        self.total_pages = total_pages

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match) -> "PaginationPrevButton":
        return cls(int(match.group("user_id")), int(match.group("guild_id")), int(match.group("page")), int(match.group("total")))

    async def callback(self, interaction: discord.Interaction) -> None:
        logger.tree("History Prev Button Clicked", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Target User ID", str(self.user_id)),
            ("Page", f"{self.page} → {max(0, self.page - 1)}"),
        ], emoji="◀️")

        new_page = max(0, self.page - 1)
        view = HistoryPaginationView(self.user_id, self.guild_id, new_page, self.total)
        embed = await view._build_embed(interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)


class PaginationNextButton(discord.ui.DynamicItem[discord.ui.Button], template=r"hist_next:(?P<user_id>\d+):(?P<guild_id>\d+):(?P<page>\d+):(?P<total>\d+)"):
    """Persistent Next button for pagination."""

    def __init__(self, user_id: int, guild_id: int, page: int, total: int):
        total_pages = (total + 4) // 5
        super().__init__(
            discord.ui.Button(
                label="Next",
                style=discord.ButtonStyle.secondary,
                custom_id=f"hist_next:{user_id}:{guild_id}:{page}:{total}",
                disabled=(page >= total_pages - 1),
            )
        )
        self.user_id = user_id
        self.guild_id = guild_id
        self.page = page
        self.total = total
        self.total_pages = total_pages

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match) -> "PaginationNextButton":
        return cls(int(match.group("user_id")), int(match.group("guild_id")), int(match.group("page")), int(match.group("total")))

    async def callback(self, interaction: discord.Interaction) -> None:
        logger.tree("History Next Button Clicked", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Target User ID", str(self.user_id)),
            ("Page", f"{self.page} → {min(self.total_pages - 1, self.page + 1)}"),
        ], emoji="▶️")

        new_page = min(self.total_pages - 1, self.page + 1)
        view = HistoryPaginationView(self.user_id, self.guild_id, new_page, self.total)
        embed = await view._build_embed(interaction.client)
        await interaction.response.edit_message(embed=embed, view=view)


class HistoryPaginationView(discord.ui.View):
    """Pagination view for history display."""

    def __init__(self, user_id: int, guild_id: int, page: int, total: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.guild_id = guild_id
        self.page = page
        self.total = total
        self.total_pages = (total + 4) // 5

        # Add persistent pagination buttons
        self.add_item(PaginationPrevButton(user_id, guild_id, page, total))
        self.add_item(PaginationNextButton(user_id, guild_id, page, total))

    async def _build_embed(self, client) -> discord.Embed:
        db = get_db()
        history = db.get_combined_history(self.user_id, self.guild_id, limit=5, offset=self.page * 5)

        embed = discord.Embed(
            title="Moderation History",
            color=EmbedColors.INFO,
        )

        try:
            user = await client.fetch_user(self.user_id)
            embed.set_author(name=user.name, icon_url=user.display_avatar.url)
        except Exception:
            pass

        import time as time_module

        for record in history:
            action = record.get("action", "unknown")
            timestamp = record.get("timestamp", 0)
            reason = record.get("reason") or "No reason provided"
            moderator_id = record.get("moderator_id")
            duration_seconds = record.get("duration_seconds")

            # Check if warning is expired
            is_expired = False
            if action == "warn":
                decay_cutoff = time_module.time() - (WARNING_DECAY_DAYS * SECONDS_PER_DAY)
                is_expired = timestamp < decay_cutoff

            if action == "mute":
                emoji = "🔇"
            elif action == "unmute":
                emoji = "🔊"
            elif action == "extend":
                emoji = "⏱️"
            elif action == "ban":
                emoji = "🔨"
            elif action == "unban":
                emoji = "🔓"
            elif action == "warn":
                emoji = "⚠️" if not is_expired else "📋"
            else:
                emoji = "📋"

            duration_str = ""
            if duration_seconds:
                hours, remainder = divmod(int(duration_seconds), SECONDS_PER_HOUR)
                minutes, _ = divmod(remainder, 60)
                if hours > 0:
                    duration_str = f" ({hours}h {minutes}m)" if minutes else f" ({hours}h)"
                else:
                    duration_str = f" ({minutes}m)"

            time_str = f"<t:{int(timestamp)}:R>"
            value = f"**Reason:** {reason[:100]}\n**By:** <@{moderator_id}>\n**When:** {time_str}"
            if duration_str:
                value += f"\n**Duration:** {duration_str}"

            # Mark expired warnings
            action_title = action.title()
            if is_expired:
                action_title = f"~~{action_title}~~ (expired)"

            embed.add_field(
                name=f"{emoji} {action_title}{duration_str}",
                value=value,
                inline=False,
            )

        embed.set_footer(text=f"Page {self.page + 1}/{self.total_pages} • {self.total} total records")
        return embed


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


# =============================================================================
# Approve Button (Owner Only)
# =============================================================================

APPROVE_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon18", id=EMOJI_ID_APPROVE)


class ApproveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"approve_case:(?P<thread_id>\d+):(?P<case_id>\w+)"):
    """
    Persistent approve button that closes/archives the case thread when clicked by owner.

    Works after bot restart by using DynamicItem with regex pattern.
    Only the developer/owner can use this button.
    """

    def __init__(self, thread_id: int, case_id: str):
        super().__init__(
            discord.ui.Button(
                label="Approve",
                style=discord.ButtonStyle.secondary,
                emoji=APPROVE_EMOJI,
                custom_id=f"approve_case:{thread_id}:{case_id}",
            )
        )
        self.thread_id = thread_id
        self.case_id = case_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "ApproveButton":
        """Reconstruct the button from the custom_id regex match."""
        thread_id = int(match.group("thread_id"))
        case_id = match.group("case_id")
        return cls(thread_id, case_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle approve button click - only owner can use."""
        from src.core.config import is_developer, get_config
        from src.services.case_log.transcript import TranscriptBuilder
        from src.services.case_log.views import CaseControlPanelView
        from src.services.case_log.embeds import build_control_panel_embed
        from src.utils.retry import safe_fetch_message, safe_edit

        config = get_config()

        # Only owner can approve
        if not is_developer(interaction.user.id):
            await interaction.response.send_message(
                "Only the owner can approve cases.",
                ephemeral=True,
            )
            return

        try:
            # Get the thread
            thread = interaction.channel
            if not isinstance(thread, discord.Thread):
                await interaction.response.send_message(
                    "This button can only be used in case threads.",
                    ephemeral=True,
                )
                return

            # Update database FIRST (before Discord action)
            db = get_db()
            db.approve_case(self.case_id, interaction.user.id)

            # Get case info for action-type-based deletion timing
            case_info = db.get_case(self.case_id)
            action_type = case_info.get("action_type", "mute") if case_info else "mute"

            # Calculate deletion time based on action type
            # Ban: 30 days, Mute: 14 days, Other: 7 days
            import time
            now = int(time.time())
            if action_type == "ban":
                retention_days = 30
            elif action_type in ("mute", "timeout"):
                retention_days = 14
            else:
                retention_days = 7
            deletion_timestamp = now + (retention_days * 24 * 60 * 60)

            # Build and save transcript immediately
            transcript_saved = False
            existing_transcript = db.get_case_transcript(self.case_id)
            if not existing_transcript:
                try:
                    # Fetch case info for target user and moderator names
                    case_info = db.get_case(self.case_id)
                    target_user_id = case_info.get("user_id") if case_info else None
                    moderator_id = case_info.get("moderator_id") if case_info else None

                    # Try to fetch user names from Discord
                    target_user_name = None
                    moderator_name = None

                    if target_user_id:
                        try:
                            target_user = await interaction.client.fetch_user(target_user_id)
                            target_user_name = target_user.display_name
                        except Exception:
                            pass

                    if moderator_id:
                        try:
                            moderator_user = await interaction.client.fetch_user(moderator_id)
                            moderator_name = moderator_user.display_name
                        except Exception:
                            pass

                    transcript_builder = TranscriptBuilder(
                        interaction.client,
                        config.transcript_assets_thread_id
                    )
                    transcript = await transcript_builder.build_from_thread(
                        thread=thread,
                        case_id=self.case_id,
                        target_user_id=target_user_id,
                        target_user_name=target_user_name,
                        moderator_id=moderator_id,
                        moderator_name=moderator_name,
                    )
                    if transcript:
                        transcript_saved = db.save_case_transcript(self.case_id, transcript.to_json())
                        if transcript_saved:
                            logger.tree("Transcript Created On Approval", [
                                ("Case ID", self.case_id),
                                ("Messages", str(transcript.message_count)),
                                ("Target", f"{target_user_name} ({target_user_id})"),
                                ("Moderator", f"{moderator_name} ({moderator_id})"),
                            ], emoji="📝")
                except Exception as e:
                    logger.warning("Transcript Creation Failed", [
                        ("Case ID", self.case_id),
                        ("Error", str(e)[:50]),
                    ])
            else:
                transcript_saved = True  # Already exists

            # Build approval embed with deletion time (NO transcript button here)
            embed = discord.Embed(
                title="✅ Case Approved",
                color=EmbedColors.SUCCESS,
                timestamp=datetime.now(NY_TZ),
            )
            embed.add_field(
                name="Approved By",
                value=interaction.user.mention,
                inline=True,
            )
            embed.add_field(
                name="Case ID",
                value=f"`{self.case_id}`",
                inline=True,
            )
            embed.add_field(
                name="🗑️ Auto-Delete",
                value=f"<t:{deletion_timestamp}:F>\n(<t:{deletion_timestamp}:R>)",
                inline=False,
            )
            set_footer(embed)

            # Send approval embed WITHOUT transcript button
            await interaction.response.send_message(embed=embed)

            # Update the control panel with transcript button
            transcript_url = None
            if config.case_transcript_base_url and transcript_saved:
                transcript_url = f"{config.case_transcript_base_url}/{self.case_id}"

            # Find and update the control panel
            case = db.get_case(self.case_id)
            if case:
                control_panel_msg_id = case.get("control_panel_message_id")

                # If not found, search pinned messages
                if not control_panel_msg_id:
                    try:
                        pinned = await thread.pins()
                        for msg in pinned:
                            if msg.embeds and msg.embeds[0].title and "Control Panel" in msg.embeds[0].title:
                                control_panel_msg_id = msg.id
                                db.set_case_control_panel_message(self.case_id, msg.id)
                                break
                    except Exception:
                        pass

                if control_panel_msg_id:
                    control_msg = await safe_fetch_message(thread, control_panel_msg_id)
                    if control_msg:
                        # Build updated control panel embed
                        # Note: Don't pass moderator here - use case data to preserve original moderator
                        control_embed = build_control_panel_embed(
                            case=case,
                            user=None,
                            moderator=None,  # Let it use case.get("moderator_id")
                            status="approved",
                        )

                        # Check if evidence exists
                        evidence_urls = db.get_case_evidence(self.case_id)
                        has_evidence = len(evidence_urls) > 0

                        # Build control panel view with transcript button
                        control_view = CaseControlPanelView(
                            user_id=case.get("user_id"),
                            guild_id=case.get("guild_id"),
                            case_id=self.case_id,
                            case_thread_id=thread.id,
                            status="approved",
                            is_mute=case.get("action_type") in ("mute", "timeout"),
                            has_evidence=has_evidence,
                            transcript_url=transcript_url,
                        )

                        await safe_edit(control_msg, embed=control_embed, view=control_view)
                        logger.tree("Control Panel Updated With Transcript", [
                            ("Case ID", self.case_id),
                            ("Has Transcript", "Yes" if transcript_url else "No"),
                        ], emoji="🎛️")

            # Add green check mark to thread name
            current_name = thread.name
            if not current_name.startswith("✅"):
                new_name = f"✅ | {current_name}"
                # Discord thread names max 100 chars
                if len(new_name) > 100:
                    new_name = new_name[:100]
                await thread.edit(name=new_name)

            # Update tags to show "Approved" status
            approved_tags = []
            if hasattr(interaction.client, 'case_log_service') and interaction.client.case_log_service:
                approved_tags = interaction.client.case_log_service.get_tags_for_case(
                    action_type, is_approved=True
                )

            # Lock the thread (but DON'T archive - keep visible during cooldown)
            # Thread will be deleted by scheduler after retention period
            if approved_tags:
                await thread.edit(
                    locked=True,
                    applied_tags=approved_tags,
                    reason=f"Case approved by {interaction.user.display_name}",
                )
            else:
                await thread.edit(
                    locked=True,
                    reason=f"Case approved by {interaction.user.display_name}",
                )

            tag_names = [t.name for t in approved_tags] if approved_tags else []
            logger.tree("Case Approved", [
                ("Case ID", self.case_id),
                ("Thread ID", str(self.thread_id)),
                ("Approved By", f"{interaction.user.display_name} ({interaction.user.id})"),
                ("Tags Updated", ", ".join(tag_names) if tag_names else "None"),
                ("Transcript", "Yes" if transcript_url else "No"),
                ("Deletes At", f"<t:{deletion_timestamp}:F>"),
            ], emoji="✅")

            # Log transcript via logging service
            if transcript_url and case and hasattr(interaction.client, 'logging_service') and interaction.client.logging_service:
                try:
                    user_id = case.get("user_id")
                    action_type = case.get("action_type", "unknown")
                    reason = case.get("reason") or "No reason provided"
                    moderator_id = case.get("moderator_id")
                    created_at = case.get("created_at")

                    # Try to get user info
                    try:
                        user = await interaction.client.fetch_user(user_id)
                    except Exception:
                        user = None

                    if user:
                        case_thread_url = f"https://discord.com/channels/{case.get('guild_id')}/{thread.id}"
                        await interaction.client.logging_service.log_case_transcript(
                            case_id=self.case_id,
                            user=user,
                            action_type=action_type,
                            moderator_id=moderator_id,
                            reason=reason,
                            created_at=created_at or 0,
                            approved_by=interaction.user,
                            transcript_url=transcript_url,
                            case_thread_url=case_thread_url,
                        )

                        logger.tree("Case Transcript Logged", [
                            ("Case ID", self.case_id),
                            ("User", user.name),
                        ], emoji="📜")
                except Exception as e:
                    logger.warning("Failed to Log Case Transcript", [
                        ("Case ID", self.case_id),
                        ("Error", str(e)[:50]),
                    ])

        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to archive this thread.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error("Approve Button Error", [
                ("Case ID", self.case_id),
                ("Error Type", type(e).__name__),
                ("Error", str(e)[:100]),
            ])
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "An error occurred while approving the case.",
                        ephemeral=True,
                    )
            except discord.HTTPException as e:
                logger.debug(f"Approve error response failed: {e.code} - {e.text[:50] if e.text else 'No text'}")


# =============================================================================
# Case Button View
# =============================================================================

class CaseButtonView(discord.ui.View):
    """View with Case link button for public response."""

    def __init__(self, guild_id: int, thread_id: int, user_id: int):
        super().__init__(timeout=None)

        # Case link button (links to case thread with control panel)
        url = f"https://discord.com/channels/{guild_id}/{thread_id}"
        self.add_item(discord.ui.Button(
            label="Case",
            url=url,
            style=discord.ButtonStyle.link,
            emoji=CASE_EMOJI,
        ))


# =============================================================================
# Message Button View
# =============================================================================

class MessageButtonView(discord.ui.View):
    """View with a single Message link button."""

    def __init__(self, jump_url: str):
        super().__init__(timeout=None)

        # Message link button
        self.add_item(discord.ui.Button(
            label="Message",
            url=jump_url,
            style=discord.ButtonStyle.link,
            emoji=MESSAGE_EMOJI,
        ))


# =============================================================================
# Edit Case Button & Modal
# =============================================================================

class EditCaseModal(discord.ui.Modal):
    """Modal for editing case reason."""

    def __init__(self, case_id: str, current_reason: Optional[str] = None):
        super().__init__(title="Edit Case Reason")
        self.case_id = case_id

        self.reason_input = discord.ui.TextInput(
            label="Reason",
            style=discord.TextStyle.paragraph,
            placeholder="Enter the updated reason for this case...",
            default=current_reason or "",
            required=False,
            max_length=1000,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        new_reason = self.reason_input.value.strip() or None

        try:
            # Update case in database
            db = get_db()
            success = db.update_case_reason(self.case_id, new_reason, interaction.user.id)

            if success:
                await interaction.response.send_message(
                    f"✏️ **Case Updated** by {interaction.user.mention}\n"
                    f"**New Reason:** {new_reason or 'No reason provided'}",
                    ephemeral=False,
                )

                logger.tree("Case Edited", [
                    ("Case ID", self.case_id),
                    ("Editor", f"{interaction.user} ({interaction.user.id})"),
                    ("New Reason", (new_reason or "None")[:50]),
                ], emoji="✏️")
            else:
                await interaction.response.send_message(
                    "❌ Failed to update case. Case may not exist.",
                    ephemeral=True,
                )
        except Exception as e:
            logger.error("Edit Case Failed", [
                ("Case ID", self.case_id),
                ("Error", str(e)[:50]),
            ])
            await interaction.response.send_message(
                "❌ An error occurred while updating the case.",
                ephemeral=True,
            )


class EditCaseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"edit_case:(?P<case_id>\w+)"):
    """
    Persistent edit button that allows moderators to edit case reason.

    Works after bot restart by using DynamicItem with regex pattern.
    Only moderators can use this button.
    """

    def __init__(self, case_id: str):
        super().__init__(
            discord.ui.Button(
                label="Edit",
                style=discord.ButtonStyle.secondary,
                emoji=NOTE_EMOJI,
                custom_id=f"edit_case:{case_id}",
            )
        )
        self.case_id = case_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "EditCaseButton":
        """Reconstruct the button from the custom_id regex match."""
        case_id = match.group("case_id")
        return cls(case_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle edit button click - only moderators can use."""
        logger.tree("Edit Case Button Clicked", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Case ID", self.case_id),
        ], emoji="✏️")

        from src.core.config import get_config, is_developer

        config = get_config()

        # Check if user is moderator or developer
        is_mod = False
        if isinstance(interaction.user, discord.Member):
            if is_developer(interaction.user.id):
                is_mod = True
            elif interaction.user.guild_permissions.moderate_members:
                is_mod = True
            elif config.moderation_role_id and interaction.user.get_role(config.moderation_role_id):
                is_mod = True

        if not is_mod:
            await interaction.response.send_message(
                "❌ Only moderators can edit cases.",
                ephemeral=True,
            )
            return

        try:
            # Get current case info
            db = get_db()
            case = db.get_case(self.case_id)

            current_reason = case.get("reason") if case else None

            # Show edit modal
            modal = EditCaseModal(self.case_id, current_reason)
            await interaction.response.send_modal(modal)

        except Exception as e:
            logger.error("Edit Case Button Failed", [
                ("Case ID", self.case_id),
                ("Error", str(e)[:50]),
            ])
            await interaction.response.send_message(
                "❌ Failed to open edit modal.",
                ephemeral=True,
            )


# =============================================================================
# User Info Select (Dropdown for Info, Avatar, History)
# =============================================================================

class UserInfoSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"user_info_select:(?P<user_id>\d+):(?P<guild_id>\d+)"):
    """
    Persistent dropdown for user info actions.

    Options: Info, Avatar, History
    Used across case logs, appeals, modmail, and tickets.
    """

    def __init__(self, user_id: int, guild_id: int):
        select = discord.ui.Select(
            placeholder="👤 User Info",
            options=[
                discord.SelectOption(
                    label="Info",
                    value="info",
                    emoji=INFO_EMOJI,
                    description="View user details",
                ),
                discord.SelectOption(
                    label="Avatar",
                    value="avatar",
                    emoji=DOWNLOAD_EMOJI,
                    description="Download user avatar",
                ),
                discord.SelectOption(
                    label="History",
                    value="history",
                    emoji=HISTORY_EMOJI,
                    description="View moderation history",
                ),
            ],
            custom_id=f"user_info_select:{user_id}:{guild_id}",
            row=0,
        )
        super().__init__(select)
        self.user_id = user_id
        self.guild_id = guild_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Select,
        match: re.Match[str],
    ) -> "UserInfoSelect":
        user_id = int(match.group("user_id"))
        guild_id = int(match.group("guild_id"))
        return cls(user_id, guild_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle dropdown selection."""
        # Get selected value from the underlying Select item
        selected = self.item.values[0] if self.item.values else None

        logger.tree("User Info Dropdown Selected", [
            ("Clicked By", f"{interaction.user.name} ({interaction.user.id})"),
            ("Selection", selected or "None"),
            ("Target User ID", str(self.user_id)),
            ("Channel", "DM" if isinstance(interaction.channel, discord.DMChannel) else (interaction.channel.name if hasattr(interaction.channel, 'name') else str(interaction.channel))),
        ], emoji="👤")

        if selected == "info":
            # Delegate to InfoButton's callback logic
            info_btn = InfoButton(self.user_id, self.guild_id)
            await info_btn.callback(interaction)
        elif selected == "avatar":
            # Delegate to DownloadButton's callback logic
            avatar_btn = DownloadButton(self.user_id)
            await avatar_btn.callback(interaction)
        elif selected == "history":
            # Delegate to HistoryButton's callback logic
            history_btn = HistoryButton(self.user_id, self.guild_id)
            await history_btn.callback(interaction)


# =============================================================================
# View Registration
# =============================================================================

def setup_moderation_views(bot: "AzabBot") -> None:
    """
    Register persistent views for moderation buttons.

    Call this on bot startup to enable button persistence after restart.
    """
    bot.add_dynamic_items(
        InfoButton,
        DownloadButton,
        HistoryButton,
        PaginationPrevButton,
        PaginationNextButton,
        ExtendButton,
        UnmuteButton,
        ApproveButton,
        EditCaseButton,
        UserInfoSelect,
    )


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "CASE_EMOJI",
    "MESSAGE_EMOJI",
    "INFO_EMOJI",
    "DOWNLOAD_EMOJI",
    "HISTORY_EMOJI",
    "EXTEND_EMOJI",
    "UNMUTE_EMOJI",
    "APPROVE_EMOJI",
    "APPEAL_EMOJI",
    "DENY_EMOJI",
    "build_history_embed",
    "build_history_view",
    "InfoButton",
    "DownloadButton",
    "HistoryButton",
    "ExtendButton",
    "UnmuteButton",
    "ApproveButton",
    "EditCaseButton",
    "UserInfoSelect",
    "CaseButtonView",
    "MessageButtonView",
    "setup_moderation_views",
]
