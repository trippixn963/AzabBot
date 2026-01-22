"""
Azab Discord Bot - Ban Package
===============================

Server moderation ban/unban commands with case logging.

Structure:
    - views.py: BanModal for context menu banning
    - autocomplete.py: Autocomplete functions for reasons and banned users
    - ban_ops.py: Ban execution logic and context menu handlers
    - unban_ops.py: Unban command logic
    - cog.py: Main BanCog class with commands

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .views import BanModal
from .cog import BanCog

__all__ = [
    "BanModal",
    "BanCog",
]


async def setup(bot) -> None:
    """Load the BanCog."""
    await bot.add_cog(BanCog(bot))
