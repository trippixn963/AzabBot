"""
AzabBot - Lockdown Unlock Operations
====================================

Channel unlocking operations for the lockdown command.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import discord

from src.core.logger import logger
from src.utils.async_utils import create_safe_task
from src.utils.discord_rate_limit import log_http_error

from .constants import MAX_CONCURRENT_OPS, LockdownResult

if TYPE_CHECKING:
    from src.core.database.manager import DatabaseManager


async def unlock_text_channel(
    channel: discord.TextChannel,
    everyone_role: discord.Role,
    mod_role: Optional[discord.Role],
    saved_perms: Optional[dict],
    reason: str,
) -> Tuple[bool, Optional[str]]:
    """
    Unlock a single text channel.

    Args:
        channel: The text channel to unlock.
        everyone_role: The @everyone role.
        mod_role: The moderation role (or None).
        saved_perms: Saved original permissions (or None).
        reason: Audit log reason.

    Returns:
        Tuple of (success, error_message).
    """
    try:
        current_overwrite: discord.PermissionOverwrite = channel.overwrites_for(everyone_role)

        if saved_perms:
            # Restore original permission (None = not set, True/False = explicit)
            original_send = saved_perms.get("original_send_messages")
            current_overwrite.send_messages = original_send
            current_overwrite.add_reactions = original_send
            current_overwrite.create_public_threads = original_send
            current_overwrite.create_private_threads = original_send
            current_overwrite.send_messages_in_threads = original_send
        else:
            # No saved state - remove explicit denies (set to None/neutral)
            current_overwrite.send_messages = None
            current_overwrite.add_reactions = None
            current_overwrite.create_public_threads = None
            current_overwrite.create_private_threads = None
            current_overwrite.send_messages_in_threads = None

        # If overwrite is now empty, remove it entirely
        if current_overwrite.is_empty():
            await channel.set_permissions(everyone_role, overwrite=None, reason=reason)
        else:
            await channel.set_permissions(everyone_role, overwrite=current_overwrite, reason=reason)

        # Remove mod role overwrites we added during lockdown
        if mod_role:
            mod_overwrite: discord.PermissionOverwrite = channel.overwrites_for(mod_role)
            # Set back to neutral (removes our explicit allows)
            mod_overwrite.send_messages = None
            mod_overwrite.add_reactions = None
            if mod_overwrite.is_empty():
                await channel.set_permissions(mod_role, overwrite=None, reason=reason)
            else:
                await channel.set_permissions(mod_role, overwrite=mod_overwrite, reason=reason)

        logger.debug("Channel Unlocked", [
            ("Channel", f"#{channel.name}"),
            ("ID", str(channel.id)),
            ("Restored", "saved" if saved_perms else "default"),
        ])

        return True, None

    except discord.Forbidden:
        error_msg = f"#{channel.name}: Missing permissions"
        logger.warning("Channel Unlock Failed", [
            ("Channel", f"#{channel.name} ({channel.id})"),
            ("Error", "Forbidden"),
        ])
        return False, error_msg

    except discord.HTTPException as e:
        error_msg = f"#{channel.name}: {e.text[:50] if e.text else 'HTTP error'}"
        log_http_error(e, "Channel Unlock", [
            ("Channel", f"#{channel.name} ({channel.id})"),
        ])
        return False, error_msg

    except Exception as e:
        error_msg = f"#{channel.name}: {str(e)[:50]}"
        logger.error("Channel Unlock Error", [
            ("Channel", f"#{channel.name} ({channel.id})"),
            ("Error", str(e)[:100]),
            ("Type", type(e).__name__),
        ])
        return False, error_msg


async def unlock_voice_channel(
    channel: discord.VoiceChannel,
    everyone_role: discord.Role,
    mod_role: Optional[discord.Role],
    saved_perms: Optional[dict],
    reason: str,
) -> Tuple[bool, Optional[str]]:
    """
    Unlock a single voice channel.

    Args:
        channel: The voice channel to unlock.
        everyone_role: The @everyone role.
        mod_role: The moderation role (or None).
        saved_perms: Saved original permissions (or None).
        reason: Audit log reason.

    Returns:
        Tuple of (success, error_message).
    """
    try:
        current_overwrite: discord.PermissionOverwrite = channel.overwrites_for(everyone_role)

        if saved_perms:
            original_connect = saved_perms.get("original_connect")
            current_overwrite.connect = original_connect
            current_overwrite.speak = original_connect
        else:
            current_overwrite.connect = None
            current_overwrite.speak = None

        if current_overwrite.is_empty():
            await channel.set_permissions(everyone_role, overwrite=None, reason=reason)
        else:
            await channel.set_permissions(everyone_role, overwrite=current_overwrite, reason=reason)

        # Remove mod role overwrites we added during lockdown
        if mod_role:
            mod_overwrite: discord.PermissionOverwrite = channel.overwrites_for(mod_role)
            mod_overwrite.connect = None
            mod_overwrite.speak = None
            if mod_overwrite.is_empty():
                await channel.set_permissions(mod_role, overwrite=None, reason=reason)
            else:
                await channel.set_permissions(mod_role, overwrite=mod_overwrite, reason=reason)

        logger.debug("Channel Unlocked", [
            ("Channel", f"🔊{channel.name}"),
            ("ID", str(channel.id)),
            ("Restored", "saved" if saved_perms else "default"),
        ])

        return True, None

    except discord.Forbidden:
        error_msg = f"🔊{channel.name}: Missing permissions"
        logger.warning("Channel Unlock Failed", [
            ("Channel", f"🔊{channel.name} ({channel.id})"),
            ("Error", "Forbidden"),
        ])
        return False, error_msg

    except discord.HTTPException as e:
        error_msg = f"🔊{channel.name}: {e.text[:50] if e.text else 'HTTP error'}"
        log_http_error(e, "Channel Unlock (Voice)", [
            ("Channel", f"🔊{channel.name} ({channel.id})"),
        ])
        return False, error_msg

    except Exception as e:
        error_msg = f"🔊{channel.name}: {str(e)[:50]}"
        logger.error("Channel Unlock Error", [
            ("Channel", f"🔊{channel.name} ({channel.id})"),
            ("Error", str(e)[:100]),
            ("Type", type(e).__name__),
        ])
        return False, error_msg


async def unlock_all_channels(
    guild: discord.Guild,
    everyone_role: discord.Role,
    mod_role: Optional[discord.Role],
    reason: str,
    db: "DatabaseManager",
) -> LockdownResult:
    """
    Unlock all channels in a guild concurrently.

    Args:
        guild: The guild to unlock.
        everyone_role: The @everyone role.
        mod_role: The moderation role (or None) - clean up mod overwrites.
        reason: Audit log reason.
        db: Database manager for getting saved permissions.

    Returns:
        LockdownResult with counts and errors.
    """
    result = LockdownResult()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_OPS)

    # Get saved channel permissions
    saved_channel_perms = db.get_channel_permissions(guild.id)
    saved_lookup: Dict[int, dict] = {p["channel_id"]: p for p in saved_channel_perms}

    async def unlock_with_semaphore(coro) -> Tuple[bool, Optional[str]]:
        async with semaphore:
            return await coro

    tasks: List[asyncio.Task] = []

    for channel in guild.text_channels:
        saved = saved_lookup.get(channel.id)
        task = create_safe_task(
            unlock_with_semaphore(unlock_text_channel(channel, everyone_role, mod_role, saved, reason)),
            f"Unlock #{channel.name}",
        )
        tasks.append(task)

    for channel in guild.voice_channels:
        saved = saved_lookup.get(channel.id)
        task = create_safe_task(
            unlock_with_semaphore(unlock_voice_channel(channel, everyone_role, mod_role, saved, reason)),
            f"Unlock 🔊{channel.name}",
        )
        tasks.append(task)

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                result.failed_count += 1
                result.errors.append(str(res)[:100])
                logger.error("Unlock Task Exception", [
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


__all__ = ["unlock_text_channel", "unlock_voice_channel", "unlock_all_channels"]
