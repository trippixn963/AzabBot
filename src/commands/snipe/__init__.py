"""
Azab Discord Bot - Snipe Package
================================

View deleted and edited messages in a channel.

Structure:
    - helpers.py: Server logging helper methods
    - snipe_cmd.py: /snipe command implementation
    - editsnipe_cmd.py: /editsnipe command implementation
    - clearsnipe_cmd.py: /clearsnipe command implementation
    - cog.py: Main SnipeCog class

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .cog import SnipeCog

__all__ = ["SnipeCog"]


async def setup(bot) -> None:
    """Load the SnipeCog."""
    await bot.add_cog(SnipeCog(bot))
