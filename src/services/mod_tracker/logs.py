"""
Azab Discord Bot - Mod Tracker Logging Methods
===============================================

Mixin class containing all logging methods for the ModTrackerService.

This file was extracted from service.py for better maintainability.
All log_* methods are grouped here and inherited by ModTrackerService.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional, List, Tuple
import asyncio
import io
import re

import aiohttp
import discord

from src.core.logger import logger
from src.core.config import EmbedColors, NY_TZ
from src.core.database import get_db
from src.utils.views import CASE_EMOJI, MESSAGE_EMOJI, CaseButtonView, MessageButtonView
from src.utils.footer import set_footer

from .constants import RATE_LIMIT_DELAY

if TYPE_CHECKING:
    from src.bot import AzabBot


class ModTrackerLogsMixin:
    """
    Mixin class containing all logging methods for mod tracking.

    This class should be inherited by ModTrackerService.
    It expects the following attributes/methods from the parent:
        - self.bot: AzabBot instance
        - self.db: Database manager
        - self.config: Config instance
        - self.enabled: bool property
        - self._create_embed(): Embed factory
        - self._add_mod_field(): Add mod info to embed
        - self._send_log(): Send log to mod's thread
        - self._get_mod_thread(): Get mod's forum thread
        - self._record_action(): Record action for stats
        - self._action_history: Dict for tracking actions
        - self._ban_history: Dict for ban history
        - self._permission_changes: Dict for permission changes
        - self._check_bulk_action(): Check for suspicious bulk actions
        - get_cached_message(): Get cached message
    """

    # =========================================================================
    # Activity Logging - Personal
    # =========================================================================

    async def log_avatar_change(
        self,
        mod: discord.Member,
        old_avatar: Optional[discord.Asset],
        new_avatar: Optional[discord.Asset],
    ) -> None:
        """Log an avatar change."""
        embed = self._create_embed(
            title="🖼️ Avatar Changed",
            color=EmbedColors.WARNING,
        )
        self._add_mod_field(embed, mod)

        if old_avatar:
            embed.add_field(name="Old", value=f"[View]({old_avatar.url})", inline=True)
        else:
            embed.add_field(name="Old", value="-", inline=True)

        if new_avatar:
            embed.add_field(name="New", value=f"[View]({new_avatar.url})", inline=True)
            embed.set_thumbnail(url=new_avatar.url)
        else:
            embed.add_field(name="New", value="*Removed*", inline=True)

        if await self._send_log(mod.id, embed, "Avatar Change"):
            # Update stored avatar hash
            new_hash = mod.avatar.key if mod.avatar else None
            self.db.update_mod_info(mod.id, avatar_hash=new_hash)

            logger.tree("Mod Tracker: Avatar Change Logged", [
                ("Mod", mod.display_name),
            ], emoji="🖼️")

    async def log_name_change(
        self,
        mod: discord.Member,
        change_type: str,
        old_name: str,
        new_name: str,
    ) -> None:
        """Log a username or display name change."""
        embed = self._create_embed(
            title=f"✏️ {change_type} Changed",
            color=EmbedColors.WARNING,
        )
        self._add_mod_field(embed, mod)
        embed.add_field(name="Before", value=f"`{old_name}`", inline=True)
        embed.add_field(name="After", value=f"`{new_name}`", inline=True)

        if await self._send_log(mod.id, embed, f"{change_type} Change"):
            # Update stored info
            if change_type == "Username":
                self.db.update_mod_info(mod.id, username=new_name)
            elif change_type == "Display Name":
                self.db.update_mod_info(mod.id, display_name=new_name)

            logger.tree("Mod Tracker: Name Change Logged", [
                ("Mod", mod.display_name),
                ("Type", change_type),
                ("Before", old_name[:20]),
                ("After", new_name[:20]),
            ], emoji="✏️")

    async def log_message_delete(
        self,
        mod_id: int,
        channel: discord.TextChannel,
        content: str,
        attachments: List[discord.Attachment] = None,
        message_id: int = None,
        reply_to_user: discord.User = None,
        reply_to_id: int = None,
    ) -> None:
        """Log a deleted message with attachments."""
        if not self.enabled:
            return

        tracked = self.db.get_tracked_mod(mod_id)
        if not tracked:
            return

        thread = await self._get_mod_thread(tracked["thread_id"])
        if not thread:
            return

        # Record action for bulk detection
        self._record_action(mod_id, "delete")

        # Build embed
        embed = self._create_embed(
            title="🗑️ Message Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
        if attachments and len(attachments) > 0:
            embed.add_field(name="Attachments", value=str(len(attachments)), inline=True)

        # Add reply info if this was a reply
        if reply_to_user and reply_to_id:
            embed.add_field(
                name="Reply To",
                value=f"{reply_to_user.mention}\n`{reply_to_user.name}` ({reply_to_id})",
                inline=True,
            )

        # Truncate content
        max_content_length = 1000
        if content:
            display_content = content[:max_content_length]
            if len(content) > max_content_length:
                display_content += "..."
            embed.add_field(name="Content", value=f"```{display_content}```", inline=False)
        else:
            embed.add_field(name="Content", value="*(No text content)*", inline=False)

        # Extract and display GIF/image URLs from content
        media_url_pattern = r'https?://[^\s]+\.(?:gif|png|jpg|jpeg|webp)(?:\?[^\s]*)?|https?://(?:tenor\.com|giphy\.com|media\.discordapp\.net|cdn\.discordapp\.com)[^\s]+'
        has_media_url = False
        if content:
            media_urls = re.findall(media_url_pattern, content, re.IGNORECASE)
            if media_urls:
                # Set the first media URL as embed image
                embed.set_image(url=media_urls[0])
                has_media_url = True

        # Set embed image from first image attachment if no URL found
        if not has_media_url and attachments:
            for att in attachments:
                if att.content_type and "image" in att.content_type:
                    embed.set_image(url=att.url)
                    break

        # Try to get attachments from cache first
        files_to_send: List[discord.File] = []
        cached_msg = self.get_cached_message(message_id) if message_id else None

        if cached_msg and cached_msg.attachments:
            # Use cached attachments
            for filename, data in cached_msg.attachments:
                file = discord.File(io.BytesIO(data), filename=filename)
                files_to_send.append(file)
        elif attachments:
            # Try to download from Discord (may fail if already deleted)
            async with aiohttp.ClientSession() as session:
                for attachment in attachments[:5]:
                    try:
                        if attachment.content_type and any(
                            t in attachment.content_type
                            for t in ["image", "video", "gif"]
                        ):
                            async with session.get(attachment.url) as resp:
                                if resp.status == 200:
                                    data = await resp.read()
                                    file = discord.File(
                                        io.BytesIO(data),
                                        filename=attachment.filename,
                                        spoiler=attachment.is_spoiler(),
                                    )
                                    files_to_send.append(file)
                    except Exception as e:
                        logger.debug(f"Mod Tracker: Failed to download attachment - {e}")

        try:
            if thread.archived:
                try:
                    await thread.edit(archived=False)
                    await asyncio.sleep(RATE_LIMIT_DELAY)
                except discord.HTTPException:
                    pass

            await thread.send(embed=embed, files=files_to_send if files_to_send else None)

            logger.tree("Mod Tracker: Message Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
                ("Attachments Saved", str(len(files_to_send))),
                ("From Cache", str(cached_msg is not None)),
            ], emoji="🗑️")

        except Exception as e:
            logger.error("Mod Tracker: Failed To Log Message Delete", [
                ("Mod ID", str(mod_id)),
                ("Error", str(e)[:50]),
            ])

        # Check for bulk action
        await self._check_bulk_action(mod_id, "delete")

    async def log_message_edit(
        self,
        mod: discord.Member,
        channel: discord.TextChannel,
        old_content: str,
        new_content: str,
        jump_url: str,
        reply_to_user: discord.User = None,
        reply_to_id: int = None,
    ) -> None:
        """Log an edited message."""
        embed = self._create_embed(
            title="✏️ Message Edited",
            color=EmbedColors.WARNING,
        )
        self._add_mod_field(embed, mod)
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)

        # Add reply info if this was a reply
        if reply_to_user and reply_to_id:
            embed.add_field(
                name="Reply To",
                value=f"{reply_to_user.mention}\n`{reply_to_user.name}` ({reply_to_id})",
                inline=True,
            )

        # Truncate content
        max_content_length = 500
        old_display = old_content[:max_content_length]
        if len(old_content) > max_content_length:
            old_display += "..."
        new_display = new_content[:max_content_length]
        if len(new_content) > max_content_length:
            new_display += "..."

        embed.add_field(
            name="Before",
            value=f"```{old_display}```" if old_display else "*(empty)*",
            inline=False,
        )
        embed.add_field(
            name="After",
            value=f"```{new_display}```" if new_display else "*(empty)*",
            inline=False,
        )

        # Create message button view
        view = MessageButtonView(jump_url)

        if await self._send_log(mod.id, embed, "Message Edit", view=view):
            logger.tree("Mod Tracker: Message Edit Logged", [
                ("Mod", mod.display_name),
                ("Channel", channel.name),
            ], emoji="✏️")

    async def log_role_change(
        self,
        mod: discord.Member,
        added_roles: List[discord.Role],
        removed_roles: List[discord.Role],
    ) -> None:
        """Log role changes."""
        embed = self._create_embed(
            title="🎭 Roles Changed",
            color=EmbedColors.INFO,
        )
        self._add_mod_field(embed, mod)

        if added_roles:
            roles_str = ", ".join([r.name for r in added_roles])
            embed.add_field(name="Added", value=f"`{roles_str}`", inline=False)

        if removed_roles:
            roles_str = ", ".join([r.name for r in removed_roles])
            embed.add_field(name="Removed", value=f"`{roles_str}`", inline=False)

        if await self._send_log(mod.id, embed, "Role Change"):
            logger.tree("Mod Tracker: Role Change Logged", [
                ("Mod", mod.display_name),
                ("Added", str(len(added_roles))),
                ("Removed", str(len(removed_roles))),
            ], emoji="🎭")

    async def log_voice_activity(
        self,
        mod: discord.Member,
        action: str,
        channel: Optional[discord.VoiceChannel] = None,
        from_channel: Optional[discord.VoiceChannel] = None,
        to_channel: Optional[discord.VoiceChannel] = None,
    ) -> None:
        """Log voice channel activity."""
        embed = self._create_embed(
            title=f"🎤 Voice: {action}",
            color=EmbedColors.INFO,
        )
        self._add_mod_field(embed, mod)

        if channel:
            embed.add_field(name="Channel", value=f"{channel.name}", inline=True)
        if from_channel:
            embed.add_field(name="From", value=f"{from_channel.name}", inline=True)
        if to_channel:
            embed.add_field(name="To", value=f"{to_channel.name}", inline=True)

        if await self._send_log(mod.id, embed, f"Voice {action}"):
            logger.tree("Mod Tracker: Voice Activity Logged", [
                ("Mod", mod.display_name),
                ("Action", action),
            ], emoji="🎤")

    # =========================================================================
    # Activity Logging - Mute/Unmute Commands
    # =========================================================================

    async def log_mute(
        self,
        mod: discord.Member,
        target: discord.Member,
        duration: str,
        reason: Optional[str] = None,
    ) -> None:
        """Log when mod mutes a user via /mute command."""
        embed = self._create_embed(
            title="🔇 Muted User",
            color=EmbedColors.ERROR,
        )
        self._add_mod_field(embed, mod)

        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=True,
        )
        embed.add_field(name="Duration", value=duration, inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        # Add target's avatar as thumbnail
        embed.set_thumbnail(url=target.display_avatar.url)

        # Check for case and add button
        view = None
        case = self.db.get_case_log(target.id)
        if case:
            embed.set_footer(text=f"Case ID: {case['case_id']}")
            view = CaseButtonView(
                guild_id=self.config.logging_guild_id or target.guild.id,
                thread_id=case["thread_id"],
                user_id=target.id,
            )

        if await self._send_log(mod.id, embed, "Mute", view=view):
            logger.tree("Mod Tracker: Mute Logged", [
                ("Mod", mod.display_name),
                ("Target", target.display_name),
                ("Duration", duration),
            ], emoji="🔇")

    async def log_unmute(
        self,
        mod: discord.Member,
        target: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        """Log when mod unmutes a user via /unmute command."""
        embed = self._create_embed(
            title="🔊 Unmuted User",
            color=EmbedColors.SUCCESS,
        )
        self._add_mod_field(embed, mod)

        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=True,
        )
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        # Add target's avatar as thumbnail
        embed.set_thumbnail(url=target.display_avatar.url)

        # Check for case and add button
        view = None
        case = self.db.get_case_log(target.id)
        if case:
            embed.set_footer(text=f"Case ID: {case['case_id']}")
            view = CaseButtonView(
                guild_id=self.config.logging_guild_id or target.guild.id,
                thread_id=case["thread_id"],
                user_id=target.id,
            )

        if await self._send_log(mod.id, embed, "Unmute", view=view):
            logger.tree("Mod Tracker: Unmute Logged", [
                ("Mod", mod.display_name),
                ("Target", target.display_name),
            ], emoji="🔊")

    async def log_warn(
        self,
        mod: discord.Member,
        target: discord.Member,
        reason: Optional[str] = None,
    ) -> None:
        """Log when mod warns a user via /warn command."""
        embed = self._create_embed(
            title="⚠️ Warned User",
            color=EmbedColors.WARNING,
        )
        self._add_mod_field(embed, mod)

        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=True,
        )
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        # Add target's avatar as thumbnail
        embed.set_thumbnail(url=target.display_avatar.url)

        # Check for case and add button
        view = None
        case = self.db.get_case_log(target.id)
        if case:
            embed.set_footer(text=f"Case ID: {case['case_id']}")
            view = CaseButtonView(
                guild_id=self.config.logging_guild_id or target.guild.id,
                thread_id=case["thread_id"],
                user_id=target.id,
            )

        if await self._send_log(mod.id, embed, "Warn", view=view):
            logger.tree("Mod Tracker: Warn Logged", [
                ("Mod", mod.display_name),
                ("Target", target.display_name),
            ], emoji="⚠️")

    async def log_management_mute_attempt(
        self,
        mod: discord.Member,
        target: discord.Member,
    ) -> None:
        """
        Secret log when a management member tries to mute another management member.

        DESIGN:
            This is a silent alert - the mod doesn't know they're being tracked.
            Only logs to their thread and pings developer.
        """
        if not self.enabled:
            return

        tracked = self.db.get_tracked_mod(mod.id)
        if not tracked:
            return

        embed = self._create_embed(
            title="🚨 Management Violation Attempt",
            color=EmbedColors.GOLD,
        )
        self._add_mod_field(embed, mod)

        embed.add_field(
            name="Attempted Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=True,
        )
        embed.add_field(
            name="Violation",
            value="Attempted to mute another management member",
            inline=False,
        )

        now = datetime.now(NY_TZ)
        embed.add_field(
            name="Time",
            value=f"<t:{int(now.timestamp())}:F>",
            inline=True,
        )

        # Add target's avatar as image
        embed.set_image(url=target.display_avatar.url)

        thread = await self._get_mod_thread(tracked["thread_id"])
        if thread:
            try:
                if thread.archived:
                    await thread.edit(archived=False)

                # Send embed first
                await thread.send(embed=embed)

                # Ping developer separately (silent alert)
                developer_ping = f"<@{self.config.developer_id}>"
                await thread.send(developer_ping)

            except Exception as e:
                logger.error("Mod Tracker: Failed To Log Management Violation", [
                    ("Mod", mod.display_name),
                    ("Error", str(e)[:50]),
                ])

    # =========================================================================
    # Mod Action Logging (Timeout/Kick/Ban)
    # =========================================================================

    async def log_timeout(
        self,
        mod_id: int,
        target: discord.Member,
        until: Optional[datetime] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Log when mod times out a member with dynamic countdown."""
        if not self.enabled:
            return

        tracked = self.db.get_tracked_mod(mod_id)
        if not tracked:
            return

        # Record action
        self._record_action(mod_id, "timeout")

        embed = self._create_embed(
            title="⏰ Timeout",
            color=EmbedColors.WARNING,
        )

        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )

        # Dynamic countdown that auto-updates
        if until:
            timestamp = int(until.timestamp())
            embed.add_field(
                name="Unmutes",
                value=f"<t:{timestamp}:R>",  # Relative (in 6 days)
                inline=True,
            )
            embed.add_field(
                name="Unmute Date",
                value=f"<t:{timestamp}:F>",  # Full date (December 28, 2025 2:09 PM)
                inline=True,
            )
        else:
            embed.add_field(name="Duration", value="Unknown", inline=True)

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        # Check for case and add button
        view = None
        case = self.db.get_case_log(target.id)
        if case:
            embed.set_footer(text=f"Case ID: {case['case_id']}")
            view = CaseButtonView(
                guild_id=self.config.logging_guild_id or target.guild.id,
                thread_id=case["thread_id"],
                user_id=target.id,
            )

        if await self._send_log(mod_id, embed, "Timeout", view=view):
            logger.tree("Mod Tracker: Timeout Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
            ], emoji="⏰")

        # Check for bulk action
        await self._check_bulk_action(mod_id, "timeout")

    async def log_kick(
        self,
        mod_id: int,
        target: discord.User,
        reason: Optional[str] = None,
    ) -> None:
        """Log when mod kicks a member."""
        await self._log_mod_action(
            mod_id=mod_id,
            action="Kick",
            emoji_icon="👢",
            target=target,
            extra_fields=[
                ("Reason", reason or "No reason provided"),
            ],
        )

    async def log_ban(
        self,
        mod_id: int,
        target: discord.User,
        reason: Optional[str] = None,
    ) -> None:
        """Log when mod bans a member."""
        # Record for suspicious pattern detection
        self._record_ban(mod_id, target.id)

        await self._log_mod_action(
            mod_id=mod_id,
            action="Ban",
            emoji_icon="🔨",
            target=target,
            extra_fields=[
                ("Reason", reason or "No reason provided"),
            ],
        )

    async def log_unban(
        self,
        mod_id: int,
        target: discord.User,
        reason: Optional[str] = None,
    ) -> None:
        """Log when mod unbans a member."""
        # Check for suspicious pattern (unbanning someone they recently banned)
        await self._check_suspicious_unban(mod_id, target.id)

        await self._log_mod_action(
            mod_id=mod_id,
            action="Unban",
            emoji_icon="🔓",
            target=target,
            extra_fields=[
                ("Reason", reason or "No reason provided"),
            ],
        )

    async def log_purge(
        self,
        mod: discord.Member,
        channel: discord.abc.GuildChannel,
        deleted_count: int,
        purge_type: str,
        reason: Optional[str] = None,
    ) -> None:
        """
        Log when mod purges messages and ping owner for review.

        Args:
            mod: The moderator who executed the purge.
            channel: The channel where messages were purged.
            deleted_count: Number of messages deleted.
            purge_type: Type of purge (e.g., "messages", "bot messages", etc.)
            reason: Optional reason for the purge.
        """
        if not self.enabled:
            return

        tracked = self.db.get_tracked_mod(mod.id)
        if not tracked:
            return

        # Record action for activity tracking
        self._record_action(mod.id, "purge")

        embed = self._create_embed(
            title="🗑️ Purged Messages",
            color=EmbedColors.WARNING,
        )
        self._add_mod_field(embed, mod)

        embed.add_field(
            name="Channel",
            value=f"{channel.mention}\n`#{channel.name}`",
            inline=True,
        )
        embed.add_field(
            name="Deleted",
            value=f"`{deleted_count}` {purge_type}",
            inline=True,
        )

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        else:
            embed.add_field(name="Reason", value="*No reason provided*", inline=False)

        thread = await self._get_mod_thread(tracked["thread_id"])
        if thread:
            try:
                if thread.archived:
                    await thread.edit(archived=False)

                # Send embed
                await thread.send(embed=embed)

                # Ping owner for review
                owner_ping = f"<@{self.config.developer_id}> Purge action - please review if needed."
                await thread.send(owner_ping)

                logger.tree("Mod Tracker: Purge Logged", [
                    ("Mod", mod.display_name),
                    ("Channel", f"#{channel.name}"),
                    ("Deleted", str(deleted_count)),
                    ("Type", purge_type),
                ], emoji="🗑️")

            except Exception as e:
                logger.error("Mod Tracker: Failed To Log Purge", [
                    ("Mod", mod.display_name),
                    ("Error", str(e)[:50]),
                ])

    async def _log_mod_action(
        self,
        mod_id: int,
        action: str,
        emoji_icon: str,
        target: discord.User,
        extra_fields: Optional[List[Tuple[str, str]]] = None,
    ) -> None:
        """Helper to log mod actions."""
        if not self.enabled:
            return

        tracked = self.db.get_tracked_mod(mod_id)
        if not tracked:
            return

        # Record action for bulk detection and inactivity tracking
        action_type = action.lower()
        self._record_action(mod_id, action_type)

        embed = self._create_embed(
            title=f"{emoji_icon} {action}",
            color=EmbedColors.WARNING,
        )

        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )

        if extra_fields:
            for name, value in extra_fields:
                embed.add_field(name=name, value=value, inline=True)

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        # Check for case and add button
        view = None
        case = self.db.get_case_log(target.id)
        if case:
            embed.set_footer(text=f"Case ID: {case['case_id']}")
            view = CaseButtonView(
                guild_id=self.config.logging_guild_id,
                thread_id=case["thread_id"],
                user_id=target.id,
            )

        if await self._send_log(mod_id, embed, action, view=view):
            logger.tree(f"Mod Tracker: {action} Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
            ], emoji=emoji_icon)

        # Check for bulk action
        await self._check_bulk_action(mod_id, action_type)

    # =========================================================================
    # Channel/Permission Logging
    # =========================================================================

    async def log_channel_create(
        self,
        mod_id: int,
        channel: discord.abc.GuildChannel,
    ) -> None:
        """Log when mod creates a channel."""
        await self._log_channel_action(mod_id, "Created", "📁", channel)

    async def log_channel_delete(
        self,
        mod_id: int,
        channel_name: str,
        channel_type: str,
    ) -> None:
        """Log when mod deletes a channel."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="🗑️ Channel Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=f"`{channel_name}`", inline=True)
        embed.add_field(name="Type", value=channel_type, inline=True)

        if await self._send_log(mod_id, embed, "Channel Delete"):
            logger.tree("Mod Tracker: Channel Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel_name),
            ], emoji="🗑️")

    async def log_channel_update(
        self,
        mod_id: int,
        channel: discord.abc.GuildChannel,
        changes: str,
    ) -> None:
        """Log when mod updates a channel."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="📝 Channel Updated",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)

        max_changes_length = 1000
        embed.add_field(
            name="Changes",
            value=changes[:max_changes_length],
            inline=False,
        )

        if await self._send_log(mod_id, embed, "Channel Update"):
            logger.tree("Mod Tracker: Channel Update Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
            ], emoji="✏️")

    async def _log_channel_action(
        self,
        mod_id: int,
        action: str,
        emoji_icon: str,
        channel: discord.abc.GuildChannel,
    ) -> None:
        """Helper to log channel actions."""
        if not self.enabled:
            return

        channel_type = type(channel).__name__.replace("Channel", "")

        embed = self._create_embed(
            title=f"{emoji_icon} Channel {action}",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Type", value=channel_type, inline=True)
        embed.add_field(name="ID", value=f"`{channel.id}`", inline=True)

        if await self._send_log(mod_id, embed, f"Channel {action}"):
            logger.tree(f"Mod Tracker: Channel {action} Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
            ], emoji=emoji_icon)

    # =========================================================================
    # Role Logging
    # =========================================================================

    async def log_role_create(
        self,
        mod_id: int,
        role: discord.Role,
    ) -> None:
        """Log when mod creates a role."""
        await self._log_role_action(mod_id, "Created", "🏷️", role)

    async def log_role_delete(
        self,
        mod_id: int,
        role_name: str,
    ) -> None:
        """Log when mod deletes a role."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="🗑️ Role Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=f"`{role_name}`", inline=True)

        if await self._send_log(mod_id, embed, "Role Delete"):
            logger.tree("Mod Tracker: Role Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Role", role_name),
            ], emoji="🗑️")

    async def log_role_update(
        self,
        mod_id: int,
        role: discord.Role,
        changes: str,
    ) -> None:
        """Log when mod updates a role."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="📝 Role Updated",
            color=role.color if role.color.value else EmbedColors.WARNING,
        )
        embed.add_field(name="Role", value=f"`{role.name}`", inline=True)

        max_changes_length = 1000
        embed.add_field(name="Changes", value=changes[:max_changes_length], inline=False)

        if await self._send_log(mod_id, embed, "Role Update"):
            logger.tree("Mod Tracker: Role Update Logged", [
                ("Mod ID", str(mod_id)),
                ("Role", role.name),
            ], emoji="✏️")

    async def _log_role_action(
        self,
        mod_id: int,
        action: str,
        emoji_icon: str,
        role: discord.Role,
    ) -> None:
        """Helper to log role actions."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title=f"{emoji_icon} Role {action}",
            color=role.color if role.color.value else EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=f"`{role.name}`", inline=True)
        embed.add_field(name="ID", value=f"`{role.id}`", inline=True)

        if await self._send_log(mod_id, embed, f"Role {action}"):
            logger.tree(f"Mod Tracker: Role {action} Logged", [
                ("Mod ID", str(mod_id)),
                ("Role", role.name),
            ], emoji=emoji_icon)

    # =========================================================================
    # Message Pin/Reaction Logging
    # =========================================================================

    async def log_message_pin(
        self,
        mod_id: int,
        channel: discord.TextChannel,
        message: discord.Message,
        pinned: bool,
    ) -> None:
        """Log when mod pins/unpins a message."""
        if not self.enabled:
            return

        action = "Pinned" if pinned else "Unpinned"
        emoji_icon = "📌" if pinned else "📍"

        embed = self._create_embed(
            title=f"{emoji_icon} Message {action}",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Author", value=f"{message.author}", inline=True)

        if message.content:
            max_content_length = 200
            content = message.content[:max_content_length]
            if len(message.content) > max_content_length:
                content += "..."
            embed.add_field(name="Content", value=f"```{content}```", inline=False)

        # Create message button view
        view = MessageButtonView(message.jump_url)

        if await self._send_log(mod_id, embed, f"Message {action}", view=view):
            logger.tree(f"Mod Tracker: Message {action} Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
            ], emoji=emoji_icon)

    # =========================================================================
    # Thread Logging
    # =========================================================================

    async def log_thread_create(
        self,
        mod_id: int,
        thread: discord.Thread,
    ) -> None:
        """Log when mod creates a thread."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="🧵 Thread Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=thread.name, inline=True)

        parent_name = "Unknown"
        if thread.parent:
            parent_name = thread.parent.name
        embed.add_field(name="Parent", value=f"#{parent_name}", inline=True)

        # Create message button view for thread
        view = MessageButtonView(thread.jump_url)

        if await self._send_log(mod_id, embed, "Thread Create", view=view):
            logger.tree("Mod Tracker: Thread Create Logged", [
                ("Mod ID", str(mod_id)),
                ("Thread", thread.name),
            ], emoji="🧵")

    async def log_thread_delete(
        self,
        mod_id: int,
        thread_name: str,
        parent_name: str,
    ) -> None:
        """Log when mod deletes a thread."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="🗑️ Thread Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=thread_name, inline=True)
        embed.add_field(name="Parent", value=f"#{parent_name}", inline=True)

        if await self._send_log(mod_id, embed, "Thread Delete"):
            logger.tree("Mod Tracker: Thread Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Thread", thread_name),
            ], emoji="🗑️")

    # =========================================================================
    # Invite Logging
    # =========================================================================

    async def log_invite_create(
        self,
        mod_id: int,
        invite: discord.Invite,
    ) -> None:
        """Log when mod creates an invite."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="🔗 Invite Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Code", value=f"`{invite.code}`", inline=True)

        channel_name = "Unknown"
        if invite.channel:
            channel_name = invite.channel.name
        embed.add_field(name="Channel", value=f"#{channel_name}", inline=True)

        max_uses = "Unlimited"
        if invite.max_uses:
            max_uses = str(invite.max_uses)
        embed.add_field(name="Max Uses", value=max_uses, inline=True)

        # Handle expiry safely
        expiry_display = "Never"
        if invite.max_age and invite.max_age > 0:
            expiry_time = datetime.now(NY_TZ) + timedelta(seconds=invite.max_age)
            expiry_display = f"<t:{int(expiry_time.timestamp())}:R>"
        embed.add_field(name="Expires", value=expiry_display, inline=True)

        if await self._send_log(mod_id, embed, "Invite Create"):
            logger.tree("Mod Tracker: Invite Create Logged", [
                ("Mod ID", str(mod_id)),
                ("Code", invite.code),
            ], emoji="🔗")

    async def log_invite_delete(
        self,
        mod_id: int,
        invite_code: str,
        channel_name: str,
    ) -> None:
        """Log when mod deletes an invite."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="🗑️ Invite Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Code", value=f"`{invite_code}`", inline=True)
        embed.add_field(name="Channel", value=f"#{channel_name}", inline=True)

        if await self._send_log(mod_id, embed, "Invite Delete"):
            logger.tree("Mod Tracker: Invite Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Code", invite_code),
            ], emoji="🗑️")

    # =========================================================================
    # Emoji/Sticker Logging
    # =========================================================================

    async def log_emoji_create(
        self,
        mod_id: int,
        emoji: discord.Emoji,
    ) -> None:
        """Log when mod creates an emoji."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="😀 Emoji Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=f"`:{emoji.name}:`", inline=True)
        embed.add_field(name="ID", value=f"`{emoji.id}`", inline=True)
        embed.set_image(url=emoji.url)

        if await self._send_log(mod_id, embed, "Emoji Create"):
            logger.tree("Mod Tracker: Emoji Create Logged", [
                ("Mod ID", str(mod_id)),
                ("Emoji", emoji.name),
            ], emoji="😀")

    async def log_emoji_delete(
        self,
        mod_id: int,
        emoji_name: str,
    ) -> None:
        """Log when mod deletes an emoji."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="🗑️ Emoji Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=f"`:{emoji_name}:`", inline=True)

        if await self._send_log(mod_id, embed, "Emoji Delete"):
            logger.tree("Mod Tracker: Emoji Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Emoji", emoji_name),
            ], emoji="🗑️")

    async def log_sticker_create(
        self,
        mod_id: int,
        sticker: discord.GuildSticker,
    ) -> None:
        """Log when mod creates a sticker."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="🏷️ Sticker Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=sticker.name, inline=True)
        embed.add_field(name="ID", value=f"`{sticker.id}`", inline=True)
        embed.set_image(url=sticker.url)

        if await self._send_log(mod_id, embed, "Sticker Create"):
            logger.tree("Mod Tracker: Sticker Create Logged", [
                ("Mod ID", str(mod_id)),
                ("Sticker", sticker.name),
            ], emoji="🎨")

    async def log_sticker_delete(
        self,
        mod_id: int,
        sticker_name: str,
    ) -> None:
        """Log when mod deletes a sticker."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="🗑️ Sticker Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=sticker_name, inline=True)

        if await self._send_log(mod_id, embed, "Sticker Delete"):
            logger.tree("Mod Tracker: Sticker Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Sticker", sticker_name),
            ], emoji="🗑️")

    # =========================================================================
    # Webhook Logging
    # =========================================================================

    async def log_webhook_create(
        self,
        mod_id: int,
        webhook_name: str,
        channel_name: str,
    ) -> None:
        """Log when mod creates a webhook."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="🔌 Webhook Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=webhook_name, inline=True)
        embed.add_field(name="Channel", value=f"#{channel_name}", inline=True)

        if await self._send_log(mod_id, embed, "Webhook Create"):
            logger.tree("Mod Tracker: Webhook Create Logged", [
                ("Mod ID", str(mod_id)),
                ("Webhook", webhook_name),
            ], emoji="🔌")

    async def log_webhook_delete(
        self,
        mod_id: int,
        webhook_name: str,
        channel_name: str,
    ) -> None:
        """Log when mod deletes a webhook."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="🗑️ Webhook Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=webhook_name, inline=True)
        embed.add_field(name="Channel", value=f"#{channel_name}", inline=True)

        if await self._send_log(mod_id, embed, "Webhook Delete"):
            logger.tree("Mod Tracker: Webhook Delete Logged", [
                ("Mod ID", str(mod_id)),
                ("Webhook", webhook_name),
            ], emoji="🗑️")

    # =========================================================================
    # Server Settings Logging
    # =========================================================================

    async def log_guild_update(
        self,
        mod_id: int,
        changes: str,
    ) -> None:
        """Log when mod changes server settings."""
        if not self.enabled:
            return

        embed = self._create_embed(
            title="⚙️ Server Settings Changed",
            color=EmbedColors.WARNING,
        )

        max_changes_length = 1000
        embed.add_field(name="Changes", value=changes[:max_changes_length], inline=False)

        if await self._send_log(mod_id, embed, "Guild Update"):
            logger.tree("Mod Tracker: Guild Update Logged", [
                ("Mod ID", str(mod_id)),
            ], emoji="⚙️")

    # =========================================================================
    # Slowmode Logging
    # =========================================================================

    async def log_slowmode_change(
        self,
        mod_id: int,
        channel: discord.TextChannel,
        old_delay: int,
        new_delay: int,
    ) -> None:
        """Log when mod changes channel slowmode."""
        if not self.enabled:
            return

        # Record action
        self._record_action(mod_id, "slowmode")

        embed = self._create_embed(
            title="🐌 Slowmode Changed",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)

        if old_delay == 0:
            old_text = "Off"
        elif old_delay < 60:
            old_text = f"{old_delay}s"
        elif old_delay < 3600:
            old_text = f"{old_delay // 60}m"
        else:
            old_text = f"{old_delay // 3600}h"

        if new_delay == 0:
            new_text = "Off"
        elif new_delay < 60:
            new_text = f"{new_delay}s"
        elif new_delay < 3600:
            new_text = f"{new_delay // 60}m"
        else:
            new_text = f"{new_delay // 3600}h"

        embed.add_field(name="Before", value=old_text, inline=True)
        embed.add_field(name="After", value=new_text, inline=True)

        if await self._send_log(mod_id, embed, "Slowmode Change"):
            logger.tree("Mod Tracker: Slowmode Change Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
                ("New Delay", new_text),
            ], emoji="🐌")

    # =========================================================================
    # AutoMod Logging
    # =========================================================================

    async def log_automod_rule_create(
        self,
        mod_id: int,
        rule_name: str,
        trigger_type: str,
    ) -> None:
        """Log when mod creates an automod rule."""
        if not self.enabled:
            return

        self._record_action(mod_id, "automod")

        embed = self._create_embed(
            title="🤖 AutoMod Rule Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Rule Name", value=rule_name, inline=True)
        embed.add_field(name="Trigger", value=trigger_type, inline=True)

        if await self._send_log(mod_id, embed, "AutoMod Create"):
            logger.tree("Mod Tracker: AutoMod Rule Created", [
                ("Mod ID", str(mod_id)),
                ("Rule", rule_name),
            ], emoji="🤖")

    async def log_automod_rule_update(
        self,
        mod_id: int,
        rule_name: str,
        changes: str,
    ) -> None:
        """Log when mod updates an automod rule."""
        if not self.enabled:
            return

        self._record_action(mod_id, "automod")

        embed = self._create_embed(
            title="📝 AutoMod Rule Updated",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Rule Name", value=rule_name, inline=True)
        embed.add_field(name="Changes", value=changes[:500], inline=False)

        if await self._send_log(mod_id, embed, "AutoMod Update"):
            logger.tree("Mod Tracker: AutoMod Rule Updated", [
                ("Mod ID", str(mod_id)),
                ("Rule", rule_name),
            ], emoji="🤖")

    async def log_automod_rule_delete(
        self,
        mod_id: int,
        rule_name: str,
    ) -> None:
        """Log when mod deletes an automod rule."""
        if not self.enabled:
            return

        self._record_action(mod_id, "automod")

        embed = self._create_embed(
            title="🗑️ AutoMod Rule Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Rule Name", value=rule_name, inline=True)

        if await self._send_log(mod_id, embed, "AutoMod Delete"):
            logger.tree("Mod Tracker: AutoMod Rule Deleted", [
                ("Mod ID", str(mod_id)),
                ("Rule", rule_name),
            ], emoji="🗑️")

    # =========================================================================
    # User Nickname Change Logging
    # =========================================================================

    async def log_nickname_change(
        self,
        mod_id: int,
        target: discord.Member,
        old_nick: Optional[str],
        new_nick: Optional[str],
    ) -> None:
        """Log when mod changes another user's nickname."""
        if not self.enabled:
            return

        self._record_action(mod_id, "nickname")

        embed = self._create_embed(
            title="✏️ Nickname Changed",
            color=EmbedColors.WARNING,
        )
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )
        embed.add_field(name="Before", value=old_nick or "*(none)*", inline=True)
        embed.add_field(name="After", value=new_nick or "*(none)*", inline=True)

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, "Nickname Change"):
            logger.tree("Mod Tracker: Nickname Change Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
            ], emoji="✏️")

    # =========================================================================
    # Voice Channel Move Logging
    # =========================================================================

    async def log_voice_move(
        self,
        mod_id: int,
        target: discord.Member,
        from_channel: discord.VoiceChannel,
        to_channel: discord.VoiceChannel,
    ) -> None:
        """Log when mod moves a user between voice channels."""
        if not self.enabled:
            return

        self._record_action(mod_id, "voice_move")

        embed = self._create_embed(
            title="🔀 User Moved (Voice)",
            color=EmbedColors.WARNING,
        )
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )
        embed.add_field(name="From", value=f"🔊 {from_channel.name}", inline=True)
        embed.add_field(name="To", value=f"🔊 {to_channel.name}", inline=True)

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, "Voice Move"):
            logger.tree("Mod Tracker: Voice Move Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
                ("To", to_channel.name),
            ], emoji="🔊")

    # =========================================================================
    # Bulk Message Purge Logging
    # =========================================================================

    async def log_message_purge(
        self,
        mod_id: int,
        channel: discord.TextChannel,
        count: int,
    ) -> None:
        """Log when mod purges/bulk deletes messages."""
        if not self.enabled:
            return

        self._record_action(mod_id, "purge")

        embed = self._create_embed(
            title="🧹 Messages Purged",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Count", value=f"**{count}** messages", inline=True)

        if await self._send_log(mod_id, embed, "Message Purge"):
            logger.tree("Mod Tracker: Message Purge Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
                ("Count", str(count)),
            ], emoji="🧹")

    # =========================================================================
    # User Role Change Logging
    # =========================================================================

    async def log_role_assign(
        self,
        mod_id: int,
        target: discord.Member,
        role: discord.Role,
        action: str,  # "added" or "removed"
    ) -> None:
        """Log when mod adds/removes a role from a user."""
        if not self.enabled:
            return

        self._record_action(mod_id, "role_assign")

        if action == "added":
            title = "Role Added to User"
            color = EmbedColors.INFO
            emoji = "➕"
        else:
            title = "Role Removed from User"
            color = EmbedColors.ERROR
            emoji = "➖"

        embed = self._create_embed(
            title=title,
            color=color,
        )
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )
        embed.add_field(name="Role", value=f"{role.mention} (`{role.name}`)", inline=True)

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, f"Role {action.title()}"):
            logger.tree(f"Mod Tracker: Role {action.title()} Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
                ("Role", role.name),
            ], emoji=emoji)

    # =========================================================================
    # Voice Moderation Logging
    # =========================================================================

    async def log_voice_mute_deafen(
        self,
        mod_id: int,
        target: discord.Member,
        action: str,  # "muted", "unmuted", "deafened", "undeafened"
    ) -> None:
        """Log when mod server mutes/deafens a user."""
        if not self.enabled:
            return

        self._record_action(mod_id, "voice_mod")

        emoji_map = {
            "muted": "🔇",
            "unmuted": "🔊",
            "deafened": "🔇",
            "undeafened": "🔊",
        }
        color = EmbedColors.ERROR if action in ["muted", "deafened"] else EmbedColors.SUCCESS

        embed = self._create_embed(
            title=f"User {action.title()} (Voice)",
            color=color,
        )
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, f"Voice {action.title()}"):
            logger.tree(f"Mod Tracker: Voice {action.title()} Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
            ], emoji=emoji_map.get(action, "🔊"))

    async def log_voice_disconnect(
        self,
        mod_id: int,
        target: discord.Member,
        channel_name: str,
    ) -> None:
        """Log when mod disconnects a user from voice."""
        if not self.enabled:
            return

        self._record_action(mod_id, "voice_disconnect")

        embed = self._create_embed(
            title="🔌 User Disconnected (Voice)",
            color=EmbedColors.ERROR,
        )
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=False,
        )
        embed.add_field(name="From Channel", value=f"🔊 {channel_name}", inline=True)

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, "Voice Disconnect"):
            logger.tree("Mod Tracker: Voice Disconnect Logged", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
            ], emoji="🔌")

    # =========================================================================
    # Channel Permission Overwrite Logging
    # =========================================================================

    async def log_permission_overwrite(
        self,
        mod_id: int,
        channel: discord.abc.GuildChannel,
        target: str,  # Role or user name
        target_type: str,  # "role" or "member"
        action: str,  # "added", "updated", "removed"
    ) -> None:
        """Log when mod changes channel permission overwrites."""
        if not self.enabled:
            return

        self._record_action(mod_id, "permission")

        # Track for mass permission change detection
        self._record_permission_change(mod_id)

        color_map = {
            "added": EmbedColors.INFO,
            "updated": EmbedColors.WARNING,
            "removed": EmbedColors.ERROR,
        }

        embed = self._create_embed(
            title=f"Permission Overwrite {action.title()}",
            color=color_map.get(action, EmbedColors.WARNING),
        )
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Target", value=target, inline=True)
        embed.add_field(name="Type", value=target_type.title(), inline=True)

        if await self._send_log(mod_id, embed, f"Permission {action.title()}"):
            logger.tree(f"Mod Tracker: Permission {action.title()} Logged", [
                ("Mod ID", str(mod_id)),
                ("Channel", channel.name),
                ("Target", target),
            ], emoji="🔐")

        # Check for mass permission changes
        await self._check_mass_permission_change(mod_id)

    # =========================================================================
    # Sticker Logging
    # =========================================================================

    async def log_sticker_create(
        self,
        mod_id: int,
        sticker_name: str,
    ) -> None:
        """Log when mod creates a sticker."""
        if not self.enabled:
            return

        self._record_action(mod_id, "sticker")

        embed = self._create_embed(
            title="🏷️ Sticker Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=sticker_name, inline=True)

        if await self._send_log(mod_id, embed, "Sticker Create"):
            logger.tree("Mod Tracker: Sticker Created", [
                ("Mod ID", str(mod_id)),
                ("Sticker", sticker_name),
            ], emoji="🎨")

    async def log_sticker_delete(
        self,
        mod_id: int,
        sticker_name: str,
    ) -> None:
        """Log when mod deletes a sticker."""
        if not self.enabled:
            return

        self._record_action(mod_id, "sticker")

        embed = self._create_embed(
            title="🗑️ Sticker Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=sticker_name, inline=True)

        if await self._send_log(mod_id, embed, "Sticker Delete"):
            logger.tree("Mod Tracker: Sticker Deleted", [
                ("Mod ID", str(mod_id)),
                ("Sticker", sticker_name),
            ], emoji="🗑️")

    # =========================================================================
    # Scheduled Event Logging
    # =========================================================================

    async def log_event_create(
        self,
        mod_id: int,
        event_name: str,
        event_type: str,
    ) -> None:
        """Log when mod creates a scheduled event."""
        if not self.enabled:
            return

        self._record_action(mod_id, "event")

        embed = self._create_embed(
            title="📅 Scheduled Event Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=event_name, inline=True)
        embed.add_field(name="Type", value=event_type, inline=True)

        if await self._send_log(mod_id, embed, "Event Create"):
            logger.tree("Mod Tracker: Event Created", [
                ("Mod ID", str(mod_id)),
                ("Event", event_name),
            ], emoji="📅")

    async def log_event_update(
        self,
        mod_id: int,
        event_name: str,
    ) -> None:
        """Log when mod updates a scheduled event."""
        if not self.enabled:
            return

        self._record_action(mod_id, "event")

        embed = self._create_embed(
            title="📝 Scheduled Event Updated",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Name", value=event_name, inline=True)

        if await self._send_log(mod_id, embed, "Event Update"):
            logger.tree("Mod Tracker: Event Updated", [
                ("Mod ID", str(mod_id)),
                ("Event", event_name),
            ], emoji="📅")

    async def log_event_delete(
        self,
        mod_id: int,
        event_name: str,
    ) -> None:
        """Log when mod deletes a scheduled event."""
        if not self.enabled:
            return

        self._record_action(mod_id, "event")

        embed = self._create_embed(
            title="🗑️ Scheduled Event Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=event_name, inline=True)

        if await self._send_log(mod_id, embed, "Event Delete"):
            logger.tree("Mod Tracker: Event Deleted", [
                ("Mod ID", str(mod_id)),
                ("Event", event_name),
            ], emoji="🗑️")

    # =========================================================================
    # Command Usage Logging
    # =========================================================================

    async def log_command_usage(
        self,
        mod_id: int,
        command_name: str,
        target: Optional[discord.User] = None,
        extra_info: Optional[str] = None,
    ) -> None:
        """Log when mod uses a bot command."""
        if not self.enabled:
            return

        self._record_action(mod_id, "command")

        embed = self._create_embed(
            title="⚡ Command Used",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Command", value=f"`/{command_name}`", inline=True)

        if target:
            embed.add_field(
                name="Target",
                value=f"{target.mention}\n`{target.name}` ({target.id})",
                inline=True,
            )

        if extra_info:
            embed.add_field(name="Details", value=extra_info, inline=False)

        if await self._send_log(mod_id, embed, "Command Usage"):
            logger.debug(f"Mod Tracker: Command Usage Logged - {mod_id} used /{command_name}")

    # =========================================================================
    # Mod Notes
    # =========================================================================

    async def add_mod_note(
        self,
        mod_id: int,
        note: str,
        added_by: discord.User,
    ) -> bool:
        """Add a note to a mod's tracking thread."""
        if not self.enabled:
            return False

        tracked = self.db.get_tracked_mod(mod_id)
        if not tracked:
            return False

        thread = await self._get_mod_thread(tracked["thread_id"])
        if not thread:
            return False

        embed = self._create_embed(
            title="📝 Mod Note Added",
            color=EmbedColors.GREEN,
        )
        embed.add_field(name="Note", value=note, inline=False)
        embed.add_field(name="Added By", value=f"{added_by.mention}\n`{added_by.display_name}`", inline=True)

        try:
            if thread.archived:
                await thread.edit(archived=False)
                await asyncio.sleep(RATE_LIMIT_DELAY)

            await thread.send(embed=embed)

            logger.tree("Mod Tracker: Note Added", [
                ("Mod ID", str(mod_id)),
                ("By", str(added_by)),
            ], emoji="📝")

            return True
        except Exception as e:
            logger.error("Mod Tracker: Failed To Add Note", [
                ("Mod ID", str(mod_id)),
                ("Error", str(e)[:50]),
            ])
            return False

    # =========================================================================
    # Security Alerts
    # =========================================================================

    async def alert_dm_attempt(
        self,
        mod_id: int,
        message_content: str,
    ) -> None:
        """Alert when tracked mod DMs the bot."""
        if not self.enabled:
            return

        await self._send_alert(
            mod_id=mod_id,
            alert_type="DM Attempt",
            description=f"Mod attempted to DM the bot.\n\n**Message:**\n```{message_content[:500]}```",
            color=EmbedColors.WARNING,
        )

        logger.tree("Mod Tracker: DM Attempt Alert", [
            ("Mod ID", str(mod_id)),
        ], emoji="⚠️")

    async def alert_self_role_change(
        self,
        mod_id: int,
        role: discord.Role,
        action: str,  # "added" or "removed"
    ) -> None:
        """Alert when mod changes their own roles (potential self-elevation)."""
        if not self.enabled:
            return

        description = f"Mod {action} a role to/from themselves.\n\n**Role:** {role.mention} (`{role.name}`)"

        if role.permissions.administrator or role.permissions.manage_guild:
            description += "\n\n**⚠️ This role has elevated permissions!**"

        await self._send_alert(
            mod_id=mod_id,
            alert_type="Self Role Change",
            description=description,
            color=EmbedColors.ERROR,
        )

        logger.tree("Mod Tracker: Self Role Change Alert", [
            ("Mod ID", str(mod_id)),
            ("Role", role.name),
            ("Action", action),
        ], emoji="🚨")

    # =========================================================================
    # Suspicious Pattern Detection
    # =========================================================================

    def _record_ban(self, mod_id: int, target_id: int) -> None:
        """Record a ban for suspicious pattern detection."""
        now = datetime.now(NY_TZ)
        self._ban_history[mod_id][target_id] = now

        # Clean old entries
        cutoff = now - timedelta(seconds=BAN_HISTORY_TTL)
        self._ban_history[mod_id] = {
            tid: t for tid, t in self._ban_history[mod_id].items()
            if t > cutoff
        }

    async def _check_suspicious_unban(self, mod_id: int, target_id: int) -> None:
        """Check if this unban is suspicious (unbanning someone they recently banned)."""
        if target_id not in self._ban_history[mod_id]:
            return

        ban_time = self._ban_history[mod_id][target_id]
        now = datetime.now(NY_TZ)
        time_since_ban = (now - ban_time).total_seconds()

        if time_since_ban <= SUSPICIOUS_UNBAN_WINDOW:
            minutes = int(time_since_ban / 60)
            await self._send_alert(
                mod_id=mod_id,
                alert_type="Suspicious Unban Pattern",
                description=f"Mod unbanned a user they banned **{minutes} minutes ago**.\n\n"
                           f"**Target ID:** `{target_id}`\n"
                           f"**Banned at:** <t:{int(ban_time.timestamp())}:R>\n\n"
                           f"This could indicate:\n"
                           f"• Accidental ban/unban\n"
                           f"• Pressure to unban\n"
                           f"• Abuse of mod powers",
                color=EmbedColors.ERROR,
            )

            # Remove from history after alerting
            del self._ban_history[mod_id][target_id]

            logger.tree("Mod Tracker: Suspicious Unban Alert", [
                ("Mod ID", str(mod_id)),
                ("Target ID", str(target_id)),
                ("Minutes Since Ban", str(minutes)),
            ], emoji="🚨")

    # =========================================================================
    # Mass Permission Change Detection
    # =========================================================================

    def _record_permission_change(self, mod_id: int) -> None:
        """Record a permission change for mass detection."""
        now = datetime.now(NY_TZ)
        self._permission_changes[mod_id].append(now)

        # Clean old entries
        cutoff = now - timedelta(seconds=MASS_PERMISSION_WINDOW)
        self._permission_changes[mod_id] = [
            t for t in self._permission_changes[mod_id] if t > cutoff
        ]

    async def _check_mass_permission_change(self, mod_id: int) -> None:
        """Check if mod is making mass permission changes."""
        count = len(self._permission_changes[mod_id])

        if count >= MASS_PERMISSION_THRESHOLD:
            await self._send_alert(
                mod_id=mod_id,
                alert_type="Mass Permission Changes",
                description=f"Mod changed permissions on **{count}** channels in the last 5 minutes.\n\n"
                           f"This could indicate:\n"
                           f"• Server restructuring\n"
                           f"• Potential lockdown attempt\n"
                           f"• Permission abuse",
                color=EmbedColors.ERROR,
            )

            # Clear after alerting to avoid spam
            self._permission_changes[mod_id].clear()

            logger.tree("Mod Tracker: Mass Permission Alert", [
                ("Mod ID", str(mod_id)),
                ("Count", str(count)),
            ], emoji="🚨")

    # =========================================================================
    # Stage Channel Moderation
    # =========================================================================

    async def log_stage_speaker(
        self,
        mod_id: int,
        target: discord.Member,
        stage_channel: discord.StageChannel,
        action: str,  # "added" or "removed"
    ) -> None:
        """Log when mod adds/removes a stage speaker."""
        if not self.enabled:
            return

        self._record_action(mod_id, "stage")

        if action == "added":
            title = "Stage Speaker Added"
            color = EmbedColors.SUCCESS
        else:
            title = "Stage Speaker Removed"
            color = EmbedColors.ERROR

        embed = self._create_embed(title=title, color=color)
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=True,
        )
        embed.add_field(name="Stage", value=f"🎭 {stage_channel.name}", inline=True)

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, f"Stage Speaker {action.title()}"):
            logger.tree(f"Mod Tracker: Stage Speaker {action.title()}", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
                ("Stage", stage_channel.name),
            ], emoji="🎭")

    async def log_stage_topic_change(
        self,
        mod_id: int,
        stage_channel: discord.StageChannel,
        old_topic: Optional[str],
        new_topic: Optional[str],
    ) -> None:
        """Log when mod changes stage topic."""
        if not self.enabled:
            return

        self._record_action(mod_id, "stage")

        embed = self._create_embed(
            title="🎙️ Stage Topic Changed",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Stage", value=f"🎭 {stage_channel.name}", inline=True)
        embed.add_field(name="Before", value=old_topic or "*(none)*", inline=False)
        embed.add_field(name="After", value=new_topic or "*(none)*", inline=False)

        if await self._send_log(mod_id, embed, "Stage Topic Change"):
            logger.tree("Mod Tracker: Stage Topic Changed", [
                ("Mod ID", str(mod_id)),
                ("Stage", stage_channel.name),
            ], emoji="🎭")

    # =========================================================================
    # Forum Tag Changes
    # =========================================================================

    async def log_forum_tag_create(
        self,
        mod_id: int,
        forum: discord.ForumChannel,
        tag_name: str,
    ) -> None:
        """Log when mod creates a forum tag."""
        if not self.enabled:
            return

        self._record_action(mod_id, "forum_tag")

        embed = self._create_embed(
            title="🏷️ Forum Tag Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Forum", value=f"#{forum.name}", inline=True)
        embed.add_field(name="Tag", value=f"`{tag_name}`", inline=True)

        if await self._send_log(mod_id, embed, "Forum Tag Create"):
            logger.tree("Mod Tracker: Forum Tag Created", [
                ("Mod ID", str(mod_id)),
                ("Forum", forum.name),
                ("Tag", tag_name),
            ], emoji="🏷️")

    async def log_forum_tag_delete(
        self,
        mod_id: int,
        forum: discord.ForumChannel,
        tag_name: str,
    ) -> None:
        """Log when mod deletes a forum tag."""
        if not self.enabled:
            return

        self._record_action(mod_id, "forum_tag")

        embed = self._create_embed(
            title="🗑️ Forum Tag Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Forum", value=f"#{forum.name}", inline=True)
        embed.add_field(name="Tag", value=f"`{tag_name}`", inline=True)

        if await self._send_log(mod_id, embed, "Forum Tag Delete"):
            logger.tree("Mod Tracker: Forum Tag Deleted", [
                ("Mod ID", str(mod_id)),
                ("Forum", forum.name),
                ("Tag", tag_name),
            ], emoji="🗑️")

    async def log_forum_tag_update(
        self,
        mod_id: int,
        forum: discord.ForumChannel,
        old_name: str,
        new_name: str,
    ) -> None:
        """Log when mod updates a forum tag."""
        if not self.enabled:
            return

        self._record_action(mod_id, "forum_tag")

        embed = self._create_embed(
            title="📝 Forum Tag Updated",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Forum", value=f"#{forum.name}", inline=True)
        embed.add_field(name="Before", value=f"`{old_name}`", inline=True)
        embed.add_field(name="After", value=f"`{new_name}`", inline=True)

        if await self._send_log(mod_id, embed, "Forum Tag Update"):
            logger.tree("Mod Tracker: Forum Tag Updated", [
                ("Mod ID", str(mod_id)),
                ("Forum", forum.name),
            ], emoji="✏️")

    # =========================================================================
    # Integration/Bot Tracking
    # =========================================================================

    async def log_integration_create(
        self,
        mod_id: int,
        integration_name: str,
        integration_type: str,
    ) -> None:
        """Log when mod adds an integration/bot."""
        if not self.enabled:
            return

        self._record_action(mod_id, "integration")

        embed = self._create_embed(
            title="🔗 Integration Added",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=integration_name, inline=True)
        embed.add_field(name="Type", value=integration_type, inline=True)

        if await self._send_log(mod_id, embed, "Integration Create"):
            logger.tree("Mod Tracker: Integration Added", [
                ("Mod ID", str(mod_id)),
                ("Integration", integration_name),
            ], emoji="🤖")

    async def log_integration_delete(
        self,
        mod_id: int,
        integration_name: str,
    ) -> None:
        """Log when mod removes an integration/bot."""
        if not self.enabled:
            return

        self._record_action(mod_id, "integration")

        embed = self._create_embed(
            title="🗑️ Integration Removed",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=integration_name, inline=True)

        if await self._send_log(mod_id, embed, "Integration Delete"):
            logger.tree("Mod Tracker: Integration Removed", [
                ("Mod ID", str(mod_id)),
                ("Integration", integration_name),
            ], emoji="🗑️")

    async def log_bot_add(
        self,
        mod_id: int,
        bot: discord.Member,
    ) -> None:
        """Log when mod adds a bot to the server."""
        if not self.enabled:
            return

        self._record_action(mod_id, "bot")

        embed = self._create_embed(
            title="🤖 Bot Added",
            color=EmbedColors.WARNING,
        )
        embed.add_field(
            name="Bot",
            value=f"{bot.mention}\n`{bot.name}` ({bot.id})",
            inline=True,
        )

        if bot.avatar:
            embed.set_thumbnail(url=bot.display_avatar.url)

        if await self._send_log(mod_id, embed, "Bot Add"):
            logger.tree("Mod Tracker: Bot Added", [
                ("Mod ID", str(mod_id)),
                ("Bot", str(bot)),
                ("Bot ID", str(bot.id)),
            ], emoji="🤖")

    async def log_bot_remove(
        self,
        mod_id: int,
        bot_name: str,
        bot_id: int,
    ) -> None:
        """Log when mod removes a bot from the server."""
        if not self.enabled:
            return

        self._record_action(mod_id, "bot")

        embed = self._create_embed(
            title="🗑️ Bot Removed",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Bot", value=f"`{bot_name}` ({bot_id})", inline=True)

        if await self._send_log(mod_id, embed, "Bot Remove"):
            logger.tree("Mod Tracker: Bot Removed", [
                ("Mod ID", str(mod_id)),
                ("Bot", bot_name),
                ("Bot ID", str(bot_id)),
            ], emoji="🗑️")

    # =========================================================================
    # Timeout Removal Tracking
    # =========================================================================

    async def log_timeout_remove(
        self,
        mod_id: int,
        target: discord.Member,
        original_until: Optional[datetime] = None,
    ) -> None:
        """Log when mod removes a timeout early."""
        if not self.enabled:
            return

        self._record_action(mod_id, "timeout_remove")

        embed = self._create_embed(
            title="⏰ Timeout Removed Early",
            color=EmbedColors.WARNING,
        )
        embed.add_field(
            name="Target",
            value=f"{target.mention}\n`{target.name}` ({target.id})",
            inline=True,
        )

        if original_until:
            embed.add_field(
                name="Was Until",
                value=f"<t:{int(original_until.timestamp())}:R>",
                inline=True,
            )

        if hasattr(target, 'display_avatar'):
            embed.set_thumbnail(url=target.display_avatar.url)

        if await self._send_log(mod_id, embed, "Timeout Remove"):
            logger.tree("Mod Tracker: Timeout Removed", [
                ("Mod ID", str(mod_id)),
                ("Target", str(target)),
            ], emoji="⏰")

    # =========================================================================
    # Prune Tracking
    # =========================================================================

    async def log_member_prune(
        self,
        mod_id: int,
        days: int,
        members_removed: int,
    ) -> None:
        """Log when mod prunes inactive members."""
        if not self.enabled:
            return

        self._record_action(mod_id, "prune")

        embed = self._create_embed(
            title="🧹 Member Prune",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Inactive Days", value=f"{days} days", inline=True)
        embed.add_field(name="Members Removed", value=f"**{members_removed}**", inline=True)

        # Alert about large prunes
        if members_removed >= 50:
            embed.add_field(
                name="⚠️ Warning",
                value="Large prune operation detected!",
                inline=False,
            )

        if await self._send_log(mod_id, embed, "Member Prune"):
            logger.tree("Mod Tracker: Member Prune", [
                ("Mod ID", str(mod_id)),
                ("Days", str(days)),
                ("Removed", str(members_removed)),
            ], emoji="🧹")

        # Alert for large prunes
        if members_removed >= 50:
            await self._send_alert(
                mod_id=mod_id,
                alert_type="Large Member Prune",
                description=f"Mod pruned **{members_removed}** members (inactive for {days}+ days).\n\n"
                           f"This is a significant action that removed many members.",
                color=EmbedColors.ERROR,
            )

    # =========================================================================
    # Server Settings Tracking
    # =========================================================================

    async def log_verification_level_change(
        self,
        mod_id: int,
        old_level: str,
        new_level: str,
    ) -> None:
        """Log when mod changes server verification level."""
        if not self.enabled:
            return

        self._record_action(mod_id, "server_settings")

        embed = self._create_embed(
            title="🔒 Verification Level Changed",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Before", value=old_level, inline=True)
        embed.add_field(name="After", value=new_level, inline=True)

        if await self._send_log(mod_id, embed, "Verification Level"):
            logger.tree("Mod Tracker: Verification Level Changed", [
                ("Mod ID", str(mod_id)),
                ("New Level", new_level),
            ], emoji="🔒")

    async def log_explicit_filter_change(
        self,
        mod_id: int,
        old_filter: str,
        new_filter: str,
    ) -> None:
        """Log when mod changes explicit content filter."""
        if not self.enabled:
            return

        self._record_action(mod_id, "server_settings")

        embed = self._create_embed(
            title="🔞 Explicit Content Filter Changed",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Before", value=old_filter, inline=True)
        embed.add_field(name="After", value=new_filter, inline=True)

        if await self._send_log(mod_id, embed, "Explicit Filter"):
            logger.tree("Mod Tracker: Explicit Filter Changed", [
                ("Mod ID", str(mod_id)),
                ("New Filter", new_filter),
            ], emoji="🔞")

    async def log_2fa_requirement_change(
        self,
        mod_id: int,
        enabled: bool,
    ) -> None:
        """Log when mod changes 2FA requirement for moderation."""
        if not self.enabled:
            return

        self._record_action(mod_id, "server_settings")

        status = "Enabled" if enabled else "Disabled"
        color = EmbedColors.SUCCESS if enabled else EmbedColors.ERROR

        embed = self._create_embed(
            title="🔐 Mod 2FA Requirement Changed",
            color=color,
        )
        embed.add_field(name="Status", value=f"**{status}**", inline=True)

        if not enabled:
            embed.add_field(
                name="⚠️ Warning",
                value="Disabling 2FA requirement reduces server security!",
                inline=False,
            )

        if await self._send_log(mod_id, embed, "2FA Requirement"):
            logger.tree("Mod Tracker: 2FA Requirement Changed", [
                ("Mod ID", str(mod_id)),
                ("Status", status),
            ], emoji="🔐")

        # Alert if 2FA is disabled
        if not enabled:
            await self._send_alert(
                mod_id=mod_id,
                alert_type="2FA Requirement Disabled",
                description="Mod disabled the 2FA requirement for moderation actions.\n\n"
                           "This reduces server security and allows mods without 2FA to take actions.",
                color=EmbedColors.ERROR,
            )

    # =========================================================================
    # Soundboard Tracking
    # =========================================================================

    async def log_soundboard_create(
        self,
        mod_id: int,
        sound_name: str,
    ) -> None:
        """Log when mod creates a soundboard sound."""
        if not self.enabled:
            return

        self._record_action(mod_id, "soundboard")

        embed = self._create_embed(
            title="🔊 Soundboard Sound Created",
            color=EmbedColors.INFO,
        )
        embed.add_field(name="Name", value=f"`{sound_name}`", inline=True)

        if await self._send_log(mod_id, embed, "Sound Create"):
            logger.tree("Mod Tracker: Sound Created", [
                ("Mod ID", str(mod_id)),
                ("Sound", sound_name),
            ], emoji="🔊")

    async def log_soundboard_delete(
        self,
        mod_id: int,
        sound_name: str,
    ) -> None:
        """Log when mod deletes a soundboard sound."""
        if not self.enabled:
            return

        self._record_action(mod_id, "soundboard")

        embed = self._create_embed(
            title="🗑️ Soundboard Sound Deleted",
            color=EmbedColors.ERROR,
        )
        embed.add_field(name="Name", value=f"`{sound_name}`", inline=True)

        if await self._send_log(mod_id, embed, "Sound Delete"):
            logger.tree("Mod Tracker: Sound Deleted", [
                ("Mod ID", str(mod_id)),
                ("Sound", sound_name),
            ], emoji="🗑️")

    async def log_soundboard_update(
        self,
        mod_id: int,
        sound_name: str,
        changes: str,
    ) -> None:
        """Log when mod updates a soundboard sound."""
        if not self.enabled:
            return

        self._record_action(mod_id, "soundboard")

        embed = self._create_embed(
            title="📝 Soundboard Sound Updated",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Name", value=f"`{sound_name}`", inline=True)
        embed.add_field(name="Changes", value=changes, inline=False)

        if await self._send_log(mod_id, embed, "Sound Update"):
            logger.tree("Mod Tracker: Sound Updated", [
                ("Mod ID", str(mod_id)),
                ("Sound", sound_name),
            ], emoji="✏️")

    # =========================================================================
    # Onboarding Tracking
    # =========================================================================

    async def log_onboarding_create(
        self,
        mod_id: int,
    ) -> None:
        """Log when mod creates/enables onboarding."""
        if not self.enabled:
            return

        self._record_action(mod_id, "onboarding")

        embed = self._create_embed(
            title="✅ Onboarding Enabled",
            color=EmbedColors.INFO,
        )
        embed.add_field(
            name="Description",
            value="Server onboarding has been enabled.",
            inline=False,
        )

        if await self._send_log(mod_id, embed, "Onboarding Create"):
            logger.tree("Mod Tracker: Onboarding Enabled", [
                ("Mod ID", str(mod_id)),
            ], emoji="👋")

    async def log_onboarding_update(
        self,
        mod_id: int,
        changes: str,
    ) -> None:
        """Log when mod updates onboarding settings."""
        if not self.enabled:
            return

        self._record_action(mod_id, "onboarding")

        embed = self._create_embed(
            title="📝 Onboarding Updated",
            color=EmbedColors.WARNING,
        )
        embed.add_field(name="Changes", value=changes[:500], inline=False)

        if await self._send_log(mod_id, embed, "Onboarding Update"):
            logger.tree("Mod Tracker: Onboarding Updated", [
                ("Mod ID", str(mod_id)),
            ], emoji="✏️")

    async def log_onboarding_delete(
        self,
        mod_id: int,
    ) -> None:
        """Log when mod disables onboarding."""
        if not self.enabled:
            return

        self._record_action(mod_id, "onboarding")

        embed = self._create_embed(
            title="❌ Onboarding Disabled",
            color=EmbedColors.ERROR,
        )
        embed.add_field(
            name="Description",
            value="Server onboarding has been disabled.",
            inline=False,
        )

        if await self._send_log(mod_id, embed, "Onboarding Delete"):
            logger.tree("Mod Tracker: Onboarding Disabled", [
                ("Mod ID", str(mod_id)),
            ], emoji="🗑️")

    # =========================================================================
    # Role Icon Tracking
    # =========================================================================

    async def log_role_icon_change(
        self,
        mod_id: int,
        role: discord.Role,
        action: str,  # "added", "changed", "removed"
    ) -> None:
        """Log when mod changes a role's icon."""
        if not self.enabled:
            return

        self._record_action(mod_id, "role_icon")

        color_map = {
            "added": EmbedColors.INFO,
            "changed": EmbedColors.WARNING,
            "removed": EmbedColors.ERROR,
        }

        embed = self._create_embed(
            title=f"Role Icon {action.title()}",
            color=color_map.get(action, EmbedColors.WARNING),
        )
        embed.add_field(name="Role", value=f"{role.mention} (`{role.name}`)", inline=True)

        # Show new icon if available
        if role.icon and action != "removed":
            embed.set_thumbnail(url=role.icon.url)

        if await self._send_log(mod_id, embed, f"Role Icon {action.title()}"):
            logger.tree(f"Mod Tracker: Role Icon {action.title()}", [
                ("Mod ID", str(mod_id)),
                ("Role", role.name),
            ], emoji="🎨")


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["ModTrackerService"]
