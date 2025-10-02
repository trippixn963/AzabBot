"""
Azab Discord Bot - Commands Package
==================================

Slash command implementations for the Azab Discord bot.
This package contains all Discord slash commands organized
in separate modules for maintainability.

Available Commands:
- /activate: Activate bot's ragebaiting mode (admin only)
- /deactivate: Deactivate bot and return to standby (admin only)

Each command is implemented as a separate class with proper
Discord.py slash command integration.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: v2.3.0
"""

from .activate import ActivateCommand
from .deactivate import DeactivateCommand

__all__ = ['ActivateCommand', 'DeactivateCommand']