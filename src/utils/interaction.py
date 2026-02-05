"""
AzabBot - Interaction Utilities
===============================

Shared helpers for Discord interaction handling.

Provides safe_respond() to eliminate repetitive try-except blocks
around interaction.response.is_done() checks.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Any, Optional, Union

import discord

from src.core.logger import logger


async def safe_respond(
    interaction: discord.Interaction,
    content: Optional[str] = None,
    *,
    embed: Optional[discord.Embed] = None,
    embeds: Optional[list[discord.Embed]] = None,
    view: Optional[discord.ui.View] = None,
    ephemeral: bool = True,
    delete_after: Optional[float] = None,
    allowed_mentions: Optional[discord.AllowedMentions] = None,
    suppress_embeds: bool = False,
    silent: bool = False,
    file: Optional[discord.File] = None,
    files: Optional[list[discord.File]] = None,
) -> Optional[Union[discord.InteractionMessage, discord.WebhookMessage]]:
    """
    Safely respond to an interaction, handling is_done() checks.

    This function automatically handles the common pattern of:
    1. Check if interaction.response.is_done()
    2. If not done, use response.send_message()
    3. If done, use followup.send()
    4. Handle HTTPException gracefully

    Args:
        interaction: The Discord interaction to respond to.
        content: The message content.
        embed: A single embed to send.
        embeds: A list of embeds to send.
        view: A view to attach.
        ephemeral: Whether the response is ephemeral (default True).
        delete_after: Seconds before auto-deleting the message.
        allowed_mentions: Allowed mentions configuration.
        suppress_embeds: Whether to suppress embeds.
        silent: Whether to suppress notifications.
        file: A file to attach.
        files: A list of files to attach.

    Returns:
        The sent message if successful, None if failed.

    Example:
        ```python
        # Instead of:
        try:
            response_done = False
            try:
                response_done = interaction.response.is_done()
            except discord.HTTPException:
                response_done = True
            if not response_done:
                await interaction.response.send_message("Error", ephemeral=True)
            else:
                await interaction.followup.send("Error", ephemeral=True)
        except discord.HTTPException:
            pass

        # Just use:
        await safe_respond(interaction, "Error", ephemeral=True)
        ```
    """
    # Build kwargs for send methods
    kwargs: dict[str, Any] = {"ephemeral": ephemeral}

    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if embeds is not None:
        kwargs["embeds"] = embeds
    if view is not None:
        kwargs["view"] = view
    if allowed_mentions is not None:
        kwargs["allowed_mentions"] = allowed_mentions
    if suppress_embeds:
        kwargs["suppress_embeds"] = suppress_embeds
    if silent:
        kwargs["silent"] = silent
    if file is not None:
        kwargs["file"] = file
    if files is not None:
        kwargs["files"] = files

    # Check if response is already done
    response_done = False
    try:
        response_done = interaction.response.is_done()
    except discord.HTTPException:
        # If we can't check, assume done and use followup
        response_done = True

    try:
        if not response_done:
            # Use initial response
            await interaction.response.send_message(**kwargs)
            # delete_after not supported on initial response, handle via followup
            if delete_after is not None:
                try:
                    msg = await interaction.original_response()
                    await msg.delete(delay=delete_after)
                except discord.HTTPException:
                    pass
            try:
                return await interaction.original_response()
            except discord.HTTPException:
                return None
        else:
            # Use followup
            if delete_after is not None:
                kwargs["delete_after"] = delete_after
            return await interaction.followup.send(**kwargs)

    except discord.HTTPException as e:
        # Log but don't raise - this is expected for expired interactions
        logger.debug(f"safe_respond failed: {e.status} - {str(e)[:50]}")
        return None

    except Exception as e:
        # Unexpected error - log it
        logger.debug(f"safe_respond unexpected error: {type(e).__name__}: {str(e)[:50]}")
        return None


async def safe_defer(
    interaction: discord.Interaction,
    *,
    ephemeral: bool = True,
    thinking: bool = False,
) -> bool:
    """
    Safely defer an interaction response.

    Args:
        interaction: The Discord interaction to defer.
        ephemeral: Whether the deferred response is ephemeral.
        thinking: Whether to show the "thinking" indicator.

    Returns:
        True if deferred successfully, False if already responded or failed.
    """
    try:
        if interaction.response.is_done():
            return False
        await interaction.response.defer(ephemeral=ephemeral, thinking=thinking)
        return True
    except discord.HTTPException:
        return False


async def safe_edit(
    interaction: discord.Interaction,
    *,
    content: Optional[str] = discord.utils.MISSING,
    embed: Optional[discord.Embed] = discord.utils.MISSING,
    embeds: Optional[list[discord.Embed]] = discord.utils.MISSING,
    view: Optional[discord.ui.View] = discord.utils.MISSING,
    attachments: Optional[list[discord.Attachment]] = discord.utils.MISSING,
) -> bool:
    """
    Safely edit the original interaction response.

    Args:
        interaction: The Discord interaction.
        content: New content (pass None to remove).
        embed: New embed (pass None to remove).
        embeds: New embeds list.
        view: New view.
        attachments: New attachments.

    Returns:
        True if edited successfully, False if failed.
    """
    kwargs: dict[str, Any] = {}

    if content is not discord.utils.MISSING:
        kwargs["content"] = content
    if embed is not discord.utils.MISSING:
        kwargs["embed"] = embed
    if embeds is not discord.utils.MISSING:
        kwargs["embeds"] = embeds
    if view is not discord.utils.MISSING:
        kwargs["view"] = view
    if attachments is not discord.utils.MISSING:
        kwargs["attachments"] = attachments

    try:
        await interaction.edit_original_response(**kwargs)
        return True
    except discord.HTTPException as e:
        logger.debug(f"safe_edit failed: {e.status} - {str(e)[:50]}")
        return False


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["safe_respond", "safe_defer", "safe_edit"]
