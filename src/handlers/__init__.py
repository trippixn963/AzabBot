"""
Azab Discord Bot - Handlers Package
===================================

Event and message handlers for the Discord bot.
Specialized handlers manage different aspects of bot functionality.

DESIGN:
    Handlers are instantiated by the bot and receive references
    to other components they need. They process Discord events
    and coordinate between services.

    To add a new handler:
    1. Create new_handler.py in this directory
    2. Follow the existing handler pattern (class with bot reference)
    3. Add import and export below
    4. Initialize in bot.py's setup_hook()

Available Handlers:
    PrisonHandler: Manages prisoner welcome, roasting, and release
    MuteHandler: Processes mute embeds and extracts reasons from logs
    PresenceHandler: Manages dynamic Discord rich presence updates

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# =============================================================================
# Handler Imports
# =============================================================================

from .prison_handler import PrisonHandler
from .mute_handler import MuteHandler
from .presence_handler import PresenceHandler


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "PrisonHandler",
    "MuteHandler",
    "PresenceHandler",
]
