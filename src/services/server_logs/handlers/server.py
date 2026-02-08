"""
AzabBot - Server Handler
========================

Handles server settings, emoji, stickers, and bot/integration logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, Optional

import discord

from src.core.config import EmbedColors
from ..categories import LogCategory

if TYPE_CHECKING:
    from ..service import LoggingService


class ServerLogsMixin:
    """Mixin for server-level logging (settings, emoji, stickers, bots)."""

    # =========================================================================
    # Emoji & Stickers
    # =========================================================================

    async def log_emoji_create(
        self: "LoggingService",
        emoji: discord.Emoji,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log an emoji creation."""
        if not self.enabled:
            return

        user_id = moderator.id if moderator else None
        embed = self._create_embed("😀 Emoji Created", EmbedColors.SUCCESS, category="Emoji Create", user_id=user_id)
        embed.add_field(name="Emoji", value=f"{emoji} `:{emoji.name}:`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        embed.add_field(name="Animated", value="Yes" if emoji.animated else "No", inline=True)
        embed.add_field(name="ID", value=f"`{emoji.id}`", inline=True)
        embed.set_thumbnail(url=emoji.url)

        await self._send_log(LogCategory.EMOJI_STICKERS, embed, user_id=user_id)

    async def log_emoji_delete(
        self: "LoggingService",
        emoji_name: str,
        emoji_id: Optional[int] = None,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log an emoji deletion."""
        if not self.enabled:
            return

        user_id = moderator.id if moderator else None
        embed = self._create_embed("😀 Emoji Deleted", EmbedColors.LOG_NEGATIVE, category="Emoji Delete", user_id=user_id)
        embed.add_field(name="Emoji", value=f"`:{emoji_name}:`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if emoji_id:
            embed.add_field(name="ID", value=f"`{emoji_id}`", inline=True)

        await self._send_log(LogCategory.EMOJI_STICKERS, embed, user_id=user_id)

    async def log_sticker_create(
        self: "LoggingService",
        sticker: discord.GuildSticker,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a sticker creation."""
        if not self.enabled:
            return

        user_id = moderator.id if moderator else None
        embed = self._create_embed("🎨 Sticker Created", EmbedColors.SUCCESS, category="Sticker Create", user_id=user_id)
        embed.add_field(name="Sticker", value=f"`{sticker.name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        if sticker.description:
            embed.add_field(name="Description", value=sticker.description[:100], inline=True)
        embed.add_field(name="Emoji", value=sticker.emoji or "None", inline=True)
        embed.add_field(name="ID", value=f"`{sticker.id}`", inline=True)
        embed.set_thumbnail(url=sticker.url)

        await self._send_log(LogCategory.EMOJI_STICKERS, embed, user_id=user_id)

    async def log_sticker_delete(
        self: "LoggingService",
        sticker_name: str,
        sticker_id: Optional[int] = None,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a sticker deletion."""
        if not self.enabled:
            return

        user_id = moderator.id if moderator else None
        embed = self._create_embed("🎨 Sticker Deleted", EmbedColors.LOG_NEGATIVE, category="Sticker Delete", user_id=user_id)
        embed.add_field(name="Sticker", value=f"`{sticker_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        if sticker_id:
            embed.add_field(name="ID", value=f"`{sticker_id}`", inline=True)

        await self._send_log(LogCategory.EMOJI_STICKERS, embed, user_id=user_id)

    # =========================================================================
    # Server Settings
    # =========================================================================

    async def log_server_update(
        self: "LoggingService",
        changes: str,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log server settings changes."""
        if not self.enabled:
            return

        embed = self._create_embed("⚙️ Server Updated", EmbedColors.WARNING, category="Server Update")
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        embed.add_field(name="Changes", value=f"```{changes}```", inline=False)

        await self._send_log(LogCategory.SERVER_SETTINGS, embed)

    async def log_server_icon_change(
        self: "LoggingService",
        guild: discord.Guild,
        old_icon_url: Optional[str],
        new_icon_url: Optional[str],
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log server icon change with images."""
        if not self.enabled:
            return

        embed = self._create_embed("🖼️ Server Icon Changed", EmbedColors.WARNING, category="Icon Change")
        embed.add_field(name="Server", value=guild.name, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        if old_icon_url:
            embed.add_field(name="Previous", value=f"[View]({old_icon_url})", inline=True)
        else:
            embed.add_field(name="Previous", value="*(none)*", inline=True)

        if new_icon_url:
            embed.set_thumbnail(url=new_icon_url)
            embed.add_field(name="New", value="See thumbnail →", inline=True)
        else:
            embed.add_field(name="New", value="*(removed)*", inline=True)

        await self._send_log(LogCategory.SERVER_SETTINGS, embed)

    async def log_server_banner_change(
        self: "LoggingService",
        guild: discord.Guild,
        old_banner_url: Optional[str],
        new_banner_url: Optional[str],
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log server banner change with images."""
        if not self.enabled:
            return

        embed = self._create_embed("🎨 Server Banner Changed", EmbedColors.WARNING, category="Banner Change")
        embed.add_field(name="Server", value=guild.name, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        if old_banner_url:
            embed.add_field(name="Previous", value=f"[View]({old_banner_url})", inline=True)
        else:
            embed.add_field(name="Previous", value="*(none)*", inline=True)

        if new_banner_url:
            embed.set_image(url=new_banner_url)
            embed.add_field(name="New", value="See image below ↓", inline=True)
        else:
            embed.add_field(name="New", value="*(removed)*", inline=True)

        await self._send_log(LogCategory.SERVER_SETTINGS, embed)

    # =========================================================================
    # Bots & Integrations
    # =========================================================================

    async def log_bot_add(
        self: "LoggingService",
        bot: discord.Member,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a bot being added."""
        if not self.enabled:
            return

        embed = self._create_embed("🤖 Bot Added", EmbedColors.WARNING, category="Bot Add", user_id=bot.id)
        embed.add_field(name="Bot", value=self._format_user_field(bot), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        self._set_user_thumbnail(embed, bot)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed, user_id=bot.id)

    async def log_bot_remove(
        self: "LoggingService",
        bot_name: str,
        bot_id: int,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a bot being removed."""
        if not self.enabled:
            return

        embed = self._create_embed("🤖 Bot Removed", EmbedColors.LOG_NEGATIVE, category="Bot Remove", user_id=bot_id)
        embed.add_field(name="Bot", value=f"`{bot_name}`", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.BOTS_INTEGRATIONS, embed, user_id=bot_id)


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["ServerLogsMixin"]
