"""
Ticket Buttons - Info Button
============================

Button for viewing user info and criminal history.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors
from src.utils.footer import set_footer
from src.views import build_history_embed, build_history_view
from ..constants import INFO_EMOJI

if TYPE_CHECKING:
    from src.bot import AzabBot


class InfoButton(discord.ui.DynamicItem[discord.ui.Button], template=r"tkt_info:(?P<ticket_id>T\d+)"):
    """Button to view user info and criminal history via dropdown."""

    def __init__(self, ticket_id: str):
        self.ticket_id = ticket_id
        super().__init__(
            discord.ui.Button(
                label="Info",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tkt_info:{ticket_id}",
                emoji=INFO_EMOJI,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "InfoButton":
        return cls(match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction) -> None:
        logger.tree("Ticket Info Button Clicked", [
            ("Staff", f"{interaction.user.name} ({interaction.user.id})"),
            ("Ticket ID", self.ticket_id),
        ], emoji="ℹ️")

        bot: "AzabBot" = interaction.client
        if not hasattr(bot, "ticket_service") or not bot.ticket_service:
            await interaction.response.send_message(
                "Ticket system is not available.",
                ephemeral=True,
            )
            return

        ticket = bot.ticket_service.db.get_ticket(self.ticket_id)
        if not ticket:
            await interaction.response.send_message(
                "Ticket not found.",
                ephemeral=True,
            )
            return

        # Show dropdown to select info type
        view = InfoSelectView(
            ticket_id=self.ticket_id,
            user_id=ticket["user_id"],
            guild_id=ticket.get("guild_id", interaction.guild.id),
        )
        await interaction.response.send_message(
            "Select information to view:",
            view=view,
            ephemeral=True,
        )


class InfoSelectView(discord.ui.View):
    """View with dropdown for selecting User Info or Criminal History."""

    def __init__(self, ticket_id: str, user_id: int, guild_id: int):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id
        self.user_id = user_id
        self.guild_id = guild_id
        # Cache to avoid duplicate queries
        self._user_cache: Optional[discord.User] = None
        self._cases_cache: Optional[list] = None
        self._tickets_cache: Optional[list] = None

    @discord.ui.select(
        placeholder="Choose info type...",
        options=[
            discord.SelectOption(
                label="User Info",
                value="user_info",
                description="Account age, join date, ticket stats",
                emoji="👤",
            ),
            discord.SelectOption(
                label="Criminal History",
                value="criminal_history",
                description="Warns, mutes, bans with details",
                emoji="⚠️",
            ),
        ],
    )
    async def info_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        bot: "AzabBot" = interaction.client
        await interaction.response.defer(ephemeral=True)

        try:
            choice = select.values[0]

            if choice == "user_info":
                embed = await self._build_user_info_embed(bot, interaction.guild)
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                embed, cases = await self._build_criminal_history_embed(bot)
                view = build_history_view(cases, self.guild_id)
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            logger.error("Info Select Failed", [
                ("Ticket", self.ticket_id),
                ("User ID", str(self.user_id)),
                ("Choice", select.values[0] if select.values else "none"),
                ("Error", str(e)[:100]),
            ])
            await interaction.followup.send(
                f"Failed to load information: {str(e)[:100]}",
                ephemeral=True,
            )
        # Don't stop the view - allow multiple selections until timeout

    async def _build_user_info_embed(
        self,
        bot: "AzabBot",
        guild: discord.Guild,
    ) -> discord.Embed:
        """Build user info embed with account age, join date, etc."""
        # Fetch user (use cache if available)
        if self._user_cache is None:
            try:
                self._user_cache = await bot.fetch_user(self.user_id)
            except Exception:
                pass
        user = self._user_cache

        # Get member for join date
        member = guild.get_member(self.user_id) if guild else None

        embed = discord.Embed(
            title="👤 User Information",
            color=EmbedColors.GREEN,
        )

        if user:
            embed.set_thumbnail(url=user.display_avatar.url)

            # Username
            embed.add_field(
                name="User",
                value=f"{user.mention}\n`{user.name}`",
                inline=True,
            )

            # User ID
            embed.add_field(
                name="ID",
                value=f"`{user.id}`",
                inline=True,
            )

            # Account Created
            created_at = user.created_at
            now = datetime.now(timezone.utc)
            age_days = (now - created_at).days

            if age_days < 30:
                age_str = f"{age_days} day{'s' if age_days != 1 else ''}"
            elif age_days < 365:
                months = age_days // 30
                age_str = f"{months} month{'s' if months != 1 else ''}"
            else:
                years = age_days // 365
                remaining_months = (age_days % 365) // 30
                if remaining_months > 0:
                    age_str = f"{years}y {remaining_months}mo"
                else:
                    age_str = f"{years} year{'s' if years != 1 else ''}"

            embed.add_field(
                name="Account Age",
                value=f"**{age_str}**\n<t:{int(created_at.timestamp())}:D>",
                inline=True,
            )
        else:
            embed.add_field(
                name="User",
                value=f"<@{self.user_id}>",
                inline=True,
            )

        # Server Join Date (if member is in guild)
        if member and member.joined_at:
            join_days = (datetime.now(timezone.utc) - member.joined_at).days
            embed.add_field(
                name="Joined Server",
                value=f"<t:{int(member.joined_at.timestamp())}:D>\n({join_days} days ago)",
                inline=True,
            )
        else:
            embed.add_field(
                name="Joined Server",
                value="Not in server",
                inline=True,
            )

        # Ticket Stats (use cache if available)
        if self._tickets_cache is None:
            self._tickets_cache = bot.ticket_service.db.get_user_tickets(self.user_id, self.guild_id) or []
        ticket_history = self._tickets_cache
        if ticket_history:
            total = len(ticket_history)
            open_count = sum(1 for t in ticket_history if t["status"] == "open")
            claimed_count = sum(1 for t in ticket_history if t["status"] == "claimed")
            closed_count = sum(1 for t in ticket_history if t["status"] == "closed")
            embed.add_field(
                name="Ticket Stats",
                value=(
                    f"🎫 **{total}** total\n"
                    f"🟢 {open_count} open │ 🔵 {claimed_count} claimed │ 🔴 {closed_count} closed"
                ),
                inline=True,
            )
        else:
            embed.add_field(
                name="Ticket Stats",
                value="No previous tickets",
                inline=True,
            )

        # Mod Stats Summary (use cache if available)
        if self._cases_cache is None:
            self._cases_cache = bot.ticket_service.db.get_user_cases(self.user_id, self.guild_id, limit=100) or []
        cases = self._cases_cache
        if cases:
            warns = sum(1 for c in cases if c.get("action_type") == "warn")
            mutes = sum(1 for c in cases if c.get("action_type") == "mute")
            bans = sum(1 for c in cases if c.get("action_type") == "ban")
            embed.add_field(
                name="Mod Record",
                value=f"⚠️ {warns} warns │ 🔇 {mutes} mutes │ 🔨 {bans} bans",
                inline=False,
            )
        else:
            embed.add_field(
                name="Mod Record",
                value="✅ Clean record",
                inline=False,
            )

        set_footer(embed)
        return embed

    async def _build_criminal_history_embed(self, bot: "AzabBot") -> tuple:
        """Build criminal history embed using shared unified format.

        Returns:
            Tuple of (embed, cases) for building the view with case links.
        """
        # Get all cases (use cache if available)
        if self._cases_cache is None:
            self._cases_cache = bot.ticket_service.db.get_user_cases(self.user_id, self.guild_id, limit=100) or []
        cases = self._cases_cache[:10]  # Show 10 in criminal history

        # Use the shared history embed builder for unified format
        embed = await build_history_embed(
            client=bot,
            user_id=self.user_id,
            guild_id=self.guild_id,
            cases=cases,
        )
        return embed, cases


__all__ = [
    "InfoButton",
    "InfoSelectView",
]
