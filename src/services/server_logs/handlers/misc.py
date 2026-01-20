"""
Server Logs - Misc Handler
==========================

Handles miscellaneous logging (pins, voice actions, verification, etc.).

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import TYPE_CHECKING, List, Optional, Tuple, Union
import io

import discord

from src.core.config import EmbedColors
from src.core.database import get_db
from src.core.logger import logger

if TYPE_CHECKING:
    from ..service import LoggingService


class MiscLogsMixin:
    """Mixin for miscellaneous logging."""

    async def log_message_pin(
        self: "LoggingService",
        message: Optional[discord.Message] = None,
        pinned: bool = True,
        moderator: Optional[discord.Member] = None,
        channel: Optional[discord.TextChannel] = None,
        message_id: Optional[int] = None,
    ) -> None:
        """Log a message being pinned or unpinned."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import MessageLogView

        user_id = message.author.id if message else None

        if pinned:
            embed = self._create_embed("📌 Message Pinned", EmbedColors.SUCCESS, category="Pin", user_id=user_id)
        else:
            embed = self._create_embed("📌 Message Unpinned", EmbedColors.WARNING, category="Unpin", user_id=user_id)

        if message:
            embed.add_field(name="Author", value=self._format_user_field(message.author), inline=True)
            embed.add_field(name="Channel", value=self._format_channel(message.channel), inline=True)
            if moderator:
                embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

            if message.content:
                preview = message.content[:200] + "..." if len(message.content) > 200 else message.content
                embed.add_field(name="Content Preview", value=f"```{preview}```", inline=False)

            self._set_user_thumbnail(embed, message.author)

            view = MessageLogView(message.author.id, message.guild.id if message.guild else 0, message_url=message.jump_url)
            await self._send_log(LogCategory.MESSAGES, embed, user_id=user_id, view=view)
            return
        else:
            if channel:
                embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
            if moderator:
                embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
            if message_id:
                embed.add_field(name="Message ID", value=f"`{message_id}`", inline=True)
            if not pinned:
                embed.add_field(name="Note", value="*Message may have been deleted*", inline=False)

        await self._send_log(LogCategory.MESSAGES, embed, user_id=user_id)

    async def log_server_voice_mute(
        self: "LoggingService",
        member: discord.Member,
        muted: bool,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a server voice mute/unmute from audit log."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        if muted:
            embed = self._create_embed("🔇 Server Voice Muted", EmbedColors.WARNING, category="Voice Mute", user_id=member.id)
        else:
            embed = self._create_embed("🔊 Server Voice Unmuted", EmbedColors.SUCCESS, category="Voice Unmute", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        if member.voice and member.voice.channel:
            embed.add_field(name="Channel", value=f"🔊 {self._format_channel(member.voice.channel)}", inline=True)

        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_server_voice_deafen(
        self: "LoggingService",
        member: discord.Member,
        deafened: bool,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a server voice deafen/undeafen from audit log."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        if deafened:
            embed = self._create_embed("🔇 Server Voice Deafened", EmbedColors.WARNING, category="Voice Deafen", user_id=member.id)
        else:
            embed = self._create_embed("🔊 Server Voice Undeafened", EmbedColors.SUCCESS, category="Voice Undeafen", user_id=member.id)

        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        if member.voice and member.voice.channel:
            embed.add_field(name="Channel", value=f"🔊 {self._format_channel(member.voice.channel)}", inline=True)

        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.VOICE, embed, user_id=member.id)

    async def log_member_verification(
        self: "LoggingService",
        member: discord.Member,
    ) -> None:
        """Edit the original join embed to add [Verified] when member passes screening."""
        from ..categories import LogCategory

        if not self._initialized or LogCategory.JOINS not in self._threads:
            return

        db = get_db()
        message_id = db.get_join_message_id(member.id, member.guild.id)
        if not message_id:
            return

        try:
            thread = self._threads[LogCategory.JOINS]
            message = await thread.fetch_message(message_id)

            if message.embeds:
                embed = message.embeds[0]
                embed.title = "📥 Member Joined [Verified] ✅"
                await message.edit(embed=embed)
        except discord.NotFound:
            pass
        except Exception as e:
            logger.debug(f"Logging Service: Failed to edit join message: {e}")

    async def log_nickname_force_change(
        self: "LoggingService",
        target: discord.Member,
        old_nick: Optional[str],
        new_nick: Optional[str],
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log when a mod changes someone else's nickname."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("✏️ Nickname Force Changed", EmbedColors.WARNING, category="Nickname Force", user_id=target.id)
        embed.add_field(name="Target", value=self._format_user_field(target), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        embed.add_field(name="Before", value=f"`{old_nick}`" if old_nick else "*(none)*", inline=True)
        embed.add_field(name="After", value=f"`{new_nick}`" if new_nick else "*(none)*", inline=True)

        self._set_user_thumbnail(embed, target)

        await self._send_log(LogCategory.NAME_CHANGES, embed, user_id=target.id)

    async def log_voice_disconnect(
        self: "LoggingService",
        target: discord.Member,
        channel_name: str,
        moderator: Optional[discord.Member] = None,
        channel_id: Optional[int] = None,
    ) -> None:
        """Log when a mod disconnects a user from voice."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🔌 Voice Disconnected", EmbedColors.LOG_NEGATIVE, category="Voice Disconnect", user_id=target.id)
        embed.add_field(name="User", value=self._format_user_field(target), inline=True)
        channel_value = f"🔊 <#{channel_id}>" if channel_id else f"🔊 {channel_name}"
        embed.add_field(name="From Channel", value=channel_value, inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        self._set_user_thumbnail(embed, target)

        await self._send_log(LogCategory.VOICE, embed, user_id=target.id)

    async def log_mod_message_delete(
        self: "LoggingService",
        author: discord.User,
        channel: discord.abc.GuildChannel,
        content: Optional[str],
        moderator: Optional[discord.Member] = None,
        attachments: Optional[List[Tuple[str, bytes]]] = None,
        attachment_names: Optional[List[str]] = None,
        sticker_names: Optional[List[str]] = None,
        has_embeds: bool = False,
        embed_titles: Optional[List[str]] = None,
    ) -> None:
        """Log when a mod deletes someone else's message."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🗑️ Message Deleted by Mod", EmbedColors.LOG_NEGATIVE, category="Mod Delete", user_id=author.id)
        embed.add_field(name="Author", value=self._format_user_field(author), inline=True)
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        if content:
            truncated = content[:900] if len(content) > 900 else content
            embed.add_field(name="Content", value=f"```{truncated}```", inline=False)
        else:
            context_parts = []

            if attachment_names:
                files_str = ", ".join(f"`{name}`" for name in attachment_names[:5])
                if len(attachment_names) > 5:
                    files_str += f" +{len(attachment_names) - 5} more"
                context_parts.append(f"📎 **Attachments:** {files_str}")

            if sticker_names:
                stickers_str = ", ".join(f"`{name}`" for name in sticker_names[:3])
                context_parts.append(f"🎨 **Stickers:** {stickers_str}")

            if has_embeds:
                if embed_titles:
                    titles_str = ", ".join(f"`{t}`" for t in embed_titles[:3])
                    context_parts.append(f"📋 **Embeds:** {titles_str}")
                else:
                    context_parts.append("📋 **Embed** (link preview or bot embed)")

            if context_parts:
                context_str = "\n".join(context_parts)
                embed.add_field(name="Content", value=f"*(no text)*\n{context_str}", inline=False)
            elif attachment_names is None and sticker_names is None:
                embed.add_field(
                    name="Content",
                    value="*(message not cached - bot may have restarted)*",
                    inline=False,
                )
            else:
                embed.add_field(name="Content", value="*(empty message)*", inline=False)

        self._set_user_thumbnail(embed, author)

        files = []
        if attachments:
            for filename, data in attachments[:5]:
                files.append(discord.File(io.BytesIO(data), filename=filename))

        await self._send_log(LogCategory.MESSAGES, embed, files, user_id=author.id)

    async def log_slowmode_change(
        self: "LoggingService",
        channel: discord.abc.GuildChannel,
        old_delay: int,
        new_delay: int,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log when channel slowmode is changed."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("🐌 Slowmode Changed", EmbedColors.WARNING, category="Slowmode")
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        def format_delay(seconds: int) -> str:
            if seconds == 0:
                return "Off"
            elif seconds < 60:
                return f"{seconds}s"
            elif seconds < 3600:
                return f"{seconds // 60}m"
            else:
                return f"{seconds // 3600}h"

        embed.add_field(name="Before", value=f"`{format_delay(old_delay)}`", inline=True)
        embed.add_field(name="After", value=f"`{format_delay(new_delay)}`", inline=True)

        await self._send_log(LogCategory.CHANNELS, embed)

    async def log_channel_category_move(
        self: "LoggingService",
        channel: discord.abc.GuildChannel,
        old_category: Optional[str],
        new_category: Optional[str],
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log when a channel is moved between categories."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        embed = self._create_embed("📂 Channel Moved", EmbedColors.WARNING, category="Category Move")
        embed.add_field(name="Channel", value=self._format_channel(channel), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        embed.add_field(
            name="From Category",
            value=f"`{old_category}`" if old_category else "*(no category)*",
            inline=True,
        )
        embed.add_field(
            name="To Category",
            value=f"`{new_category}`" if new_category else "*(no category)*",
            inline=True,
        )

        await self._send_log(LogCategory.CHANNELS, embed)

    async def log_role_position_change(
        self: "LoggingService",
        role: discord.Role,
        old_position: int,
        new_position: int,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log when a role's position in hierarchy changes."""
        if not self.enabled:
            return

        from ..categories import LogCategory

        if new_position > old_position:
            embed = self._create_embed("⬆️ Role Moved Up", EmbedColors.SUCCESS, category="Role Position")
            direction = "higher"
        else:
            embed = self._create_embed("⬇️ Role Moved Down", EmbedColors.WARNING, category="Role Position")
            direction = "lower"

        embed.add_field(name="Role", value=self._format_role(role), inline=True)
        embed.add_field(name="Position", value=f"`{old_position}` → `{new_position}` ({direction})", inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)

        await self._send_log(LogCategory.ROLES, embed)


__all__ = ["MiscLogsMixin"]
