"""
AzabBot - Server Logging Service
================================

Comprehensive server activity logging using a forum channel with categorized threads.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional, Dict, List, Union
import asyncio
import html as html_lib
import io

import aiohttp
import discord

from src.core.logger import logger
from src.core.config import get_config, EmbedColors, NY_TZ
from src.core.constants import SECONDS_PER_HOUR, QUERY_LIMIT_MEDIUM, QUERY_LIMIT_XXL
from src.utils.rate_limiter import rate_limit
from src.utils.async_utils import create_safe_task
from src.utils.http import http_session, DOWNLOAD_TIMEOUT

# Import from local package
from .categories import LogCategory, THREAD_DESCRIPTIONS
from .views import (
    UserIdButton,
    LogView,
    setup_log_views)
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
    WarningsLogsMixin)

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
    WarningsLogsMixin):
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
        self._asset_cache: Dict[str, str] = {}  # CDN URL -> permanent URL
        self._asset_cache_max = 500

        logger.tree("Logging Service Created", [
            ("Enabled", str(self.enabled)),
            ("Guild Filter", str(self.config.main_guild_id) if self.config.main_guild_id else "None (all guilds)"),
        ], emoji="📋")

    @property
    def enabled(self) -> bool:
        """Check if logging is enabled and initialized."""
        return self.config.server_logs_forum_id is not None and self._initialized

    def _should_log(self, guild_id: Optional[int], user_id: Optional[int] = None) -> bool:
        """Check if we should log for this guild and user."""
        if not self.enabled:
            return False
        if guild_id is None:
            return False
        if user_id and self.config.ignored_bot_ids and user_id in self.config.ignored_bot_ids:
            return False
        if user_id and user_id == self.config.owner_id:
            return False
        if self.config.main_guild_id:
            return guild_id == self.config.main_guild_id
        return True

    def _format_channel(self, channel) -> str:
        """Format channel reference as text name (avoids #unknown for deleted channels)."""
        if channel is None:
            return "#unknown"
        try:
            if hasattr(channel, 'name') and channel.name:
                return f"#{channel.name}"
            elif hasattr(channel, 'id'):
                return f"Channel {channel.id}"
            else:
                return "#unknown"
        except (AttributeError, TypeError):
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
        except (AttributeError, TypeError):
            return "unknown role"

    # =========================================================================
    # Initialization
    # =========================================================================

    async def initialize(self) -> bool:
        """Initialize the logging service by setting up forum and threads."""
        if not self.config.server_logs_forum_id:
            logger.info("Logging Service disabled (no forum ID configured)")
            return False

        try:
            self._forum = self.bot.get_channel(self.config.server_logs_forum_id)
            if not self._forum or not isinstance(self._forum, discord.ForumChannel):
                logger.warning("Logging Service Forum Not Found", [("ID", str(self.config.server_logs_forum_id))])
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
            logger.warning("Logging Service Init Failed", [("Error", str(e)[:50])])
            return False

    async def _setup_threads(self) -> None:
        """Set up all category threads."""
        if not self._forum:
            return

        existing_threads = {}
        for thread in self._forum.threads:
            existing_threads[thread.name] = thread

        async for thread in self._forum.archived_threads(limit=QUERY_LIMIT_MEDIUM):
            existing_threads[thread.name] = thread

        for category in LogCategory:
            thread_name = category.value

            if thread_name in existing_threads:
                thread = existing_threads[thread_name]
                if thread.archived:
                    try:
                        await thread.edit(archived=False)
                    except discord.HTTPException:
                        pass
                self._threads[category] = thread
            else:
                try:
                    thread = await self._forum.create_thread(
                        name=thread_name,
                        content=THREAD_DESCRIPTIONS.get(category, "Server activity logs"))
                    self._threads[category] = thread.thread
                    await rate_limit("thread_create")
                except discord.HTTPException as e:
                    logger.warning("Logging Service Thread Creation Failed", [("Thread", thread_name), ("Error", str(e)[:50])])

    async def _validate_threads(self) -> List[str]:
        """Validate that all log category threads exist and are synced."""
        issues: List[str] = []

        if not self._forum:
            issues.append("Forum channel not available")
            return issues

        for category in LogCategory:
            if category not in self._threads:
                issues.append(f"Missing thread: {category.value}")
                logger.warning("Logging Service Thread Missing", [("Category", category.value)])

        category_names = {cat.value for cat in LogCategory}
        utility_thread_ids: set[int] = set()
        if self.config.assets_channel_id:
            utility_thread_ids.add(self.config.assets_channel_id)

        utility_thread_names = {"📁 Assets", "Assets", "Transcript Assets"}
        forum_threads = list(self._forum.threads)

        try:
            async for thread in self._forum.archived_threads(limit=QUERY_LIMIT_MEDIUM):
                forum_threads.append(thread)
        except discord.HTTPException:
            pass

        thread_name_counts: Dict[str, int] = {}
        for thread in forum_threads:
            thread_name_counts[thread.name] = thread_name_counts.get(thread.name, 0) + 1

        for name, count in thread_name_counts.items():
            if count > 1 and name in category_names:
                issues.append(f"DUPLICATE thread: '{name}' ({count} copies) - delete extras!")
                logger.error("Logging Service Duplicate Thread", [("Thread", name), ("Copies", str(count))])

        for thread in forum_threads:
            if thread.name in category_names:
                continue
            if thread.id in utility_thread_ids:
                continue
            if thread.name in utility_thread_names:
                continue
            issues.append(f"Extra thread: {thread.name}")
            logger.info("Logging Service Unrecognized Thread", [("Thread", thread.name)])

        if issues:
            log_items = [
                ("Total Categories", str(len(LogCategory))),
                ("Loaded Threads", str(len(self._threads))),
                ("Issues Found", str(len(issues))),
            ]
            # Add each issue to the tree output for visibility
            for issue in issues[:5]:  # Limit to first 5 issues
                log_items.append(("Issue", issue))
            logger.tree("Thread Sync Validation", log_items, emoji="⚠️")
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

        utility_threads_to_check: list[tuple[str, Optional[int]]] = []

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
                        except discord.HTTPException:
                            pass
                    logger.debug("Utility Thread Verified", [("Thread", thread_name), ("ID", str(thread_id))])
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
            except discord.HTTPException as e:
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
        user_id: Optional[int] = None) -> discord.Embed:
        """Create a standardized log embed with footer metadata."""
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        footer_parts = []
        if user_id:
            footer_parts.append(f"ID: {user_id}")
        if category:
            footer_parts.append(category)
        if footer_parts:
            embed.set_footer(text=" · ".join(footer_parts))
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
        except (AttributeError, TypeError):
            pass

    async def _persist_cdn_url(self, cdn_url: str, filename: str) -> Optional[str]:
        """Download a CDN image, upload to assets channel, return permanent URL. Uses cache."""
        if not self.config.assets_channel_id:
            return None

        # Strip query params for cache key (Discord CDN adds ?size= etc.)
        cache_key = cdn_url.split("?")[0]

        # Check cache first
        if cache_key in self._asset_cache:
            return self._asset_cache[cache_key]

        try:
            async with http_session.get(cdn_url, timeout=DOWNLOAD_TIMEOUT) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

        try:
            channel = self.bot.get_channel(self.config.assets_channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(self.config.assets_channel_id)
            if not channel:
                return None
            msg = await channel.send(file=discord.File(io.BytesIO(data), filename=filename))
            if msg and msg.attachments:
                permanent_url = msg.attachments[0].url
                # Cache it
                if len(self._asset_cache) >= self._asset_cache_max:
                    # Evict oldest entries
                    keys = list(self._asset_cache.keys())
                    for k in keys[:100]:
                        del self._asset_cache[k]
                self._asset_cache[cache_key] = permanent_url
                return permanent_url
        except (discord.NotFound, discord.HTTPException):
            pass
        return None

    async def _download_embed_assets(self, embed: discord.Embed) -> None:
        """Replace CDN URLs in embed with permanent asset channel URLs."""
        # Persist thumbnail
        if embed.thumbnail and embed.thumbnail.url and not embed.thumbnail.url.startswith("attachment://"):
            permanent_url = await self._persist_cdn_url(embed.thumbnail.url, "thumb.png")
            if permanent_url:
                embed.set_thumbnail(url=permanent_url)

        # Persist image
        if embed.image and embed.image.url and not embed.image.url.startswith("attachment://"):
            permanent_url = await self._persist_cdn_url(embed.image.url, "image.png")
            if permanent_url:
                embed.set_image(url=permanent_url)

    async def _send_log(
        self,
        category: LogCategory,
        embed: discord.Embed,
        files: Optional[List[discord.File]] = None,
        user_id: Optional[int] = None,
        view: Optional[discord.ui.View] = None) -> Optional[discord.Message]:
        """Send a log to the appropriate thread. Returns the message if successful."""
        if not self._initialized:
            return None

        thread = self._threads.get(category)
        if not thread:
            logger.warning("Logging Service Thread Missing", [("Category", category.value)])
            return None

        try:
            await self._download_embed_assets(embed)

            if view is None and user_id and thread.guild:
                view = LogView(user_id, thread.guild.id)

            last_exc = None
            for attempt in range(3):
                try:
                    message = await thread.send(embed=embed, files=files or None, view=view)
                    return message
                except discord.HTTPException as e:
                    if e.status == 503 and attempt < 2:
                        last_exc = e
                        logger.warning("Logging Service 503 Retry", [
                            ("Category", category.value),
                            ("Attempt", f"{attempt + 1}/3"),
                        ])
                        await asyncio.sleep(2)
                        continue
                    raise

        except discord.Forbidden:
            logger.warning("Logging Service Send Forbidden", [("Category", category.value)])
            return None
        except discord.HTTPException as e:
            logger.warning("Logging Service Send Failed", [("Category", category.value), ("Error", str(e)[:50])])
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
        messages: list) -> str:
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
    # Log Retention / Cleanup (called by MaintenanceService)
    # =========================================================================



# =============================================================================
# Module Export
# =============================================================================

__all__ = ["LoggingService", "LogCategory", "LogView", "UserIdButton", "setup_log_views"]
