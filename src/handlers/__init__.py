"""
Azab Discord Bot - Handlers Package
===================================

Event and message handlers for the Discord bot.

Available handlers:
- PrisonHandler: Manages prisoner welcome and release
- MuteHandler: Processes mute embeds and extracts reasons
- PresenceHandler: Manages dynamic Discord rich presence
"""

from .prison_handler import PrisonHandler
from .mute_handler import MuteHandler
from .presence_handler import PresenceHandler

__all__ = ['PrisonHandler', 'MuteHandler', 'PresenceHandler']