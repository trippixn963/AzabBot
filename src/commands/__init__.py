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
    /mute: Mute a user by assigning the muted role (moderator)
    /unmute: Unmute a user by removing the muted role (moderator)
    /ban: Ban a user from the server (moderator)
    /unban: Unban a user by ID (moderator)
    /warn: Issue a warning to a user (moderator)
    /purge: Bulk delete messages from channel (moderator)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# =============================================================================
# Command Cog Registry
# =============================================================================

COMMAND_COGS = [
    "src.commands.mute",
    "src.commands.ban",
    "src.commands.warn",
    "src.commands.purge",
    "src.commands.lockdown",
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
