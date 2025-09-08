"""
Azab Discord Bot - Commands Package
==================================

Slash command implementations for the Azab Discord bot.
This package contains all Discord slash commands organized
in separate modules for maintainability.

Available Commands:
- /activate: Activate bot's ragebaiting mode
- /deactivate: Deactivate bot and return to standby
- /credits: View bot credits and information

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: v2.2.0
"""

from .activate import ActivateCommand
from .deactivate import DeactivateCommand
from .credits import CreditsCommand

__all__ = ['ActivateCommand', 'DeactivateCommand', 'CreditsCommand']