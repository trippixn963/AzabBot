"""
AzabBot - Ticket Transcript Generator
=====================================

HTML and JSON transcript generation for tickets.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import html as html_lib
import io
import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any

import discord

from src.core.config import NY_TZ
from src.core.logger import logger

from .constants import TICKET_CATEGORIES, MAX_TRANSCRIPT_MESSAGES, MAX_TRANSCRIPT_USER_LOOKUPS


# =============================================================================
# JSON Transcript Data Classes (for web viewer)
# =============================================================================

@dataclass
class TicketTranscriptAttachment:
    """Represents an attachment in a ticket transcript."""
    filename: str
    url: str
    content_type: Optional[str] = None
    size: int = 0


@dataclass
class TicketTranscriptMessage:
    """Represents a single message in a ticket transcript."""
    author_id: int
    author_name: str
    author_display_name: str
    author_avatar_url: Optional[str]
    content: str
    timestamp: float
    attachments: List[TicketTranscriptAttachment]
    is_bot: bool = False
    is_staff: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "author_id": self.author_id,
            "author_name": self.author_name,
            "author_display_name": self.author_display_name,
            "author_avatar_url": self.author_avatar_url,
            "content": self.content,
            "timestamp": self.timestamp,
            "attachments": [asdict(a) for a in self.attachments],
            "is_bot": self.is_bot,
            "is_staff": self.is_staff,
        }


@dataclass
class TicketTranscript:
    """Complete JSON transcript of a ticket thread."""
    ticket_id: str
    thread_id: int
    thread_name: str
    category: str
    subject: str
    status: str
    created_at: float
    closed_at: Optional[float]
    message_count: int
    messages: List[TicketTranscriptMessage]
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    claimed_by_id: Optional[int] = None
    claimed_by_name: Optional[str] = None
    closed_by_id: Optional[int] = None
    closed_by_name: Optional[str] = None

    def to_json(self) -> str:
        """Serialize transcript to JSON string."""
        data = {
            "ticket_id": self.ticket_id,
            "thread_id": self.thread_id,
            "thread_name": self.thread_name,
            "category": self.category,
            "subject": self.subject,
            "status": self.status,
            "created_at": self.created_at,
            "closed_at": self.closed_at,
            "message_count": self.message_count,
            "messages": [m.to_dict() for m in self.messages],
            "user_id": self.user_id,
            "user_name": self.user_name,
            "claimed_by_id": self.claimed_by_id,
            "claimed_by_name": self.claimed_by_name,
            "closed_by_id": self.closed_by_id,
            "closed_by_name": self.closed_by_name,
        }
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "TicketTranscript":
        """Deserialize transcript from JSON string."""
        data = json.loads(json_str)
        messages = []
        for m in data.get("messages", []):
            attachments = [
                TicketTranscriptAttachment(**a) for a in m.get("attachments", [])
            ]
            messages.append(TicketTranscriptMessage(
                author_id=m["author_id"],
                author_name=m["author_name"],
                author_display_name=m["author_display_name"],
                author_avatar_url=m.get("author_avatar_url"),
                content=m["content"],
                timestamp=m["timestamp"],
                attachments=attachments,
                is_bot=m.get("is_bot", False),
                is_staff=m.get("is_staff", False),
            ))
        return cls(
            ticket_id=data["ticket_id"],
            thread_id=data["thread_id"],
            thread_name=data["thread_name"],
            category=data["category"],
            subject=data["subject"],
            status=data["status"],
            created_at=data["created_at"],
            closed_at=data.get("closed_at"),
            message_count=data["message_count"],
            messages=messages,
            user_id=data.get("user_id"),
            user_name=data.get("user_name"),
            claimed_by_id=data.get("claimed_by_id"),
            claimed_by_name=data.get("claimed_by_name"),
            closed_by_id=data.get("closed_by_id"),
            closed_by_name=data.get("closed_by_name"),
        )


async def collect_transcript_messages(
    thread: discord.Thread,
    bot: discord.Client,
    limit: int = MAX_TRANSCRIPT_MESSAGES,
) -> tuple[List[Dict[str, Any]], Dict[int, str]]:
    """
    Collect messages from a ticket thread for transcript.

    Args:
        thread: The ticket thread
        bot: The bot client for API calls
        limit: Maximum number of messages to collect

    Returns:
        Tuple of (messages list, user_map for mention resolution)
    """
    messages = []
    user_map: Dict[int, str] = {}  # user_id -> display_name
    channel_map: Dict[int, str] = {}  # channel_id -> name
    role_map: Dict[int, str] = {}  # role_id -> name
    raw_mention_ids: set = set()  # IDs found in raw text that need resolution

    try:
        # Collect role names from guild
        if thread.guild:
            for role in thread.guild.roles:
                role_map[role.id] = role.name

        async for msg in thread.history(limit=limit, oldest_first=True):
            attachments = [att.url for att in msg.attachments] if msg.attachments else []

            # Collect user info for mention resolution
            user_map[msg.author.id] = msg.author.display_name

            # Collect mentioned users
            for mentioned_user in msg.mentions:
                user_map[mentioned_user.id] = mentioned_user.display_name

            # Collect mentioned channels
            for mentioned_channel in msg.channel_mentions:
                channel_map[mentioned_channel.id] = mentioned_channel.name

            # Find raw mention-like text in content (e.g., <@123456789>)
            if msg.content:
                raw_mentions = re.findall(r'<@!?(\d+)>', msg.content)
                for user_id_str in raw_mentions:
                    user_id = int(user_id_str)
                    if user_id not in user_map:
                        raw_mention_ids.add(user_id)

            messages.append({
                "author": msg.author.display_name,
                "author_id": str(msg.author.id),
                "content": msg.content,
                "timestamp": msg.created_at.strftime("%b %d, %Y %I:%M %p"),
                "attachments": attachments,
                "avatar_url": str(msg.author.display_avatar.url) if msg.author.display_avatar else "",
                "is_bot": msg.author.bot,
                "is_staff": msg.author.guild_permissions.manage_messages if hasattr(msg.author, 'guild_permissions') else False,
            })

        # Resolve raw mention IDs to usernames (limited to prevent API spam)
        if raw_mention_ids and thread.guild:
            api_calls = 0
            for user_id in raw_mention_ids:
                # Try to get member from guild cache first (no API call)
                member = thread.guild.get_member(user_id)
                if member:
                    user_map[user_id] = member.display_name
                    continue

                # Try bot's user cache (no API call)
                cached_user = bot.get_user(user_id)
                if cached_user:
                    user_map[user_id] = cached_user.display_name
                    continue

                # Only make API call if under limit
                if api_calls >= MAX_TRANSCRIPT_USER_LOOKUPS:
                    continue  # Leave unresolved, don't spam API

                try:
                    user = await bot.fetch_user(user_id)
                    if user:
                        user_map[user_id] = user.display_name
                    api_calls += 1
                except discord.NotFound:
                    api_calls += 1  # Count failed lookups too
                except discord.HTTPException as e:
                    api_calls += 1
                    logger.warning("Failed to fetch user for transcript", [
                        ("User ID", str(user_id)),
                        ("Error", str(e)),
                    ])

    except Exception as e:
        logger.error("Failed to collect transcript messages", [
            ("Thread", f"{thread.name} ({thread.id})"),
            ("Error", str(e)),
        ])

    # Merge channel and role maps into user_map with prefixes
    mention_map = {**user_map}
    for channel_id, name in channel_map.items():
        mention_map[channel_id] = f"#{name}"
    for role_id, name in role_map.items():
        mention_map[role_id] = f"@{name}"

    return messages, mention_map


def _resolve_mentions(content: str, mention_map: Dict[int, str]) -> str:
    """
    Convert Discord mention syntax to readable names.

    Converts:
        <@123456789> or <@!123456789> -> @username
        <#123456789> -> #channel-name
        <@&123456789> -> @role-name

    Works with both raw and HTML-escaped content.
    """
    def replace_mention(match):
        mention_type = match.group(1)  # @, @!, #, or @&
        user_id = int(match.group(2))

        name = mention_map.get(user_id)
        if name:
            if mention_type in ('@', '@!'):
                return f'<span class="mention">@{html_lib.escape(name)}</span>'
            elif mention_type == '#':
                return f'<span class="mention channel">#{html_lib.escape(name)}</span>'
            elif mention_type == '@&':
                return f'<span class="mention role">@{html_lib.escape(name)}</span>'

        # Fallback: keep original but style it
        return f'<span class="mention unknown">&lt;{mention_type}{user_id}&gt;</span>'

    # Match user mentions <@123> or <@!123>, channel mentions <#123>, role mentions <@&123>
    # First try raw format
    pattern = r'<(@!?|#|@&)(\d+)>'
    result = re.sub(pattern, replace_mention, content)

    # Also match HTML-escaped format: &lt;@123&gt;
    escaped_pattern = r'&lt;(@!?|#|@&amp;)(\d+)&gt;'
    def replace_escaped_mention(match):
        mention_type = match.group(1).replace('&amp;', '&')  # Unescape &amp; back to &
        user_id = int(match.group(2))

        name = mention_map.get(user_id)
        if name:
            if mention_type in ('@', '@!'):
                return f'<span class="mention">@{html_lib.escape(name)}</span>'
            elif mention_type == '#':
                return f'<span class="mention channel">#{html_lib.escape(name)}</span>'
            elif mention_type == '@&':
                return f'<span class="mention role">@{html_lib.escape(name)}</span>'

        # Fallback: keep original but style it
        return f'<span class="mention unknown">&lt;{mention_type}{user_id}&gt;</span>'

    result = re.sub(escaped_pattern, replace_escaped_mention, result)

    return result


def generate_html_transcript(
    ticket: dict,
    messages: List[Dict[str, Any]],
    user: discord.User,
    closed_by: Optional[discord.Member] = None,
    mention_map: Optional[Dict[int, str]] = None,
) -> str:
    """
    Generate a modern, responsive HTML transcript with gold/green theme.

    Features:
    - Mobile-first responsive design
    - Auto-refresh for live updates (when ticket is open)
    - Smooth animations
    - Touch-friendly on mobile
    - Professional modern look

    Args:
        ticket: Ticket data from database
        messages: List of message dictionaries
        user: The ticket creator
        closed_by: The staff member who closed the ticket
        mention_map: Map of user/channel/role IDs to names for mention resolution

    Returns:
        HTML string of the transcript
    """
    if mention_map is None:
        mention_map = {}

    created_dt = datetime.fromtimestamp(ticket["created_at"], tz=NY_TZ)
    now_dt = datetime.now(NY_TZ)
    closed_dt = datetime.fromtimestamp(
        ticket.get("closed_at", time.time()), tz=NY_TZ
    ) if ticket.get("closed_at") else now_dt

    cat_info = TICKET_CATEGORIES.get(ticket["category"], TICKET_CATEGORIES["support"])
    is_open = ticket["status"] != "closed"

    # Auto-refresh script (only for open tickets)
    auto_refresh_script = ""
    if is_open:
        auto_refresh_script = """
    <script>
        // Auto-refresh every 10 seconds for live updates
        let refreshInterval = setInterval(() => {
            fetch(window.location.href)
                .then(r => r.text())
                .then(html => {
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(html, 'text/html');
                    const newMessages = doc.querySelector('.messages-list');
                    const newCount = doc.querySelector('.message-count');
                    if (newMessages && newCount) {
                        document.querySelector('.messages-list').innerHTML = newMessages.innerHTML;
                        document.querySelector('.message-count').textContent = newCount.textContent;
                        // Scroll to bottom if near bottom
                        const container = document.querySelector('.messages');
                        if (container.scrollHeight - container.scrollTop - container.clientHeight < 200) {
                            container.scrollTop = container.scrollHeight;
                        }
                    }
                })
                .catch(() => {});
        }, 10000);

        // Show live indicator
        document.addEventListener('DOMContentLoaded', () => {
            const indicator = document.querySelector('.live-indicator');
            if (indicator) {
                setInterval(() => {
                    indicator.style.opacity = indicator.style.opacity === '1' ? '0.5' : '1';
                }, 1000);
            }
        });
    </script>
"""

    html_output = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="theme-color" content="#0d1810">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <title>Ticket {ticket["ticket_id"]} - Transcript</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --gold: #d4af37;
            --gold-light: #f4d03f;
            --green: #22c55e;
            --green-dark: #15803d;
            --bg-dark: #0a0d08;
            --bg-card: #111610;
            --bg-message: #161b12;
            --bg-hover: #1a201a;
            --border: #2a3a20;
            --text: #e4e4e7;
            --text-muted: #71717a;
            --staff: #d4af37;
            --user: #22c55e;
            --bot: #a78bfa;
            --radius: 16px;
            --radius-sm: 10px;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }}

        html {{
            scroll-behavior: smooth;
        }}

        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg-dark);
            color: var(--text);
            min-height: 100vh;
            min-height: 100dvh;
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }}

        /* ===== Layout ===== */
        .app {{
            min-height: 100vh;
            min-height: 100dvh;
            display: flex;
            flex-direction: column;
        }}

        .container {{
            width: 100%;
            max-width: 800px;
            margin: 0 auto;
            padding: 0 16px;
        }}

        /* ===== Header ===== */
        .header {{
            background: linear-gradient(135deg, var(--gold) 0%, var(--green-dark) 100%);
            padding: 24px 0;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
        }}

        .header-content {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
        }}

        .header-left {{
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 0;
        }}

        .ticket-icon {{
            width: 48px;
            height: 48px;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            flex-shrink: 0;
        }}

        .header-info {{
            min-width: 0;
        }}

        .header-info h1 {{
            font-size: 20px;
            font-weight: 700;
            color: white;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .header-info p {{
            font-size: 13px;
            color: rgba(255, 255, 255, 0.8);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .status-badge {{
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            flex-shrink: 0;
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .status-open {{
            background: rgba(34, 197, 94, 0.2);
            color: #4ade80;
            border: 1px solid rgba(34, 197, 94, 0.3);
        }}

        .status-claimed {{
            background: rgba(212, 175, 55, 0.2);
            color: var(--gold-light);
            border: 1px solid rgba(212, 175, 55, 0.3);
        }}

        .status-closed {{
            background: rgba(239, 68, 68, 0.2);
            color: #f87171;
            border: 1px solid rgba(239, 68, 68, 0.3);
        }}

        .live-indicator {{
            width: 8px;
            height: 8px;
            background: #4ade80;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }}

        @keyframes pulse {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.5; transform: scale(0.9); }}
        }}

        /* ===== Meta Section ===== */
        .meta {{
            padding: 20px 0;
        }}

        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
        }}

        .meta-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 14px 16px;
        }}

        .meta-card.full {{
            grid-column: 1 / -1;
        }}

        .meta-label {{
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            margin-bottom: 4px;
        }}

        .meta-value {{
            font-size: 15px;
            font-weight: 600;
            color: var(--text);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .meta-value.gold {{ color: var(--gold); }}

        /* ===== Messages ===== */
        .messages {{
            flex: 1;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius) var(--radius) 0 0;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }}

        .messages-header {{
            background: var(--bg-message);
            padding: 14px 20px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 10;
        }}

        .messages-header-left {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-weight: 600;
            color: var(--gold);
        }}

        .message-count {{
            background: var(--border);
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
        }}

        .messages-list {{
            flex: 1;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
        }}

        .message {{
            display: flex;
            padding: 16px 20px;
            gap: 14px;
            border-bottom: 1px solid rgba(42, 58, 32, 0.5);
            transition: background 0.15s ease;
            animation: fadeIn 0.3s ease;
        }}

        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .message:hover {{
            background: var(--bg-hover);
        }}

        .message:last-child {{
            border-bottom: none;
        }}

        .avatar {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            flex-shrink: 0;
            background: var(--border);
            object-fit: cover;
        }}

        .message-body {{
            flex: 1;
            min-width: 0;
        }}

        .message-meta {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 4px;
            flex-wrap: wrap;
        }}

        .author {{
            font-weight: 600;
            font-size: 14px;
        }}

        .author.staff {{ color: var(--staff); }}
        .author.user {{ color: var(--user); }}
        .author.bot {{ color: var(--bot); }}

        .role-badge {{
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            padding: 2px 6px;
            border-radius: 4px;
            letter-spacing: 0.3px;
        }}

        .role-badge.staff {{
            background: rgba(212, 175, 55, 0.15);
            color: var(--gold);
        }}

        .role-badge.bot {{
            background: rgba(167, 139, 250, 0.15);
            color: var(--bot);
        }}

        .timestamp {{
            font-size: 12px;
            color: var(--text-muted);
        }}

        .content {{
            font-size: 14px;
            line-height: 1.6;
            color: var(--text);
            word-wrap: break-word;
            white-space: pre-wrap;
        }}

        .mention {{
            background: rgba(212, 175, 55, 0.15);
            color: var(--gold);
            padding: 1px 6px;
            border-radius: 4px;
            font-weight: 500;
        }}

        .mention.channel {{
            background: rgba(74, 222, 128, 0.15);
            color: var(--green);
        }}

        .mention.role {{
            background: rgba(167, 139, 250, 0.15);
            color: var(--bot);
        }}

        .empty-message {{
            color: var(--text-muted);
            font-style: italic;
        }}

        /* ===== Attachments ===== */
        .attachments {{
            margin-top: 12px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}

        .attachment {{
            background: var(--bg-dark);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 10px 14px;
            font-size: 13px;
            color: var(--green);
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.15s ease;
        }}

        .attachment:hover {{
            background: var(--border);
            transform: translateY(-1px);
        }}

        .attachment-image {{
            max-width: 100%;
            max-height: 300px;
            border-radius: 8px;
            cursor: pointer;
            transition: transform 0.2s ease;
        }}

        .attachment-image:hover {{
            transform: scale(1.02);
        }}

        /* ===== Embeds ===== */
        .embed {{
            margin-top: 12px;
            background: var(--bg-dark);
            border-left: 4px solid var(--gold);
            border-radius: 4px;
            padding: 12px 16px;
            max-width: 520px;
        }}

        .embed-author {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
        }}

        .embed-author-icon {{
            width: 24px;
            height: 24px;
            border-radius: 50%;
        }}

        .embed-author-name {{
            font-size: 13px;
            font-weight: 600;
            color: var(--text);
        }}

        .embed-title {{
            font-size: 15px;
            font-weight: 600;
            color: var(--gold);
            margin-bottom: 8px;
        }}

        .embed-title a {{
            color: var(--gold);
            text-decoration: none;
        }}

        .embed-title a:hover {{
            text-decoration: underline;
        }}

        .embed-description {{
            font-size: 14px;
            color: var(--text);
            line-height: 1.5;
            white-space: pre-wrap;
            margin-bottom: 8px;
        }}

        .embed-fields {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: 8px;
            margin-top: 8px;
        }}

        .embed-field {{
            min-width: 0;
        }}

        .embed-field.inline {{
            grid-column: span 1;
        }}

        .embed-field:not(.inline) {{
            grid-column: 1 / -1;
        }}

        .embed-field-name {{
            font-size: 12px;
            font-weight: 600;
            color: var(--text);
            margin-bottom: 2px;
        }}

        .embed-field-value {{
            font-size: 13px;
            color: var(--text-muted);
            white-space: pre-wrap;
        }}

        .embed-image {{
            margin-top: 12px;
            max-width: 100%;
            border-radius: 4px;
        }}

        .embed-thumbnail {{
            float: right;
            margin-left: 16px;
            width: 80px;
            height: 80px;
            border-radius: 4px;
            object-fit: cover;
        }}

        .embed-footer {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 8px;
            font-size: 12px;
            color: var(--text-muted);
        }}

        .embed-footer-icon {{
            width: 20px;
            height: 20px;
            border-radius: 50%;
        }}

        /* ===== Footer ===== */
        .footer {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-top: none;
            border-radius: 0 0 var(--radius) var(--radius);
            padding: 20px;
            text-align: center;
            margin-bottom: 24px;
        }}

        .footer p {{
            font-size: 12px;
            color: var(--text-muted);
        }}

        .footer strong {{
            color: var(--gold);
        }}

        /* ===== Mobile Optimizations ===== */
        @media (max-width: 640px) {{
            .container {{
                padding: 0 12px;
            }}

            .header {{
                padding: 16px 0;
            }}

            .ticket-icon {{
                width: 40px;
                height: 40px;
                font-size: 20px;
            }}

            .header-info h1 {{
                font-size: 16px;
            }}

            .header-info p {{
                font-size: 12px;
            }}

            .status-badge {{
                padding: 5px 10px;
                font-size: 10px;
            }}

            .meta-grid {{
                grid-template-columns: 1fr 1fr;
                gap: 8px;
            }}

            .meta-card {{
                padding: 12px 14px;
            }}

            .meta-label {{
                font-size: 10px;
            }}

            .meta-value {{
                font-size: 13px;
            }}

            .message {{
                padding: 14px 16px;
                gap: 12px;
            }}

            .avatar {{
                width: 36px;
                height: 36px;
            }}

            .author {{
                font-size: 13px;
            }}

            .content {{
                font-size: 13px;
            }}

            .messages-header {{
                padding: 12px 16px;
            }}

            .attachment-image {{
                max-height: 200px;
            }}
        }}

        /* ===== Dark Mode Scrollbar ===== */
        ::-webkit-scrollbar {{
            width: 8px;
            height: 8px;
        }}

        ::-webkit-scrollbar-track {{
            background: var(--bg-dark);
        }}

        ::-webkit-scrollbar-thumb {{
            background: var(--border);
            border-radius: 4px;
        }}

        ::-webkit-scrollbar-thumb:hover {{
            background: #3a4a30;
        }}
    </style>
    {auto_refresh_script}
</head>
<body>
    <div class="app">
        <header class="header">
            <div class="container">
                <div class="header-content">
                    <div class="header-left">
                        <div class="ticket-icon">🎫</div>
                        <div class="header-info">
                            <h1>Ticket {ticket["ticket_id"]}</h1>
                            <p>{html_lib.escape(ticket["subject"][:40])}{"..." if len(ticket["subject"]) > 40 else ""}</p>
                        </div>
                    </div>
                    <div class="status-badge status-{ticket["status"]}">
                        {"<span class='live-indicator'></span>" if is_open else ""}
                        {ticket["status"].title()}
                    </div>
                </div>
            </div>
        </header>

        <main class="container">
            <section class="meta">
                <div class="meta-grid">
                    <div class="meta-card">
                        <div class="meta-label">Category</div>
                        <div class="meta-value">{cat_info["label"]}</div>
                    </div>
                    <div class="meta-card">
                        <div class="meta-label">Opened By</div>
                        <div class="meta-value gold">{html_lib.escape(user.display_name)}</div>
                    </div>
                    <div class="meta-card">
                        <div class="meta-label">Created</div>
                        <div class="meta-value">{created_dt.strftime("%b %d, %Y")}</div>
                    </div>
                    <div class="meta-card">
                        <div class="meta-label">Time</div>
                        <div class="meta-value">{created_dt.strftime("%I:%M %p")}</div>
                    </div>
                </div>
            </section>

            <section class="messages">
                <div class="messages-header">
                    <div class="messages-header-left">
                        <span>💬</span>
                        <span>Conversation</span>
                    </div>
                    <span class="message-count">{len(messages)} messages</span>
                </div>
                <div class="messages-list">
'''

    for msg in messages:
        author = msg.get("author", "Unknown")
        content = msg.get("content", "")
        timestamp = msg.get("timestamp", "")
        attachments = msg.get("attachments", [])
        embeds = msg.get("embeds", [])
        avatar_url = msg.get("avatar_url", "")

        # Determine author class and role badge
        author_class = "user"
        role_badge = ""
        if msg.get("is_bot", False):
            author_class = "bot"
            role_badge = '<span class="role-badge bot">BOT</span>'
        elif msg.get("is_staff", False):
            author_class = "staff"
            role_badge = '<span class="role-badge staff">STAFF</span>'

        # Escape HTML in content, then resolve mentions
        if content:
            safe_content = html_lib.escape(content)
            safe_content = _resolve_mentions(safe_content, mention_map)
        else:
            safe_content = '<span class="empty-message">(no text content)</span>'

        html_output += f'''
                    <div class="message">
                        <img class="avatar" src="{avatar_url or 'https://cdn.discordapp.com/embed/avatars/0.png'}" alt="" loading="lazy" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
                        <div class="message-body">
                            <div class="message-meta">
                                <span class="author {author_class}">{html_lib.escape(author)}</span>
                                {role_badge}
                                <span class="timestamp">{timestamp}</span>
                            </div>
                            <div class="content">{safe_content}</div>
'''
        # Render attachments
        if attachments:
            html_output += '                            <div class="attachments">\n'
            for att in attachments:
                filename = att.split("/")[-1].split("?")[0] if att else "attachment"
                is_image = any(filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp'])
                if is_image:
                    html_output += f'                                <a href="{att}" target="_blank"><img class="attachment-image" src="{att}" alt="{html_lib.escape(filename)}" loading="lazy"></a>\n'
                else:
                    html_output += f'                                <a class="attachment" href="{att}" target="_blank">📎 {html_lib.escape(filename[:25])}</a>\n'
            html_output += '                            </div>\n'

        # Render embeds
        for embed in embeds:
            if not embed:
                continue
            # Get embed color for border
            embed_color = f"#{embed.get('color', 0):06x}" if embed.get('color') else "var(--gold)"
            html_output += f'                            <div class="embed" style="border-left-color: {embed_color}">\n'

            # Thumbnail (floated right)
            if embed.get("thumbnail") and embed["thumbnail"].get("url"):
                html_output += f'                                <img class="embed-thumbnail" src="{embed["thumbnail"]["url"]}" alt="" loading="lazy">\n'

            # Author
            if embed.get("author"):
                author_data = embed["author"]
                html_output += '                                <div class="embed-author">\n'
                if author_data.get("icon_url"):
                    html_output += f'                                    <img class="embed-author-icon" src="{author_data["icon_url"]}" alt="">\n'
                author_name = html_lib.escape(author_data.get("name", ""))
                if author_data.get("url"):
                    html_output += f'                                    <a href="{author_data["url"]}" class="embed-author-name">{author_name}</a>\n'
                else:
                    html_output += f'                                    <span class="embed-author-name">{author_name}</span>\n'
                html_output += '                                </div>\n'

            # Title
            if embed.get("title"):
                title = html_lib.escape(embed["title"])
                if embed.get("url"):
                    html_output += f'                                <div class="embed-title"><a href="{embed["url"]}">{title}</a></div>\n'
                else:
                    html_output += f'                                <div class="embed-title">{title}</div>\n'

            # Description
            if embed.get("description"):
                desc = html_lib.escape(embed["description"])
                desc = _resolve_mentions(desc, mention_map)
                html_output += f'                                <div class="embed-description">{desc}</div>\n'

            # Fields
            if embed.get("fields"):
                html_output += '                                <div class="embed-fields">\n'
                for field in embed["fields"]:
                    inline_class = "inline" if field.get("inline") else ""
                    field_name = html_lib.escape(field.get("name", ""))
                    field_value = html_lib.escape(field.get("value", ""))
                    field_value = _resolve_mentions(field_value, mention_map)
                    html_output += f'                                    <div class="embed-field {inline_class}">\n'
                    html_output += f'                                        <div class="embed-field-name">{field_name}</div>\n'
                    html_output += f'                                        <div class="embed-field-value">{field_value}</div>\n'
                    html_output += '                                    </div>\n'
                html_output += '                                </div>\n'

            # Image
            if embed.get("image") and embed["image"].get("url"):
                html_output += f'                                <img class="embed-image" src="{embed["image"]["url"]}" alt="" loading="lazy">\n'

            # Footer
            if embed.get("footer"):
                footer_data = embed["footer"]
                html_output += '                                <div class="embed-footer">\n'
                if footer_data.get("icon_url"):
                    html_output += f'                                    <img class="embed-footer-icon" src="{footer_data["icon_url"]}" alt="">\n'
                if footer_data.get("text"):
                    html_output += f'                                    <span>{html_lib.escape(footer_data["text"])}</span>\n'
                html_output += '                                </div>\n'

            html_output += '                            </div>\n'

        html_output += '''                        </div>
                    </div>
'''

    html_output += f'''                </div>
            </section>

            <footer class="footer">
                <p>Generated {now_dt.strftime("%b %d, %Y at %I:%M %p")} • <strong>AzabBot</strong></p>
            </footer>
        </main>
    </div>
</body>
</html>'''

    return html_output


def create_transcript_file(
    ticket_id: str,
    html_content: str,
) -> discord.File:
    """
    Create a Discord file object from HTML content.

    Args:
        ticket_id: The ticket ID for filename
        html_content: The HTML transcript content

    Returns:
        Discord File object
    """
    buffer = io.BytesIO(html_content.encode('utf-8'))
    return discord.File(buffer, filename=f"transcript_{ticket_id}.html")


async def build_json_transcript(
    thread: discord.Thread,
    ticket: dict,
    bot: discord.Client,
    user: Optional[discord.User] = None,
    claimed_by: Optional[discord.Member] = None,
    closed_by: Optional[discord.Member] = None,
) -> Optional[TicketTranscript]:
    """
    Build a JSON transcript from a ticket thread for web viewer.

    Args:
        thread: The ticket thread
        ticket: Ticket data from database
        bot: The bot client for API calls
        user: The ticket creator
        claimed_by: Staff member who claimed the ticket
        closed_by: Staff member who closed the ticket

    Returns:
        TicketTranscript object or None if failed
    """
    try:
        logger.tree("Building Ticket JSON Transcript", [
            ("Ticket ID", ticket.get("ticket_id", "Unknown")),
            ("Thread ID", str(thread.id)),
            ("Thread Name", thread.name[:50] if thread.name else "Unknown"),
        ], emoji="📝")

        messages: List[TicketTranscriptMessage] = []

        async for msg in thread.history(limit=MAX_TRANSCRIPT_MESSAGES, oldest_first=True):
            # Build attachments
            attachments = []
            for att in msg.attachments:
                attachments.append(TicketTranscriptAttachment(
                    filename=att.filename,
                    url=att.url,
                    content_type=att.content_type,
                    size=att.size,
                ))

            # Check if staff
            is_staff = False
            if hasattr(msg.author, 'guild_permissions'):
                is_staff = msg.author.guild_permissions.manage_messages

            messages.append(TicketTranscriptMessage(
                author_id=msg.author.id,
                author_name=msg.author.name,
                author_display_name=msg.author.display_name,
                author_avatar_url=str(msg.author.display_avatar.url) if msg.author.display_avatar else None,
                content=msg.content,
                timestamp=msg.created_at.timestamp(),
                attachments=attachments,
                is_bot=msg.author.bot,
                is_staff=is_staff,
            ))

        transcript = TicketTranscript(
            ticket_id=ticket.get("ticket_id", ""),
            thread_id=thread.id,
            thread_name=thread.name,
            category=ticket.get("category", "support"),
            subject=ticket.get("subject", ""),
            status=ticket.get("status", "closed"),
            created_at=ticket.get("created_at", time.time()),
            closed_at=ticket.get("closed_at"),
            message_count=len(messages),
            messages=messages,
            user_id=user.id if user else ticket.get("user_id"),
            user_name=user.display_name if user else None,
            claimed_by_id=claimed_by.id if claimed_by else ticket.get("claimed_by"),
            claimed_by_name=claimed_by.display_name if claimed_by else None,
            closed_by_id=closed_by.id if closed_by else ticket.get("closed_by"),
            closed_by_name=closed_by.display_name if closed_by else None,
        )

        logger.tree("Ticket JSON Transcript Built", [
            ("Ticket ID", ticket.get("ticket_id", "Unknown")),
            ("Messages", str(len(messages))),
            ("User", f"{transcript.user_name} ({transcript.user_id})"),
        ], emoji="✅")

        return transcript

    except Exception as e:
        logger.error("Ticket JSON Transcript Build Failed", [
            ("Ticket ID", ticket.get("ticket_id", "Unknown")),
            ("Thread ID", str(thread.id)),
            ("Error", str(e)[:100]),
        ])
        return None
