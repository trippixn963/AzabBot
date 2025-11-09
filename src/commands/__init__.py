"""
Azab Discord Bot - Commands Package
==================================

Slash command implementations for the Azab Discord bot.
This package contains all Discord slash commands organized
in separate modules for maintainability.

Available Commands:
- /activate: Activate bot's ragebaiting mode (admin only)
- /deactivate: Deactivate bot and return to standby (admin only)
- /ignore: Ignore or unignore specific users (admin only)

Each command is implemented as a separate class with proper
Discord.py slash command integration.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .activate import ActivateCommand
from .deactivate import DeactivateCommand
from .ignore import IgnoreCommand

__all__ = ['ActivateCommand', 'DeactivateCommand', 'IgnoreCommand']