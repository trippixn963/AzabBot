"""
AzabBot - Handlers Package
==========================

Event and message handlers for the Discord bot.
Specialized handlers manage different aspects of bot functionality.

DESIGN:
    Handlers are instantiated by the bot and receive references
    to other components they need. They process Discord events
    and coordinate between services.

    Event Cogs are loaded dynamically by the bot using load_extension().
    - messages/: Message create/delete/edit
    - members.py: Member join/leave/update
    - channels.py: Channel/thread/role/emoji events
    - audit_log/: Audit log routing to mod_tracker and logging_service

    To add a new handler:
    1. Create new_handler.py in this directory
    2. Follow the existing handler pattern (class with bot reference)
    3. Add import and export below
    4. Initialize in bot.py's setup_hook()

Available Handlers:
    PrisonHandler: Manages prisoner welcome and release notifications
    MuteHandler: Processes mute embeds and extracts reasons from logs

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# =============================================================================
# Event Cog Registry
# =============================================================================

EVENT_COGS = [
    "src.handlers.messages",
    "src.handlers.members",
    "src.handlers.channels",
    "src.handlers.audit_log",
]
"""
List of event cog module paths for dynamic loading.

DESIGN:
    Bot iterates this list and calls load_extension() for each.
    Add new event cogs here to have them loaded automatically.
"""

# =============================================================================
# Handler Imports
# =============================================================================

from .prison import PrisonHandler
from .voice import VoiceHandler
from .mute import MuteHandler


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "EVENT_COGS",
    "PrisonHandler",
    "VoiceHandler",
    "MuteHandler",
]
