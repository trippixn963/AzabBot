"""
AzabBot - Server Logging Service
================================

Comprehensive server activity logging using a forum channel with categorized threads.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Dict, List, Union
import asyncio
import html as html_lib

import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.utils.rate_limiter import rate_limit
from src.utils.async_utils import create_safe_task

# Import from local package
from .categories import LogCategory, THREAD_DESCRIPTIONS
from .views import (
    UserIdButton,
    LogView,
    setup_log_views,
)
from .handlers import (
    ModerationLogsMixin,
    MutesLogsMixin,
    MessageLogsMixin,
    MemberLogsMixin,
    VoiceLogsMixin,
    ChannelLogsMixin,
    ServerLogsMixin,
    IntegrationsLogsMixin,
    ThreadsLogsMixin,
    AutoModLogsMixin,
    EventsLogsMixin,
    ForumLogsMixin,
    ReactionsLogsMixin,
    StageLogsMixin,
    BoostsLogsMixin,
    InvitesLogsMixin,
    MiscLogsMixin,
    AlertsLogsMixin,
    TicketsLogsMixin,
    AppealsLogsMixin,
    ModmailLogsMixin,
    WarningsLogsMixin,
    AuditLogsMixin,
)

if TYPE_CHECKING:
    from src.bot import AzabBot


# =============================================================================
# Logging Service
# =============================================================================

class LoggingService(
    ModerationLogsMixin,
    MutesLogsMixin,
    MessageLogsMixin,
    MemberLogsMixin,
    VoiceLogsMixin,
    ChannelLogsMixin,
    ServerLogsMixin,
    IntegrationsLogsMixin,
    ThreadsLogsMixin,
    AutoModLogsMixin,
    EventsLogsMixin,
    ForumLogsMixin,
    ReactionsLogsMixin,
    StageLogsMixin,
    BoostsLogsMixin,
    InvitesLogsMixin,
    MiscLogsMixin,
    AlertsLogsMixin,
    TicketsLogsMixin,
    AppealsLogsMixin,
    ModmailLogsMixin,
    WarningsLogsMixin,
    AuditLogsMixin,
):
    """
    Server activity logging service using forum threads.

    DESIGN:
        Creates and manages 15 threads in a forum channel, one per category.
        Each log type is routed to the appropriate thread.
        Embeds are consistent and include timestamps.

    Attributes:
        bot: Reference to the main bot instance.
        config: Bot configuration.
        _forum: Cached forum channel reference.
        _threads: Cached thread references by category.
    """

    def __init__(self, bot: "AzabBot") -> None:
        """Initialize the logging service."""
        self.bot = bot
        self.config = get_config()
        self._forum: Optional[discord.ForumChannel] = None
        self._threads: Dict[LogCategory, discord.Thread] = {}
        self._initialized = False

        logger.tree("Logging Service Created", [
            ("Enabled", str(self.enabled)),
            ("Guild Filter", str(self.config.logging_guild_id) if self.config.logging_guild_id else "None (all guilds)"),
        ], emoji="📋")

    @property
    def enabled(self) -> bool:
        """Check if logging is enabled."""
        return self.config.server_logs_forum_id is not None

    def _should_log(self, guild_id: Optional[int], user_id: Optional[int] = None) -> bool:
        """Check if we should log for this guild and user."""
        if not self.enabled:
            return False
        if guild_id is None:
            return False
        if user_id and self.config.ignored_bot_ids and user_id in self.config.ignored_bot_ids:
            return False
        if self.config.logging_guild_id:
            return guild_id == self.config.logging_guild_id
        return True

    def _format_channel(self, channel) -> str:
        """Format channel reference as clickable mention."""
        if channel is None:
            return "#unknown"
        try:
            if hasattr(channel, 'id'):
                return f"<#{channel.id}>"
            elif hasattr(channel, 'name') and channel.name:
                return f"#{channel.name}"
            else:
                return "#unknown"
        except Exception:
            return "#unknown"

    def _format_role(self, role) -> str:
        """Format role reference with fallback to name."""
        if role is None:
            return "unknown role"
        try:
            if hasattr(role, 'name') and role.name:
                return f"`{role.name}`"
            elif hasattr(role, 'id'):
                return f"`role-{role.id}`"
            else:
                return "unknown role"
        except Exception:
            return "unknown role"

    # =========================================================================
    # Initialization
    # =========================================================================

    async def initialize(self) -> bool:
        """Initialize the logging service by setting up forum and threads."""
        if not self.enabled:
            logger.info("Logging Service disabled (no forum ID configured)")
            return False

        try:
            self._forum = self.bot.get_channel(self.config.server_logs_forum_id)
            if not self._forum or not isinstance(self._forum, discord.ForumChannel):
                logger.warning(f"Logging Service: Forum channel not found: {self.config.server_logs_forum_id}")
                return False

            await self._setup_threads()
            sync_issues = await self._validate_threads()
            await self._validate_utility_threads()

            self._initialized = True
            log_items = [
                ("Forum", self._forum.name),
                ("Threads", f"{len(self._threads)}/{len(LogCategory)}"),
            ]
            if sync_issues:
                log_items.append(("Sync Issues", str(len(sync_issues))))
                logger.warning("Logging Service Initialized (with issues)", log_items)
            else:
                logger.tree("Logging Service Initialized", log_items, emoji="✅")

            return True

        except Exception as e:
            logger.warning(f"Logging Service: Init failed: {e}")
            return False

    async def _setup_threads(self) -> None:
        """Set up all category threads."""
        if not self._forum:
            return

        existing_threads = {}
        for thread in self._forum.threads:
            existing_threads[thread.name] = thread

        async for thread in self._forum.archived_threads(limit=50):
            existing_threads[thread.name] = thread

        for category in LogCategory:
            thread_name = category.value

            if thread_name in existing_threads:
                thread = existing_threads[thread_name]
                if thread.archived:
                    try:
                        await thread.edit(archived=False)
                    except Exception:
                        pass
                self._threads[category] = thread
            else:
                try:
                    thread = await self._forum.create_thread(
                        name=thread_name,
                        content=THREAD_DESCRIPTIONS.get(category, "Server activity logs"),
                    )
                    self._threads[category] = thread.thread
                    await rate_limit("thread_create")
                except Exception as e:
                    logger.warning(f"Logging Service: Failed to create thread {thread_name}: {e}")

    async def _validate_threads(self) -> List[str]:
        """Validate that all log category threads exist and are synced."""
        issues: List[str] = []

        if not self._forum:
            issues.append("Forum channel not available")
            return issues

        for category in LogCategory:
            if category not in self._threads:
                issues.append(f"Missing thread: {category.value}")
                logger.warning(f"Logging Service: Missing thread for {category.value}")

        category_names = {cat.value for cat in LogCategory}
        utility_thread_ids: set[int] = set()
        if self.config.transcript_assets_thread_id:
            utility_thread_ids.add(self.config.transcript_assets_thread_id)

        utility_thread_names = {"📁 Assets", "Assets", "Transcript Assets"}
        forum_threads = list(self._forum.threads)

        try:
            async for thread in self._forum.archived_threads(limit=50):
                forum_threads.append(thread)
        except Exception:
            pass

        thread_name_counts: Dict[str, int] = {}
        for thread in forum_threads:
            thread_name_counts[thread.name] = thread_name_counts.get(thread.name, 0) + 1

        for name, count in thread_name_counts.items():
            if count > 1 and name in category_names:
                issues.append(f"DUPLICATE thread: '{name}' ({count} copies) - delete extras!")
                logger.error(f"Logging Service: Duplicate thread '{name}' found ({count} copies)")

        for thread in forum_threads:
            if thread.name in category_names:
                continue
            if thread.id in utility_thread_ids:
                continue
            if thread.name in utility_thread_names:
                continue
            issues.append(f"Extra thread: {thread.name}")
            logger.info(f"Logging Service: Unrecognized thread '{thread.name}' in forum")

        if issues:
            logger.tree("Thread Sync Validation", [
                ("Total Categories", str(len(LogCategory))),
                ("Loaded Threads", str(len(self._threads))),
                ("Issues Found", str(len(issues))),
            ], emoji="⚠️")
        else:
            logger.tree("Thread Sync Validation", [
                ("Status", "All threads synced"),
                ("Categories", str(len(LogCategory))),
            ], emoji="✅")

        return issues

    async def _validate_utility_threads(self) -> None:
        """Validate that utility threads (Assets, etc.) still exist."""
        if not self._forum:
            return

        utility_threads_to_check: list[tuple[str, Optional[int]]] = [
            ("📁 Assets", self.config.transcript_assets_thread_id),
        ]

        for thread_name, thread_id in utility_threads_to_check:
            if not thread_id:
                continue

            try:
                thread = self.bot.get_channel(thread_id)
                if not thread:
                    thread = await self.bot.fetch_channel(thread_id)

                if thread:
                    if hasattr(thread, 'name') and thread.name != thread_name:
                        try:
                            await thread.edit(name=thread_name)
                            logger.info("Utility Thread Renamed", [
                                ("Old Name", thread.name),
                                ("New Name", thread_name),
                                ("Thread ID", str(thread_id)),
                            ])
                        except Exception:
                            pass
                    logger.debug(f"Utility thread verified: {thread_name} ({thread_id})")
                else:
                    logger.warning("Utility Thread Not Found", [
                        ("Expected", thread_name),
                        ("Thread ID", str(thread_id)),
                    ])
            except discord.NotFound:
                logger.warning("Utility Thread Deleted", [
                    ("Expected", thread_name),
                    ("Thread ID", str(thread_id)),
                    ("Action", "Will be recreated on next use"),
                ])
            except Exception as e:
                logger.error("Utility Thread Check Failed", [
                    ("Thread", thread_name),
                    ("Error", str(e)[:50]),
                ])

    # =========================================================================
    # Helpers
    # =========================================================================

    def _create_embed(
        self,
        title: str,
        color: int,
        description: Optional[str] = None,
        category: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> discord.Embed:
        """Create a standardized log embed."""
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(NY_TZ),
        )
        footer_parts = []
        if category:
            footer_parts.append(category)
        if user_id:
            footer_parts.append(f"ID: {user_id}")
        footer_text = " • ".join(footer_parts) if footer_parts else datetime.now(NY_TZ).strftime("%B %d, %Y")
        embed.set_footer(text=footer_text)
        return embed

    def _format_user_field(self, user: Union[discord.User, discord.Member]) -> str:
        """Format user field inline without ID (ID goes in footer)."""
        return f"{user.mention} · {user.name}"

    def _format_reason(self, reason: Optional[str]) -> str:
        """Format reason field with code block."""
        if not reason:
            return "```No reason provided```"
        if len(reason) > 500:
            reason = reason[:497] + "..."
        return f"```{reason}```"

    def _format_duration_precise(self, seconds: int) -> str:
        """Format duration with precision."""
        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''}"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            if secs > 0:
                return f"{minutes}m {secs}s"
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        elif seconds < 86400:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if minutes > 0:
                return f"{hours}h {minutes}m"
            return f"{hours} hour{'s' if hours != 1 else ''}"
        elif seconds < 2592000:
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            if hours > 0:
                return f"{days}d {hours}h"
            return f"{days} day{'s' if days != 1 else ''}"
        elif seconds < 31536000:
            months = seconds // 2592000
            days = (seconds % 2592000) // 86400
            if days > 0:
                return f"{months}mo {days}d"
            return f"{months} month{'s' if months != 1 else ''}"
        else:
            years = seconds // 31536000
            remaining_days = (seconds % 31536000) // 86400
            if remaining_days > 0:
                return f"{years}y {remaining_days}d"
            return f"{years} year{'s' if years != 1 else ''}"

    def _set_user_thumbnail(self, embed: discord.Embed, user: Union[discord.User, discord.Member]) -> None:
        """Set user avatar as thumbnail if available."""
        try:
            if user.display_avatar:
                embed.set_thumbnail(url=user.display_avatar.url)
        except Exception:
            pass

    async def _send_log(
        self,
        category: LogCategory,
        embed: discord.Embed,
        files: Optional[List[discord.File]] = None,
        user_id: Optional[int] = None,
        view: Optional[discord.ui.View] = None,
    ) -> Optional[discord.Message]:
        """Send a log to the appropriate thread. Returns the message if successful."""
        if not self._initialized:
            logger.warning(f"Logging Service: Not initialized, cannot send to {category.value}")
            return None

        if category not in self._threads:
            logger.warning(f"Logging Service: Thread missing for category {category.value}")
            return None

        try:
            thread = self._threads[category]
            if view is None and user_id:
                view = LogView(user_id, thread.guild.id)
            message = await thread.send(embed=embed, files=files or [], view=view)
            return message
        except discord.Forbidden:
            logger.warning(f"Logging Service: Forbidden to send to {category.value}")
            return None
        except Exception as e:
            logger.warning(f"Logging Service: Send failed to {category.value}: {e}")
            return None

    # =========================================================================
    # Transcript HTML Generation (used by TicketsLogsMixin)
    # =========================================================================

    def _generate_transcript_html(
        self,
        ticket_id: str,
        category: str,
        subject: str,
        user: discord.User,
        closed_by: discord.Member,
        created_dt,
        closed_dt,
        duration_str: str,
        messages: list,
    ) -> str:
        """Generate a beautiful HTML transcript."""
        html_output = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ticket {ticket_id} - Transcript</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e4e4e4;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 40px rgba(102, 126, 234, 0.3);
        }}
        .header h1 {{
            font-size: 28px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .header h1 .emoji {{ font-size: 32px; }}
        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        .meta-item {{
            background: rgba(255,255,255,0.1);
            padding: 12px 16px;
            border-radius: 8px;
        }}
        .meta-item .label {{
            font-size: 12px;
            text-transform: uppercase;
            opacity: 0.7;
            margin-bottom: 4px;
        }}
        .meta-item .value {{ font-size: 16px; font-weight: 600; }}
        .messages {{
            background: #0d1117;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }}
        .messages-header {{
            background: #161b22;
            padding: 16px 20px;
            border-bottom: 1px solid #30363d;
            font-weight: 600;
            color: #8b949e;
        }}
        .message {{
            display: flex;
            padding: 16px 20px;
            border-bottom: 1px solid #21262d;
            transition: background 0.2s;
        }}
        .message:hover {{ background: rgba(255,255,255,0.02); }}
        .message:last-child {{ border-bottom: none; }}
        .avatar {{
            width: 44px;
            height: 44px;
            border-radius: 50%;
            margin-right: 16px;
            flex-shrink: 0;
            background: #30363d;
        }}
        .message-content {{ flex: 1; min-width: 0; }}
        .message-header {{
            display: flex;
            align-items: baseline;
            gap: 8px;
            margin-bottom: 6px;
        }}
        .author {{ font-weight: 600; color: #58a6ff; }}
        .author.staff {{ color: #f0883e; }}
        .author.bot {{ color: #a371f7; }}
        .timestamp {{ font-size: 12px; color: #8b949e; }}
        .content {{ line-height: 1.5; word-wrap: break-word; white-space: pre-wrap; }}
        .attachments {{ margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; }}
        .attachment {{
            background: #21262d;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 13px;
            color: #58a6ff;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .attachment:hover {{ background: #30363d; }}
        .footer {{
            text-align: center;
            padding: 30px;
            color: #8b949e;
            font-size: 14px;
        }}
        .empty-message {{ color: #8b949e; font-style: italic; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><span class="emoji">🎫</span> Ticket {ticket_id}</h1>
            <div class="meta-grid">
                <div class="meta-item">
                    <div class="label">Category</div>
                    <div class="value">{category.title()}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Status</div>
                    <div class="value">Closed</div>
                </div>
                <div class="meta-item">
                    <div class="label">Opened By</div>
                    <div class="value">{html_lib.escape(user.display_name)}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Closed By</div>
                    <div class="value">{html_lib.escape(closed_by.display_name)}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Created</div>
                    <div class="value">{created_dt.strftime("%b %d, %Y %I:%M %p")}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Duration</div>
                    <div class="value">{duration_str}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Subject</div>
                    <div class="value">{html_lib.escape(subject[:50])}{"..." if len(subject) > 50 else ""}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Messages</div>
                    <div class="value">{len(messages)}</div>
                </div>
            </div>
        </div>

        <div class="messages">
            <div class="messages-header">📝 Conversation</div>
'''

        for msg in messages:
            author = msg.get("author", "Unknown")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")
            attachments = msg.get("attachments", [])
            avatar_url = msg.get("avatar_url", "")
            is_staff = msg.get("is_staff", False)

            author_class = "staff" if is_staff else ""
            if "Bot" in author:
                author_class = "bot"

            safe_content = html_lib.escape(content) if content else '<span class="empty-message">(no text content)</span>'

            html_output += f'''
            <div class="message">
                <img class="avatar" src="{avatar_url or 'https://cdn.discordapp.com/embed/avatars/0.png'}" alt="avatar" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
                <div class="message-content">
                    <div class="message-header">
                        <span class="author {author_class}">{html_lib.escape(author)}</span>
                        <span class="timestamp">{timestamp}</span>
                    </div>
                    <div class="content">{safe_content}</div>
'''
            if attachments:
                html_output += '                    <div class="attachments">\n'
                for att in attachments:
                    filename = att.split("/")[-1].split("?")[0] if att else "attachment"
                    html_output += f'                        <a class="attachment" href="{att}" target="_blank">📎 {html_lib.escape(filename[:30])}</a>\n'
                html_output += '                    </div>\n'

            html_output += '''                </div>
            </div>
'''

        html_output += f'''        </div>

        <div class="footer">
            Generated on {closed_dt.strftime("%B %d, %Y at %I:%M %p %Z")}<br>
            🎫 AzabBot Ticket System
        </div>
    </div>
</body>
</html>'''

        return html_output

    # =========================================================================
    # Log Retention / Cleanup
    # =========================================================================

    async def start_retention_cleanup(self) -> None:
        """Start the scheduled log retention cleanup task."""
        if not self.enabled or self.config.log_retention_days <= 0:
            logger.debug("Log retention cleanup disabled")
            return

        create_safe_task(self._retention_cleanup_loop(), "Log Retention Cleanup")
        logger.tree("Log Retention Started", [
            ("Retention", f"{self.config.log_retention_days} days"),
            ("Schedule", "Daily at midnight EST"),
        ], emoji="🗑️")

    async def _retention_cleanup_loop(self) -> None:
        """Loop that runs maintenance tasks daily at midnight (00:00) EST."""
        from datetime import timedelta

        while True:
            try:
                now = datetime.now(NY_TZ)
                target = now.replace(hour=0, minute=0, second=0, microsecond=0)
                if now >= target:
                    target = target + timedelta(days=1)

                wait_seconds = (target - now).total_seconds()
                await asyncio.sleep(wait_seconds)

                await self._cleanup_old_logs()
                await self._validate_utility_threads()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Log Retention Loop Error", [("Error", str(e))])
                await asyncio.sleep(3600)

    async def _cleanup_old_logs(self) -> None:
        """Delete log messages older than retention period."""
        from datetime import timedelta

        if not self.enabled or self.config.log_retention_days <= 0:
            return

        if not self._forum:
            return

        retention_days = self.config.log_retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        total_deleted = 0
        threads_cleaned = 0

        try:
            threads = []
            for thread in self._forum.threads:
                threads.append(thread)

            async for thread in self._forum.archived_threads(limit=50):
                threads.append(thread)

            for thread in threads:
                try:
                    deleted_in_thread = 0

                    async for message in thread.history(limit=500, before=cutoff, oldest_first=True):
                        if message.pinned:
                            continue

                        try:
                            await message.delete()
                            deleted_in_thread += 1
                            total_deleted += 1
                            await rate_limit("bulk_operation")

                        except (discord.NotFound, discord.Forbidden):
                            pass
                        except Exception as e:
                            logger.debug(f"Retention delete failed: {e}")

                    if deleted_in_thread > 0:
                        threads_cleaned += 1
                        logger.debug(f"Retention: Cleaned {deleted_in_thread} from #{thread.name}")

                except Exception as e:
                    logger.debug(f"Retention thread error ({thread.name}): {e}")

            if total_deleted > 0:
                logger.tree("Log Retention Cleanup Complete", [
                    ("Threads", str(threads_cleaned)),
                    ("Messages Deleted", str(total_deleted)),
                    ("Retention", f"{retention_days} days"),
                ], emoji="🗑️")

        except Exception as e:
            logger.error("Log Retention Cleanup Failed", [("Error", str(e))])


# =============================================================================
# Module Export
# =============================================================================

__all__ = ["LoggingService", "LogCategory", "LogView", "UserIdButton", "setup_log_views"]
