"""
Azab Discord Bot - Utils Package
================================

Utility modules for the Azab Discord bot.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .version import Version, get_version_string, get_version_info
from .time_format import format_duration

__all__ = ['Version', 'get_version_string', 'get_version_info', 'format_duration']