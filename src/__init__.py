"""
Azab Discord Bot - Source Package
=================================

The main source package for the Azab Discord bot, built specifically
for discord.gg/syria. This package contains all core bot functionality
organized in a modular architecture.

DESIGN:
    The package follows a layered architecture:
    - core/: Foundation services (config, database, logging, health)
    - handlers/: Discord event handlers (prison, mute, presence)
    - services/: External integrations (tickets, appeals, etc.)
    - commands/: Slash command implementations (as cogs)
    - utils/: Helper functions and utilities

    New features should be added to the appropriate layer:
    - New event handlers → handlers/
    - New slash commands → commands/
    - New API integrations → services/
    - New helper functions → utils/
    - Core infrastructure → core/

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# =============================================================================
# Package Version
# =============================================================================

__version__ = "2.0.0"
__author__ = "حَـــــنَّـــــا"


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "__version__",
    "__author__",
]
