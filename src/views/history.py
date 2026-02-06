"""
AzabBot - History Button Views
==============================

Buttons for viewing paginated moderation history.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import re
from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import get_config, EmbedColors
from src.core.database import get_db
from src.core.logger import logger
from src.core.constants import WARNING_DECAY_DAYS, SECONDS_PER_DAY, SECONDS_PER_HOUR, QUERY_LIMIT_SMALL, QUERY_LIMIT_TINY
from src.utils.discord_rate_limit import log_http_error

from .constants import HISTORY_EMOJI

if TYPE_CHECKING:
    from src.bot import AzabBot


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
        """Show simple case list with Discord and website links."""
        logger.tree("History Button Clicked", [
            ("Clicked By", f"{interaction.user} ({interaction.user.id})"),
            ("Target User ID", str(self.user_id)),
            ("Guild ID", str(self.guild_id)),
        ], emoji="📜")

        try:
            db = get_db()
            config = get_config()

            # Get cases for this user
            cases = db.get_user_cases(self.user_id, self.guild_id, limit=QUERY_LIMIT_SMALL, include_resolved=True)

            if not cases:
                await interaction.response.send_message(
                    "No moderation history found for this user.",
                    ephemeral=True,
                )
                return

            # Build simple list with links
            lines = []
            action_emoji = {
                "mute": "🔇", "ban": "🔨", "warn": "⚠️", "forbid": "🚫",
                "timeout": "⏰", "unmute": "🔊", "unban": "✅", "unforbid": "✅",
            }

            for case in cases:
                case_id = case.get("case_id", "????")
                action_type = case.get("action_type", "?")
                thread_id = case.get("thread_id")
                status = case.get("status", "open")
                emoji = action_emoji.get(action_type, "📋")
                status_indicator = "🟢" if status == "open" else "⚫"

                # Build links
                links = []

                # Discord link - only show if NOT archived (thread still exists)
                if thread_id and config.logging_guild_id and status != "archived":
                    discord_url = f"https://discord.com/channels/{config.logging_guild_id}/{thread_id}"
                    links.append(f"[Discord]({discord_url})")

                # Website link - only show for archived cases (transcript saved after thread deleted)
                if status == "archived" and config.case_transcript_base_url:
                    website_url = f"{config.case_transcript_base_url}/{case_id}"
                    links.append(f"[Website]({website_url})")

                link_str = " • ".join(links) if links else "No links"
                lines.append(f"{status_indicator} {emoji} `{case_id}` — {link_str}")

            # Get username for title
            username = "Unknown"
            try:
                user = await interaction.client.fetch_user(self.user_id)
                username = user.name
            except discord.NotFound:
                pass
            except discord.HTTPException:
                pass

            embed = discord.Embed(
                title=f"Case History — {username}",
                description="\n".join(lines),
                color=EmbedColors.INFO,
            )
            embed.set_footer(text=f"{len(cases)} cases")

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except discord.HTTPException as e:
            log_http_error(e, "History Button", [
                ("User ID", str(self.user_id)),
            ])
            try:
                await interaction.response.send_message(
                    "Failed to fetch history. Please try again.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass
        except Exception as e:
            logger.error("History Button Failed", [
                ("User ID", str(self.user_id)),
                ("Error", str(e)[:100]),
                ("Type", type(e).__name__),
            ])
            try:
                await interaction.response.send_message(
                    "An error occurred while fetching history.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass

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
        total_pages = (total + QUERY_LIMIT_TINY - 1) // QUERY_LIMIT_TINY  # Ceiling division
        embed.set_footer(text=f"Page {page + 1}/{total_pages} • {total} total records")

        return embed


class PaginationPrevButton(discord.ui.DynamicItem[discord.ui.Button], template=r"hist_prev:(?P<user_id>\d+):(?P<guild_id>\d+):(?P<page>\d+):(?P<total>\d+)"):
    """Persistent Previous button for pagination."""

    def __init__(self, user_id: int, guild_id: int, page: int, total: int):
        total_pages = (total + QUERY_LIMIT_TINY - 1) // QUERY_LIMIT_TINY
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
        total_pages = (total + QUERY_LIMIT_TINY - 1) // QUERY_LIMIT_TINY
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
        self.total_pages = (total + QUERY_LIMIT_TINY - 1) // QUERY_LIMIT_TINY

        # Add persistent pagination buttons
        self.add_item(PaginationPrevButton(user_id, guild_id, page, total))
        self.add_item(PaginationNextButton(user_id, guild_id, page, total))

    async def _build_embed(self, client) -> discord.Embed:
        db = get_db()
        history = db.get_combined_history(self.user_id, self.guild_id, limit=QUERY_LIMIT_TINY, offset=self.page * QUERY_LIMIT_TINY)

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


__all__ = [
    "build_history_embed",
    "build_history_view",
    "HistoryButton",
    "PaginationPrevButton",
    "PaginationNextButton",
    "HistoryPaginationView",
]
