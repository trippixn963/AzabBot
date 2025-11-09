"""
Azab Discord Bot - Handlers Package
===================================

Event and message handlers for the Discord bot.
Specialized handlers manage different aspects of bot functionality.

Available Handlers:
- PrisonHandler: Manages prisoner welcome and release messages
- MuteHandler: Processes mute embeds and extracts reasons from logs
- PresenceHandler: Manages dynamic Discord rich presence updates

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .prison_handler import PrisonHandler
from .mute_handler import MuteHandler
from .presence_handler import PresenceHandler

__all__ = ['PrisonHandler', 'MuteHandler', 'PresenceHandler']