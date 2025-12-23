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

import re
from datetime import datetime
from typing import TYPE_CHECKING

import discord

from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# UI Constants
# =============================================================================

# App emojis from Discord Developer Portal
CASE_EMOJI = discord.PartialEmoji(name="case", id=1452426909077213255)
MESSAGE_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon14", id=1452783032460247150)
INFO_EMOJI = discord.PartialEmoji(name="info", id=1452510787817046197)
DOWNLOAD_EMOJI = discord.PartialEmoji(name="download", id=1452689360804909148)
HISTORY_EMOJI = discord.PartialEmoji(name="history", id=1452963786427469894)
EXTEND_EMOJI = discord.PartialEmoji(name="extend", id=1452963975150174410)
UNMUTE_EMOJI = discord.PartialEmoji(name="discotoolsxyzicon3", id=1452964296572272703)
NOTE_EMOJI = discord.PartialEmoji(name="note", id=1452964649271037974)


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
        """Show paginated history embed."""
        db = get_db()

        # Get history count and first page
        total_count = db.get_history_count(self.user_id, self.guild_id)
        history = db.get_combined_history(self.user_id, self.guild_id, limit=5, offset=0)

        if not history:
            await interaction.response.send_message(
                "No moderation history found for this user.",
                ephemeral=True,
            )
            return

        # Build history embed
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
        WARNING_DECAY_DAYS = 30  # Match database.py constant

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
                decay_cutoff = time_module.time() - (WARNING_DECAY_DAYS * 86400)
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
                hours, remainder = divmod(int(duration_seconds), 3600)
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


class HistoryPaginationView(discord.ui.View):
    """Pagination view for history display."""

    def __init__(self, user_id: int, guild_id: int, page: int, total: int):
        super().__init__(timeout=300)  # 5 minute timeout
        self.user_id = user_id
        self.guild_id = guild_id
        self.page = page
        self.total = total
        self.total_pages = (total + 4) // 5

        # Disable buttons appropriately
        self.prev_button.disabled = page == 0
        self.next_button.disabled = page >= self.total_pages - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        await self._update_page(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        await self._update_page(interaction)

    async def _update_page(self, interaction: discord.Interaction):
        db = get_db()
        history = db.get_combined_history(self.user_id, self.guild_id, limit=5, offset=self.page * 5)

        # Build new embed
        embed = await self._build_embed(interaction.client, history)

        # Update button states
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page >= self.total_pages - 1

        await interaction.response.edit_message(embed=embed, view=self)

    async def _build_embed(self, client, history: list) -> discord.Embed:
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
        WARNING_DECAY_DAYS = 30  # Match database.py constant

        for record in history:
            action = record.get("action", "unknown")
            timestamp = record.get("timestamp", 0)
            reason = record.get("reason") or "No reason provided"
            moderator_id = record.get("moderator_id")
            duration_seconds = record.get("duration_seconds")

            # Check if warning is expired
            is_expired = False
            if action == "warn":
                decay_cutoff = time_module.time() - (WARNING_DECAY_DAYS * 86400)
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
                hours, remainder = divmod(int(duration_seconds), 3600)
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

    def __init__(self, user_id: int, guild_id: int):
        super().__init__()
        self.user_id = user_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        db = get_db()

        # Parse duration
        duration_str = self.duration.value.lower().strip()
        total_seconds = self._parse_duration(duration_str)

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

        # Success message
        await interaction.response.send_message(
            f"Mute extended by **{duration_str}**. New expiration: <t:{int(new_expires)}:R>",
            ephemeral=True,
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

    def _parse_duration(self, duration_str: str) -> int | None:
        """Parse duration string like 1h, 30m, 2h30m, 1d into seconds."""
        import re as regex
        total = 0
        pattern = regex.compile(r'(\d+)([dhms])')
        matches = pattern.findall(duration_str)

        if not matches:
            # Try just a number (assume minutes)
            try:
                return int(duration_str) * 60
            except ValueError:
                return None

        for value, unit in matches:
            value = int(value)
            if unit == 'd':
                total += value * 86400
            elif unit == 'h':
                total += value * 3600
            elif unit == 'm':
                total += value * 60
            elif unit == 's':
                total += value

        return total if total > 0 else None


class ExtendButton(discord.ui.DynamicItem[discord.ui.Button], template=r"mod_extend:(?P<user_id>\d+):(?P<guild_id>\d+)"):
    """
    Persistent extend button that opens a modal to extend mute duration.
    """

    def __init__(self, user_id: int, guild_id: int):
        super().__init__(
            discord.ui.Button(
                label="Extend",
                style=discord.ButtonStyle.primary,
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
        user_id = int(match.group("user_id"))
        guild_id = int(match.group("guild_id"))
        return cls(user_id, guild_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        # Check if user is currently muted
        db = get_db()
        active_mute = db.get_active_mute(self.user_id, self.guild_id)

        if not active_mute:
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

    def __init__(self, user_id: int, guild_id: int):
        super().__init__()
        self.user_id = user_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        db = get_db()
        config = get_config()

        # Check if still muted
        if not db.is_user_muted(self.user_id, self.guild_id):
            await interaction.response.send_message(
                "This user is not currently muted.",
                ephemeral=True,
            )
            return

        # Get member and remove mute role
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Could not find guild.", ephemeral=True)
            return

        member = guild.get_member(self.user_id)
        if not member:
            await interaction.response.send_message(
                "User is no longer in the server.",
                ephemeral=True,
            )
            return

        mute_role = guild.get_role(config.MUTED_ROLE_ID)
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
                f"Successfully unmuted {member.mention}.",
                ephemeral=True,
            )

            # Log to case thread
            try:
                case_log = db.get_case_log(self.user_id)
                if case_log:
                    thread = guild.get_thread(case_log["thread_id"])
                    if thread:
                        reason_text = self.reason.value if self.reason.value else "No reason provided"
                        embed = discord.Embed(
                            title="🔊 User Unmuted",
                            color=EmbedColors.SUCCESS,
                        )
                        embed.add_field(name="User", value=f"{member.mention}\n`{member.name}`", inline=True)
                        embed.add_field(name="Unmuted By", value=f"{interaction.user.mention}\n`{interaction.user.name}`", inline=True)
                        embed.add_field(name="Reason", value=reason_text, inline=False)
                        set_footer(embed)
                        await thread.send(embed=embed)
            except Exception:
                pass

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

    def __init__(self, user_id: int, guild_id: int):
        super().__init__(
            discord.ui.Button(
                label="Unmute",
                style=discord.ButtonStyle.success,
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
        user_id = int(match.group("user_id"))
        guild_id = int(match.group("guild_id"))
        return cls(user_id, guild_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        db = get_db()

        if not db.is_user_muted(self.user_id, self.guild_id):
            await interaction.response.send_message(
                "This user is not currently muted.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(UnmuteModal(self.user_id, self.guild_id))


# =============================================================================
# Notes Button + Modal
# =============================================================================

class NoteModal(discord.ui.Modal, title="Add Moderator Note"):
    """Modal for adding a moderator note."""

    note = discord.ui.TextInput(
        label="Note",
        placeholder="Enter your note about this user...",
        required=True,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, user_id: int, guild_id: int):
        super().__init__()
        self.user_id = user_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        db = get_db()

        # Save the note
        db.save_mod_note(
            user_id=self.user_id,
            guild_id=self.guild_id,
            moderator_id=interaction.user.id,
            note=self.note.value,
        )

        await interaction.response.send_message(
            "Note saved successfully.",
            ephemeral=True,
        )

        # Log to case thread
        try:
            case_log = db.get_case_log(self.user_id)
            if case_log and interaction.guild:
                thread = interaction.guild.get_thread(case_log["thread_id"])
                if thread:
                    embed = discord.Embed(
                        title="📝 Note Added",
                        color=EmbedColors.INFO,
                    )
                    embed.add_field(
                        name="Added By",
                        value=f"{interaction.user.mention}\n`{interaction.user.name}`",
                        inline=True,
                    )
                    embed.add_field(name="Note", value=self.note.value, inline=False)
                    set_footer(embed)
                    await thread.send(embed=embed)
        except Exception:
            pass


class NotesButton(discord.ui.DynamicItem[discord.ui.Button], template=r"mod_notes:(?P<user_id>\d+):(?P<guild_id>\d+)"):
    """
    Persistent notes button that shows existing notes and allows adding new ones.
    """

    def __init__(self, user_id: int, guild_id: int):
        super().__init__(
            discord.ui.Button(
                label="Notes",
                style=discord.ButtonStyle.secondary,
                emoji=NOTE_EMOJI,
                custom_id=f"mod_notes:{user_id}:{guild_id}",
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
    ) -> "NotesButton":
        user_id = int(match.group("user_id"))
        guild_id = int(match.group("guild_id"))
        return cls(user_id, guild_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        db = get_db()

        # Get existing notes
        notes = db.get_mod_notes(self.user_id, self.guild_id, limit=10)
        note_count = db.get_note_count(self.user_id, self.guild_id)

        # Build notes embed
        embed = discord.Embed(
            title="📝 Moderator Notes",
            color=EmbedColors.INFO,
        )

        try:
            user = await interaction.client.fetch_user(self.user_id)
            embed.set_author(name=user.name, icon_url=user.display_avatar.url)
        except Exception:
            pass

        if notes:
            for note in notes:
                mod_id = note.get("moderator_id")
                created_at = note.get("created_at", 0)
                note_text = note.get("note", "")

                embed.add_field(
                    name=f"<t:{int(created_at)}:R> by <@{mod_id}>",
                    value=note_text[:200] + ("..." if len(note_text) > 200 else ""),
                    inline=False,
                )

            if note_count > 10:
                embed.set_footer(text=f"Showing 10 of {note_count} notes")
        else:
            embed.description = "No notes have been added for this user yet."

        # Create view with Add Note button
        view = NotesDisplayView(self.user_id, self.guild_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class NotesDisplayView(discord.ui.View):
    """View for displaying notes with an Add Note button."""

    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.guild_id = guild_id

    @discord.ui.button(label="Add Note", style=discord.ButtonStyle.primary, emoji=NOTE_EMOJI)
    async def add_note_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NoteModal(self.user_id, self.guild_id))


# =============================================================================
# Case Button View
# =============================================================================

class CaseButtonView(discord.ui.View):
    """View with Case link, Info, and History buttons for public response."""

    def __init__(self, guild_id: int, thread_id: int, user_id: int):
        super().__init__(timeout=None)

        # Case link button
        url = f"https://discord.com/channels/{guild_id}/{thread_id}"
        self.add_item(discord.ui.Button(
            label="Case",
            url=url,
            style=discord.ButtonStyle.link,
            emoji=CASE_EMOJI,
        ))

        # Info button (persistent)
        self.add_item(InfoButton(user_id, guild_id))

        # History button (persistent)
        self.add_item(HistoryButton(user_id, guild_id))


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
        ExtendButton,
        UnmuteButton,
        NotesButton,
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
    "NOTE_EMOJI",
    "InfoButton",
    "DownloadButton",
    "HistoryButton",
    "ExtendButton",
    "UnmuteButton",
    "NotesButton",
    "CaseButtonView",
    "MessageButtonView",
    "setup_moderation_views",
]
