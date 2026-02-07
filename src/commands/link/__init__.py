"""
AzabBot - Link Command Package
==============================

Links alliance channel messages to members for auto-deletion on leave.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from .cog import LinkCog
from .views import LinkApproveButton, LinkDenyButton, LinkConfirmView

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Load the Link cog."""
    bot.add_dynamic_items(LinkApproveButton, LinkDenyButton)
    await bot.add_cog(LinkCog(bot))


__all__ = ["LinkCog", "LinkApproveButton", "LinkDenyButton", "LinkConfirmView", "setup"]
