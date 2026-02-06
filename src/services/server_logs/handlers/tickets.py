"""
AzabBot - Tickets Handler
=========================

Handles ticket logging.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional
import io

import discord

from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.database import get_db
from src.core.logger import logger
from src.utils.footer import set_footer

if TYPE_CHECKING:
    from ..service import LoggingService


class TicketsLogsMixin:
    """Mixin for ticket logging."""

    async def log_ticket_created(
        self: "LoggingService",
        ticket_id: str,
        user: discord.User,
        category: str,
        subject: str,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log a ticket creation."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import TicketLogView, UserIdButton

        embed = self._create_embed(
            "🎫 Ticket Created",
            EmbedColors.SUCCESS,
            category="Ticket",
            user_id=user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="User", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Subject", value=subject[:200] if subject else "No subject", inline=False)
        self._set_user_thumbnail(embed, user)

        view = TicketLogView(guild_id, thread_id)
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_claimed(
        self: "LoggingService",
        ticket_id: str,
        user: discord.User,
        staff: discord.Member,
        category: str,
        thread_id: int,
        guild_id: int,
        created_at: float,
    ) -> None:
        """Log a ticket claim."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import TicketLogView, UserIdButton
        import time

        response_seconds = int(time.time() - created_at)
        if response_seconds < 60:
            response_time = f"{response_seconds}s"
        elif response_seconds < 3600:
            response_time = f"{response_seconds // 60}m {response_seconds % 60}s"
        elif response_seconds < 86400:
            hours = response_seconds // 3600
            mins = (response_seconds % 3600) // 60
            response_time = f"{hours}h {mins}m"
        else:
            days = response_seconds // 86400
            hours = (response_seconds % 86400) // 3600
            response_time = f"{days}d {hours}h"

        embed = self._create_embed(
            "✋ Ticket Claimed",
            EmbedColors.GOLD,
            category="Ticket",
            user_id=user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Response Time", value=f"⏱️ {response_time}", inline=True)
        embed.add_field(name="Opened By", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Claimed By", value=self._format_user_field(staff), inline=True)
        self._set_user_thumbnail(embed, staff)

        view = TicketLogView(guild_id, thread_id)
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_closed(
        self: "LoggingService",
        ticket_id: str,
        user: discord.User,
        closed_by: discord.Member,
        category: str,
        thread_id: int,
        guild_id: int,
        reason: Optional[str] = None,
    ) -> None:
        """Log a ticket close."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import TicketLogView, UserIdButton, TRANSCRIPT_EMOJI, CASE_EMOJI

        embed = self._create_embed(
            "🔒 Ticket Closed",
            EmbedColors.LOG_NEGATIVE,
            category="Ticket",
            user_id=user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Opened By", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Closed By", value=self._format_user_field(closed_by), inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason[:500], inline=False)
        self._set_user_thumbnail(embed, closed_by)

        view = TicketLogView(guild_id, thread_id)
        config = get_config()
        if config.transcript_base_url:
            transcript_url = f"{config.transcript_base_url}/{ticket_id}"
            view.add_item(discord.ui.Button(
                label="Transcript",
                url=transcript_url,
                style=discord.ButtonStyle.link,
                emoji=TRANSCRIPT_EMOJI,
            ))
        db = get_db()
        case = db.get_case_log(user.id)
        if case:
            case_url = f"https://discord.com/channels/{guild_id}/{case['thread_id']}"
            view.add_item(discord.ui.Button(
                label="Case",
                url=case_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_reopened(
        self: "LoggingService",
        ticket_id: str,
        user: discord.User,
        reopened_by: discord.Member,
        category: str,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log a ticket reopen."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import TicketLogView, UserIdButton

        embed = self._create_embed(
            "🔓 Ticket Reopened",
            EmbedColors.SUCCESS,
            category="Ticket",
            user_id=user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Opened By", value=self._format_user_field(user), inline=True)
        embed.add_field(name="Reopened By", value=self._format_user_field(reopened_by), inline=True)
        self._set_user_thumbnail(embed, reopened_by)

        view = TicketLogView(guild_id, thread_id)
        view.add_item(UserIdButton(user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_user_added(
        self: "LoggingService",
        ticket_id: str,
        ticket_user: discord.User,
        added_user: discord.User,
        added_by: discord.Member,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log a user being added to a ticket."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import TicketLogView, UserIdButton

        embed = self._create_embed(
            "👤 User Added to Ticket",
            EmbedColors.BLUE,
            category="Ticket",
            user_id=added_user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Ticket Owner", value=self._format_user_field(ticket_user), inline=True)
        embed.add_field(name="User Added", value=self._format_user_field(added_user), inline=True)
        embed.add_field(name="Added By", value=self._format_user_field(added_by), inline=True)
        self._set_user_thumbnail(embed, added_user)

        view = TicketLogView(guild_id, thread_id)
        view.add_item(UserIdButton(added_user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_transferred(
        self: "LoggingService",
        ticket_id: str,
        ticket_user: discord.User,
        new_staff: discord.Member,
        transferred_by: discord.Member,
        category: str,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log a ticket transfer."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import TicketLogView, UserIdButton

        embed = self._create_embed(
            "↔️ Ticket Transferred",
            EmbedColors.BLUE,
            category="Ticket",
            user_id=ticket_user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Ticket Owner", value=self._format_user_field(ticket_user), inline=True)
        embed.add_field(name="Transferred To", value=self._format_user_field(new_staff), inline=True)
        embed.add_field(name="Transferred By", value=self._format_user_field(transferred_by), inline=True)
        self._set_user_thumbnail(embed, new_staff)

        view = TicketLogView(guild_id, thread_id)
        view.add_item(UserIdButton(ticket_user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_priority_changed(
        self: "LoggingService",
        ticket_id: str,
        ticket_user: discord.User,
        changed_by: discord.Member,
        old_priority: str,
        new_priority: str,
        category: str,
        thread_id: int,
        guild_id: int,
    ) -> None:
        """Log a ticket priority change."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import TicketLogView, UserIdButton

        priority_colors = {
            "low": 0x808080,
            "normal": EmbedColors.BLUE,
            "high": 0xFFA500,
            "urgent": EmbedColors.LOG_NEGATIVE,
        }

        embed = self._create_embed(
            "📊 Ticket Priority Changed",
            priority_colors.get(new_priority, EmbedColors.BLUE),
            category="Ticket",
            user_id=ticket_user.id,
        )
        embed.add_field(name="Ticket", value=f"`{ticket_id}`", inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Priority", value=f"{old_priority.title()} → **{new_priority.title()}**", inline=True)
        embed.add_field(name="Ticket Owner", value=self._format_user_field(ticket_user), inline=True)
        embed.add_field(name="Changed By", value=self._format_user_field(changed_by), inline=True)
        self._set_user_thumbnail(embed, changed_by)

        view = TicketLogView(guild_id, thread_id)
        view.add_item(UserIdButton(ticket_user.id))

        await self._send_log(LogCategory.TICKETS, embed, view=view)

    async def log_ticket_transcript(
        self: "LoggingService",
        ticket_id: str,
        user: discord.User,
        category: str,
        subject: str,
        messages: list,
        closed_by: discord.Member,
        created_at: float,
        closed_at: float,
    ) -> None:
        """Log a ticket transcript when closed."""
        if not self.enabled:
            logger.warning("Logging Service Disabled For Transcript", [("Ticket ID", ticket_id)])
            return

        from ..categories import LogCategory
        from ..views import TranscriptLinkView

        logger.tree("Logging Ticket Transcript", [
            ("Ticket ID", ticket_id),
            ("User", f"{user.name} ({user.id})"),
            ("Messages", str(len(messages))),
        ], emoji="📜")

        import html as html_lib
        created_dt = datetime.fromtimestamp(created_at, tz=NY_TZ)
        closed_dt = datetime.fromtimestamp(closed_at, tz=NY_TZ)
        duration = closed_dt - created_dt

        days = duration.days
        hours, remainder = divmod(duration.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if days > 0:
            duration_str = f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            duration_str = f"{hours}h {minutes}m"
        else:
            duration_str = f"{minutes}m"

        embed = discord.Embed(
            title=f"🎫 Ticket Transcript - {ticket_id}",
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ),
        )

        self._set_user_thumbnail(embed, user)
        embed.add_field(name="User", value=f"{user.mention}\n`{user.name}`", inline=True)
        embed.add_field(name="Category", value=f"`{category.title()}`", inline=True)
        embed.add_field(name="Closed By", value=f"{closed_by.mention}", inline=True)
        embed.add_field(name="Subject", value=subject[:200] if subject else "No subject", inline=False)
        embed.add_field(name="Created", value=f"<t:{int(created_at)}:F>", inline=True)
        embed.add_field(name="Duration", value=f"`{duration_str}`", inline=True)

        set_footer(embed)

        html_content = self._generate_transcript_html(
            ticket_id=ticket_id,
            category=category,
            subject=subject,
            user=user,
            closed_by=closed_by,
            created_dt=created_dt,
            closed_dt=closed_dt,
            duration_str=duration_str,
            messages=messages,
        )

        transcript_file = discord.File(
            io.BytesIO(html_content.encode("utf-8")),
            filename=f"transcript_{ticket_id}.html",
        )

        config = get_config()
        view = None
        if config.transcript_base_url:
            transcript_url = f"{config.transcript_base_url}/{ticket_id}"
            view = TranscriptLinkView(transcript_url)

        result = await self._send_log(LogCategory.TRANSCRIPTS, embed, files=[transcript_file], view=view, user_id=user.id)
        if result:
            logger.tree("Ticket Transcript Logged to Forum", [
                ("Ticket ID", ticket_id),
                ("Message ID", str(result.id)),
            ], emoji="✅")
        else:
            logger.error("Failed to Log Ticket Transcript", [
                ("Ticket ID", ticket_id),
                ("User", f"{user.name} ({user.id})"),
                ("Reason", "send_log returned None"),
            ])

    async def log_case_transcript(
        self: "LoggingService",
        case_id: str,
        user: discord.User,
        action_type: str,
        moderator_id: int,
        reason: str,
        created_at: float,
        approved_by: discord.Member,
        transcript_url: Optional[str] = None,
        case_thread_url: Optional[str] = None,
    ) -> None:
        """Log a case transcript when approved."""
        if not self.enabled:
            return

        from ..categories import LogCategory
        from ..views import CASE_EMOJI

        action_emoji = {
            "mute": "🔇", "ban": "🔨", "warn": "⚠️", "forbid": "🚫",
            "timeout": "⏰", "unmute": "🔊", "unban": "✅", "unforbid": "✅",
        }.get(action_type, "📋")

        embed = discord.Embed(
            title=f"{action_emoji} Case Transcript - {case_id}",
            color=EmbedColors.SUCCESS,
            timestamp=datetime.now(NY_TZ),
        )

        self._set_user_thumbnail(embed, user)
        embed.add_field(name="User", value=f"{user.mention}\n`{user.name}`", inline=True)
        embed.add_field(name="Action", value=f"`{action_type.title()}`", inline=True)
        embed.add_field(name="Moderator", value=f"<@{moderator_id}>", inline=True)
        embed.add_field(name="Reason", value=reason[:200] if len(reason) > 200 else reason, inline=False)
        embed.add_field(name="Created", value=f"<t:{int(created_at)}:F>", inline=True)
        embed.add_field(name="Approved By", value=approved_by.mention, inline=True)

        set_footer(embed)

        view = discord.ui.View(timeout=None)
        if transcript_url:
            view.add_item(discord.ui.Button(
                label="View Transcript",
                url=transcript_url,
                style=discord.ButtonStyle.link,
                emoji="📜",
            ))
        if case_thread_url:
            view.add_item(discord.ui.Button(
                label="Case Thread",
                url=case_thread_url,
                style=discord.ButtonStyle.link,
                emoji=CASE_EMOJI,
            ))

        await self._send_log(LogCategory.TRANSCRIPTS, embed, view=view if view.children else None, user_id=user.id)


__all__ = ["TicketsLogsMixin"]
