"""
Server Logs - Boosts Handler
============================

Handles server boost logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors

if TYPE_CHECKING:
    from ..service import LoggingService


class BoostsLogsMixin:
    """Mixin for server boost logging."""

    async def log_boost(
        self: "LoggingService",
        member: discord.Member,
    ) -> None:
        """Log a member boosting the server."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import MESSAGE_EMOJI

        embed = self._create_embed("💎 Server Boosted", EmbedColors.SUCCESS, category="Boost", user_id=member.id)
        embed.add_field(name="Booster", value=self._format_user_field(member), inline=True)

        if member.guild:
            embed.add_field(
                name="Server Boosts",
                value=f"**{member.guild.premium_subscription_count}** boosts",
                inline=True,
            )
            embed.add_field(
                name="Boost Level",
                value=f"Level **{member.guild.premium_tier}**",
                inline=True,
            )

        self._set_user_thumbnail(embed, member)

        # Try to find the boost announcement message in main server's system channel
        view = None
        main_guild = self.bot.get_guild(self.config.main_guild_id) if self.config.main_guild_id else member.guild
        if main_guild and main_guild.system_channel:
            try:
                async for msg in main_guild.system_channel.history(limit=10):
                    if msg.type == discord.MessageType.premium_guild_subscription and msg.author.id == member.id:
                        view = discord.ui.View(timeout=None)
                        view.add_item(discord.ui.Button(
                            label="Message",
                            url=msg.jump_url,
                            style=discord.ButtonStyle.link,
                            emoji=MESSAGE_EMOJI,
                        ))
                        break
            except Exception:
                pass

        await self._send_log(LogCategory.BOOSTS, embed, view=view, user_id=member.id)

    async def log_unboost(
        self: "LoggingService",
        member: discord.Member,
        boosted_since: Optional[datetime] = None,
    ) -> None:
        """Log a member removing their server boost."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("💔 Boost Removed", EmbedColors.LOG_NEGATIVE, category="Unboost", user_id=member.id)
        embed.add_field(name="Former Booster", value=self._format_user_field(member), inline=True)

        if member.guild:
            embed.add_field(
                name="Server Boosts",
                value=f"**{member.guild.premium_subscription_count}** boosts",
                inline=True,
            )
            embed.add_field(
                name="Boost Level",
                value=f"Level **{member.guild.premium_tier}**",
                inline=True,
            )

        if boosted_since:
            now = datetime.now(boosted_since.tzinfo) if boosted_since.tzinfo else datetime.utcnow()
            duration = now - boosted_since
            days = duration.days

            if days >= 365:
                years = days // 365
                remaining_days = days % 365
                duration_str = f"{years}y {remaining_days}d"
            elif days >= 30:
                months = days // 30
                remaining_days = days % 30
                duration_str = f"{months}mo {remaining_days}d"
            else:
                duration_str = f"{days}d"

            embed.add_field(
                name="Boosted For",
                value=f"**{duration_str}** (since <t:{int(boosted_since.timestamp())}:D>)",
                inline=False,
            )

            if days in (30, 31, 365, 366):
                embed.add_field(
                    name="Note",
                    value="⚠️ Duration suggests subscription expiry",
                    inline=False,
                )

        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.BOOSTS, embed, user_id=member.id)


__all__ = ["BoostsLogsMixin"]
