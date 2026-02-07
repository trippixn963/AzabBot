"""
AzabBot - Lockdown Lock Operations
==================================

Channel locking operations for the lockdown command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, List, Optional, Tuple

import discord

from src.core.logger import logger
from src.utils.async_utils import create_safe_task
from src.utils.discord_rate_limit import log_http_error

from .constants import MAX_CONCURRENT_OPS, LockdownResult

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


async def lock_text_channel(
    channel: discord.TextChannel,
    everyone_role: discord.Role,
    mod_role: Optional[discord.Role],
    reason: str,
    db: "DatabaseManager",
) -> Tuple[bool, Optional[str]]:
    """
    Lock a single text channel.

    Args:
        channel: The text channel to lock.
        everyone_role: The @everyone role.
        mod_role: The moderation role (or None).
        reason: Audit log reason.
        db: Database manager for saving permissions.

    Returns:
        Tuple of (success, error_message).
    """
    try:
        # Get current @everyone overwrite for this channel
        current_overwrite: discord.PermissionOverwrite = channel.overwrites_for(everyone_role)

        # Save original permission state
        db.save_channel_permission(
            guild_id=channel.guild.id,
            channel_id=channel.id,
            channel_type="text",
            send_messages=current_overwrite.send_messages,
            connect=None,
        )

        # Set overwrite to deny messaging permissions
        current_overwrite.send_messages = False
        current_overwrite.add_reactions = False
        current_overwrite.create_public_threads = False
        current_overwrite.create_private_threads = False
        current_overwrite.send_messages_in_threads = False

        await channel.set_permissions(
            everyone_role,
            overwrite=current_overwrite,
            reason=reason,
        )

        # Give mod role explicit allow so they can still communicate
        if mod_role:
            mod_overwrite: discord.PermissionOverwrite = channel.overwrites_for(mod_role)
            mod_overwrite.send_messages = True
            mod_overwrite.add_reactions = True
            await channel.set_permissions(
                mod_role,
                overwrite=mod_overwrite,
                reason=f"{reason} (mod access)",
            )

        logger.debug("Channel Locked", [
            ("Channel", f"#{channel.name}"),
            ("ID", str(channel.id)),
            ("Type", "text"),
            ("Mod Access", "yes" if mod_role else "no"),
        ])

        return True, None

    except discord.Forbidden as e:
        error_msg = f"#{channel.name}: Missing permissions"
        logger.warning("Channel Lock Failed", [
            ("Channel", f"#{channel.name} ({channel.id})"),
            ("Error", "Forbidden - missing permissions"),
        ])
        return False, error_msg

    except discord.HTTPException as e:
        error_msg = f"#{channel.name}: {e.text[:50] if e.text else 'HTTP error'}"
        log_http_error(e, "Channel Lock", [
            ("Channel", f"#{channel.name} ({channel.id})"),
        ])
        return False, error_msg

    except Exception as e:
        error_msg = f"#{channel.name}: {str(e)[:50]}"
        logger.error("Channel Lock Error", [
            ("Channel", f"#{channel.name} ({channel.id})"),
            ("Error", str(e)[:100]),
            ("Type", type(e).__name__),
        ])
        return False, error_msg


async def lock_voice_channel(
    channel: discord.VoiceChannel,
    everyone_role: discord.Role,
    mod_role: Optional[discord.Role],
    reason: str,
    db: "DatabaseManager",
) -> Tuple[bool, Optional[str]]:
    """
    Lock a single voice channel.

    Args:
        channel: The voice channel to lock.
        everyone_role: The @everyone role.
        mod_role: The moderation role (or None).
        reason: Audit log reason.
        db: Database manager for saving permissions.

    Returns:
        Tuple of (success, error_message).
    """
    try:
        current_overwrite: discord.PermissionOverwrite = channel.overwrites_for(everyone_role)

        db.save_channel_permission(
            guild_id=channel.guild.id,
            channel_id=channel.id,
            channel_type="voice",
            send_messages=None,
            connect=current_overwrite.connect,
        )

        current_overwrite.connect = False
        current_overwrite.speak = False

        await channel.set_permissions(
            everyone_role,
            overwrite=current_overwrite,
            reason=reason,
        )

        # Give mod role explicit allow so they can still use voice
        if mod_role:
            mod_overwrite: discord.PermissionOverwrite = channel.overwrites_for(mod_role)
            mod_overwrite.connect = True
            mod_overwrite.speak = True
            await channel.set_permissions(
                mod_role,
                overwrite=mod_overwrite,
                reason=f"{reason} (mod access)",
            )

        logger.debug("Channel Locked", [
            ("Channel", f"🔊{channel.name}"),
            ("ID", str(channel.id)),
            ("Type", "voice"),
            ("Mod Access", "yes" if mod_role else "no"),
        ])

        return True, None

    except discord.Forbidden:
        error_msg = f"🔊{channel.name}: Missing permissions"
        logger.warning("Channel Lock Failed", [
            ("Channel", f"🔊{channel.name} ({channel.id})"),
            ("Error", "Forbidden - missing permissions"),
        ])
        return False, error_msg

    except discord.HTTPException as e:
        error_msg = f"🔊{channel.name}: {e.text[:50] if e.text else 'HTTP error'}"
        log_http_error(e, "Channel Lock (Voice)", [
            ("Channel", f"🔊{channel.name} ({channel.id})"),
        ])
        return False, error_msg

    except Exception as e:
        error_msg = f"🔊{channel.name}: {str(e)[:50]}"
        logger.error("Channel Lock Error", [
            ("Channel", f"🔊{channel.name} ({channel.id})"),
            ("Error", str(e)[:100]),
            ("Type", type(e).__name__),
        ])
        return False, error_msg


async def lock_all_channels(
    guild: discord.Guild,
    everyone_role: discord.Role,
    mod_role: Optional[discord.Role],
    reason: str,
    db: "DatabaseManager",
) -> LockdownResult:
    """
    Lock all channels in a guild concurrently.

    Args:
        guild: The guild to lock.
        everyone_role: The @everyone role.
        mod_role: The moderation role (or None) - mods keep access.
        reason: Audit log reason.
        db: Database manager for saving permissions.

    Returns:
        LockdownResult with counts and errors.
    """
    result = LockdownResult()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_OPS)

    async def lock_with_semaphore(coro) -> Tuple[bool, Optional[str]]:
        async with semaphore:
            return await coro

    # Build list of lock tasks
    tasks: List[asyncio.Task] = []

    for channel in guild.text_channels:
        task = create_safe_task(
            lock_with_semaphore(lock_text_channel(channel, everyone_role, mod_role, reason, db)),
            f"Lock #{channel.name}",
        )
        tasks.append(task)

    for channel in guild.voice_channels:
        task = create_safe_task(
            lock_with_semaphore(lock_voice_channel(channel, everyone_role, mod_role, reason, db)),
            f"Lock 🔊{channel.name}",
        )
        tasks.append(task)

    # Execute all tasks concurrently
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                result.failed_count += 1
                result.errors.append(str(res)[:100])
                logger.error("Lock Task Exception", [
                    ("Error", str(res)[:100]),
                    ("Type", type(res).__name__),
                ])
            elif isinstance(res, tuple):
                success, error = res
                if success:
                    result.success_count += 1
                else:
                    result.failed_count += 1
                    if error:
                        result.errors.append(error)

    return result


__all__ = ["lock_text_channel", "lock_voice_channel", "lock_all_channels"]
