"""
AzabBot - Link Command Cog
==========================

Links alliance channel messages to members for auto-deletion on leave.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING

from src.commands.link.cog import LinkCog
from src.commands.link.views import LinkApproveButton, LinkDenyButton

if TYPE_CHECKING:
    from src.bot import AzabBot


async def setup(bot: "AzabBot") -> None:
    """Load the Link cog."""
    bot.add_dynamic_items(LinkApproveButton, LinkDenyButton)
    await bot.add_cog(LinkCog(bot))


__all__ = ["LinkCog", "setup"]
