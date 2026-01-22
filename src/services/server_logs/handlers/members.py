"""
AzabBot - Members Handler
=========================

Handles member join, leave, role changes, name changes, and avatar changes.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import io
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import aiohttp
import discord

from src.core.logger import logger
from src.core.config import EmbedColors
from src.core.database import get_db

if TYPE_CHECKING:
    from ..service import LoggingService


class MemberLogsMixin:
    """Mixin for member-related logging."""

    async def log_member_join(
        self: "LoggingService",
        member: discord.Member,
        invite_code: Optional[str] = None,
        inviter: Optional[discord.User] = None,
    ) -> None:
        """Log a member join."""
        if not self._should_log(member.guild.id, member.id):
            return

        from ..categories import LogCategory

        db = get_db()
        activity = db.get_member_activity(member.id, member.guild.id)
        join_count = (activity["join_count"] + 1) if activity else 1

        embed = self._create_embed("📥 Member Joined", EmbedColors.SUCCESS, category="Join", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)

        created = int(member.created_at.timestamp())
        embed.add_field(name="Account Created", value=f"<t:{created}:R>", inline=True)

        if invite_code:
            embed.add_field(name="Invite", value=f"`{invite_code}`", inline=True)
        if inviter:
            embed.add_field(name="Invited By", value=self._format_user_field(inviter), inline=True)

        if join_count > 1:
            embed.add_field(name="Join #", value=f"`{join_count}`", inline=True)

        embed.add_field(name="Members", value=f"`{member.guild.member_count:,}`", inline=True)
        self._set_user_thumbnail(embed, member)

        message = await self._send_log(LogCategory.JOINS, embed, user_id=member.id)

        message_id = message.id if message else None
        db.record_member_join(member.id, member.guild.id, join_message_id=message_id)
        if message_id:
            logger.debug(f"Stored join message {message_id} for member {member.id} in database")

    async def _edit_join_message_on_leave(
        self: "LoggingService",
        message_id: int,
        member: discord.Member,
        was_banned: bool,
    ) -> None:
        """Edit the original join embed to show they left."""
        from ..categories import LogCategory

        logger.debug(f"Editing join message {message_id} for member {member.id}")
        try:
            thread = self._threads[LogCategory.JOINS]
            message = await thread.fetch_message(message_id)
            logger.debug(f"Fetched message {message_id}, has embeds: {bool(message.embeds)}")

            if message.embeds:
                embed = message.embeds[0]

                duration_str = "Unknown"
                if member.joined_at:
                    total_seconds = int(datetime.now(timezone.utc).timestamp() - member.joined_at.timestamp())
                    total_seconds = max(0, total_seconds)
                    duration_str = self._format_duration_precise(total_seconds)

                if was_banned:
                    embed.title = "📥 Member Joined → 🔨 Banned"
                    embed.color = EmbedColors.LOG_NEGATIVE
                else:
                    embed.title = "📥 Member Joined → 📤 Left"
                    embed.color = EmbedColors.WARNING

                embed.add_field(name="Left After", value=f"`{duration_str}`", inline=True)
                await message.edit(embed=embed)
        except discord.NotFound:
            pass
        except Exception as e:
            logger.debug(f"Logging Service: Failed to edit join message on leave: {e}")

    async def log_member_leave(
        self: "LoggingService",
        member: discord.Member,
        was_banned: bool = False,
    ) -> None:
        """Log a member leave with detailed info."""
        from ..categories import LogCategory

        db = get_db()

        join_message_id = db.pop_join_message_id(member.id, member.guild.id)
        logger.debug(f"Member leave: {member.id}, join_message_id={join_message_id}, JOINS in threads={LogCategory.JOINS in self._threads}")

        if join_message_id and LogCategory.JOINS in self._threads:
            await self._edit_join_message_on_leave(join_message_id, member, was_banned)
        elif join_message_id:
            logger.debug(f"JOINS thread not found, cannot edit join message for {member.id}")

        if not self._should_log(member.guild.id, member.id):
            return
        leave_count = db.record_member_leave(member.id, member.guild.id)

        if was_banned:
            title = "📤 Member Left [Banned]"
            color = EmbedColors.LOG_NEGATIVE
        else:
            title = "📤 Member Left"
            color = EmbedColors.WARNING

        embed = self._create_embed(title, color, category="Leave", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)

        created = int(member.created_at.timestamp())
        embed.add_field(name="Account Age", value=f"<t:{created}:R>", inline=True)

        if member.joined_at:
            total_seconds = int(datetime.now(timezone.utc).timestamp() - member.joined_at.timestamp())
            total_seconds = max(0, total_seconds)
            duration_str = self._format_duration_precise(total_seconds)
            embed.add_field(name="Time in Server", value=f"`{duration_str}`", inline=True)

        if leave_count > 1:
            embed.add_field(name="Leave #", value=f"`{leave_count}`", inline=True)

        embed.add_field(name="Members", value=f"`{member.guild.member_count:,}`", inline=True)

        roles = [r for r in member.roles if r.name != "@everyone"]
        role_count = len(roles)
        role_names = [self._format_role(r) for r in roles[:15]]
        if role_names:
            roles_str = " ".join(role_names)
            if role_count > 15:
                roles_str += f" +{role_count - 15} more"
            embed.add_field(name=f"Roles ({role_count})", value=roles_str, inline=False)

        self._set_user_thumbnail(embed, member)
        await self._send_log(LogCategory.LEAVES, embed, user_id=member.id)

    async def log_role_add(
        self: "LoggingService",
        member: discord.Member,
        role: discord.Role,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a role being added to a member."""
        if not self._should_log(member.guild.id, member.id):
            return

        from ..categories import LogCategory

        embed = self._create_embed("➕ Role Added", EmbedColors.SUCCESS, category="Role Add", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Role", value=self._format_role(role), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.ROLE_CHANGES, embed, user_id=member.id)

    async def log_role_remove(
        self: "LoggingService",
        member: discord.Member,
        role: discord.Role,
        moderator: Optional[discord.Member] = None,
    ) -> None:
        """Log a role being removed from a member."""
        if not self._should_log(member.guild.id, member.id):
            return

        from ..categories import LogCategory

        embed = self._create_embed("➖ Role Removed", EmbedColors.LOG_NEGATIVE, category="Role Remove", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Role", value=self._format_role(role), inline=True)
        if moderator:
            embed.add_field(name="By", value=self._format_user_field(moderator), inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.ROLE_CHANGES, embed, user_id=member.id)

    async def log_nickname_change(
        self: "LoggingService",
        member: discord.Member,
        before: Optional[str],
        after: Optional[str],
    ) -> None:
        """Log a nickname change."""
        if not self._should_log(member.guild.id, member.id):
            return

        from ..categories import LogCategory

        embed = self._create_embed("✨ Nickname Changed", EmbedColors.INFO, category="Nickname", user_id=member.id)
        embed.add_field(name="User", value=self._format_user_field(member), inline=True)
        embed.add_field(name="Before", value=f"`{before}`" if before else "*(none)*", inline=True)
        embed.add_field(name="After", value=f"`{after}`" if after else "*(none)*", inline=True)
        self._set_user_thumbnail(embed, member)

        await self._send_log(LogCategory.NAME_CHANGES, embed, user_id=member.id)

    async def log_username_change(
        self: "LoggingService",
        user: discord.User,
        before: str,
        after: str,
    ) -> None:
        """Log a username change."""
        if not self.enabled or (self.config.ignored_bot_ids and user.id in self.config.ignored_bot_ids):
            return

        from ..categories import LogCategory

        embed = self._create_embed("✨ Username Changed", EmbedColors.INFO, category="Username", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Before", value=f"`{before}`", inline=True)
        embed.add_field(name="After", value=f"`{after}`", inline=True)
        self._set_user_thumbnail(embed, user)

        await self._send_log(LogCategory.NAME_CHANGES, embed, user_id=user.id)

    async def log_avatar_change(
        self: "LoggingService",
        user: discord.User,
        before_url: Optional[str],
        after_url: Optional[str],
    ) -> None:
        """Log an avatar change."""
        if not self.enabled or (self.config.ignored_bot_ids and user.id in self.config.ignored_bot_ids):
            return

        from ..categories import LogCategory
        from ..views import UserIdButton, OldAvatarButton, NewAvatarButton

        embed = self._create_embed("🖼️ Avatar Changed", EmbedColors.INFO, category="Avatar", user_id=user.id)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)

        files = []
        old_avatar_downloaded = False

        if before_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(before_url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            files.append(discord.File(io.BytesIO(data), filename="old_avatar.png"))
                            embed.set_thumbnail(url="attachment://old_avatar.png")
                            embed.add_field(name="Previous", value="See thumbnail ↗️", inline=True)
                            old_avatar_downloaded = True
            except Exception:
                pass

        if after_url:
            embed.set_image(url=after_url)
            embed.add_field(name="New", value="See image below ↓", inline=True)

        message = await self._send_log(LogCategory.AVATAR_CHANGES, embed, files, user_id=user.id)

        if message:
            try:
                view = discord.ui.View(timeout=None)
                if old_avatar_downloaded:
                    view.add_item(OldAvatarButton(message.channel.id, message.id))
                if after_url:
                    view.add_item(NewAvatarButton(message.channel.id, message.id))
                view.add_item(UserIdButton(user.id))
                await message.edit(view=view)
            except Exception:
                pass
