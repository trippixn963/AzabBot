"""
Azab Discord Bot - Commands Package
==================================

Slash command implementations for the Azab Discord bot.
Commands are implemented as discord.py Cogs for modularity.

DESIGN:
    Each command file contains a Cog class with related commands.
    Cogs are loaded dynamically by the bot using load_extension().

    To add a new command:
    1. Create new_command.py in this directory
    2. Create a Cog class with @app_commands.command decorators
    3. Add async def setup(bot) function at the end
    4. Add the cog to COMMAND_COGS list below
    5. Bot will auto-load it on startup

Available Commands:
    /activate: Activate bot's ragebaiting mode (developer only)
    /deactivate: Deactivate bot and return to standby (developer only)
    /ignore: Ignore or unignore specific users (developer only)
    /mute: Mute a user by assigning the muted role (moderator)
    /unmute: Unmute a user by removing the muted role (moderator)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# =============================================================================
# Command Cog Registry
# =============================================================================

COMMAND_COGS = [
    "src.commands.toggle",
    "src.commands.ignore",
    "src.commands.mute",
]
"""
List of command cog module paths for dynamic loading.

DESIGN:
    Bot iterates this list and calls load_extension() for each.
    Add new command cogs here to have them loaded automatically.
"""


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "COMMAND_COGS",
]
