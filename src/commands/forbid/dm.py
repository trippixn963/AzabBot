"""
AzabBot - DM Mixin
==================

DM notification methods for forbid/unforbid actions.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.utils.dm_helpers import safe_send_dm

from .constants import RESTRICTIONS
from .views import ForbidAppealView

if TYPE_CHECKING:
    from src.commands.forbid.cog import ForbidCog


class DMMixin:
    """Mixin for forbid DM notifications."""

    async def _send_forbid_dm(
        self: "ForbidCog",
        user: discord.Member,
        restrictions: List[str],
        duration_display: str,
        reason: Optional[str],
        guild: discord.Guild,
    ) -> bool:
        """Send DM notification to user when forbidden. Returns True if sent successfully."""
        # Build restrictions list
        restrictions_text = "\n".join([
            f"{RESTRICTIONS[r]['emoji']} **{RESTRICTIONS[r]['display']}** - {RESTRICTIONS[r]['description']}"
            for r in restrictions if r in RESTRICTIONS
        ])

        embed = discord.Embed(
            title="🚫 You've Been Restricted",
            description=f"A moderator has applied restrictions to your account in **{guild.name}**.",
            color=EmbedColors.GOLD,
            timestamp=datetime.now(NY_TZ),
        )

        embed.add_field(
            name="Restrictions Applied",
            value=restrictions_text,
            inline=False,
        )

        embed.add_field(name="Duration", value=duration_display, inline=True)

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        embed.add_field(
            name="What This Means",
            value="These restrictions limit specific features. You can still participate in the server otherwise.",
            inline=False,
        )

        # Add appeal information
        embed.add_field(
            name="Want to Appeal?",
            value="If you believe this was a mistake, you can appeal using the button below or by contacting a moderator.",
            inline=False,
        )

        # Create appeal button view
        view = ForbidAppealView(guild.id, user.id)

        result = await safe_send_dm(user, embed=embed, view=view, context="Forbid DM")

        if result:
            logger.tree("Forbid DM Sent", [
                ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                ("ID", str(user.id)),
                ("Restrictions", ", ".join(restrictions)),
                ("Duration", duration_display),
            ], emoji="📨")
        else:
            logger.warning("Forbid DM Failed", [
                ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                ("ID", str(user.id)),
                ("Reason", "DMs disabled or blocked"),
            ])

        return result

    async def _send_unforbid_dm(
        self: "ForbidCog",
        user: discord.Member,
        restrictions: List[str],
        guild: discord.Guild,
    ) -> bool:
        """Send DM notification to user when restrictions are removed. Returns True if sent successfully."""
        # Build restrictions list
        restrictions_text = "\n".join([
            f"{RESTRICTIONS[r]['emoji']} **{RESTRICTIONS[r]['display']}**"
            for r in restrictions if r in RESTRICTIONS
        ])

        embed = discord.Embed(
            title="Restrictions Removed",
            description=f"Your restrictions in **{guild.name}** have been lifted.",
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ),
        )

        embed.add_field(
            name="Removed Restrictions",
            value=restrictions_text,
            inline=False,
        )

        embed.add_field(
            name="What This Means",
            value="You now have full access to these features again.",
            inline=False,
        )

        result = await safe_send_dm(user, embed=embed, context="Unforbid DM")

        if result:
            logger.tree("Unforbid DM Sent", [
                ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                ("ID", str(user.id)),
                ("Restrictions Removed", ", ".join(restrictions)),
            ], emoji="📨")
        else:
            logger.warning("Unforbid DM Failed", [
                ("User", f"{user.name} ({user.nick})" if hasattr(user, 'nick') and user.nick else user.name),
                ("ID", str(user.id)),
                ("Reason", "DMs disabled or blocked"),
            ])

        return result


__all__ = ["DMMixin"]
