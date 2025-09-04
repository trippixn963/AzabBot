"""
Azab Discord Bot - Handlers Package
===================================

Event and message handlers for the Azab Discord bot.
This package contains specialized handlers for processing
Discord events and managing bot interactions.

Available Handlers:
- PrisonHandler: Manages prisoner welcome and release messages
- MuteHandler: Processes mute embeds and extracts reasons

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: Modular
"""

from .prison_handler import PrisonHandler
from .mute_handler import MuteHandler

__all__ = ['PrisonHandler', 'MuteHandler']