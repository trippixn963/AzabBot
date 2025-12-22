"""
Azab Discord Bot - Events Package
=================================

Event handler Cogs for the Azab Discord bot.
Events are organized into Cogs by category for maintainability.

DESIGN:
    Each event file contains a Cog class with @commands.Cog.listener decorators.
    Cogs are loaded dynamically by the bot using load_extension().

    Event routing:
    - messages.py: Message create/delete/edit
    - members.py: Member join/leave/update
    - channels.py: Channel/thread/role/emoji events
    - audit_log.py: Audit log routing to mod_tracker and logging_service

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# =============================================================================
# Event Cog Registry
# =============================================================================

EVENT_COGS = [
    "src.events.messages",
    "src.events.members",
    "src.events.channels",
    "src.events.audit_log",
]
"""
List of event cog module paths for dynamic loading.

DESIGN:
    Bot iterates this list and calls load_extension() for each.
    Add new event cogs here to have them loaded automatically.
"""


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "EVENT_COGS",
]
