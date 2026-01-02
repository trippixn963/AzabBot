"""
Ticket Transcript Generator
===========================

HTML transcript generation for tickets.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import html as html_lib
import io
import re
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

import discord

from src.core.config import NY_TZ
from src.core.logger import logger

from .constants import TICKET_CATEGORIES, MAX_TRANSCRIPT_MESSAGES, MAX_TRANSCRIPT_USER_LOOKUPS


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
    Generate a beautiful HTML transcript with gold/green theme.

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

    # Gold/Green theme colors
    html_output = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ticket {ticket["ticket_id"]} - Transcript</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1f16 0%, #0d1810 100%);
            color: #e4e4e4;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #d4af37 0%, #228b22 100%);
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 40px rgba(212, 175, 55, 0.3);
        }}
        .header h1 {{
            font-size: 28px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 12px;
            color: #fff;
            text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
        }}
        .header h1 .emoji {{ font-size: 32px; }}
        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        .meta-item {{
            background: rgba(0,0,0,0.2);
            padding: 12px 16px;
            border-radius: 8px;
        }}
        .meta-item .label {{
            font-size: 12px;
            text-transform: uppercase;
            opacity: 0.8;
            margin-bottom: 4px;
            color: #fff;
        }}
        .meta-item .value {{
            font-size: 16px;
            font-weight: 600;
            color: #fff;
        }}
        .messages {{
            background: #12170f;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.4);
            border: 1px solid #2a3a20;
        }}
        .messages-header {{
            background: linear-gradient(90deg, #1a2515 0%, #1f2a18 100%);
            padding: 16px 20px;
            border-bottom: 1px solid #2a3a20;
            font-weight: 600;
            color: #d4af37;
        }}
        .message {{
            display: flex;
            padding: 16px 20px;
            border-bottom: 1px solid #1e2819;
            transition: background 0.2s;
        }}
        .message:hover {{
            background: rgba(212, 175, 55, 0.03);
        }}
        .message:last-child {{
            border-bottom: none;
        }}
        .avatar {{
            width: 44px;
            height: 44px;
            border-radius: 50%;
            margin-right: 16px;
            flex-shrink: 0;
            background: #2a3a20;
            border: 2px solid #3a4a30;
        }}
        .message-content {{
            flex: 1;
            min-width: 0;
        }}
        .message-header {{
            display: flex;
            align-items: baseline;
            gap: 8px;
            margin-bottom: 6px;
        }}
        .author {{
            font-weight: 600;
            color: #4ade80;
        }}
        .author.staff {{
            color: #d4af37;
        }}
        .author.bot {{
            color: #a78bfa;
        }}
        .timestamp {{
            font-size: 12px;
            color: #6b7c5a;
        }}
        .content {{
            line-height: 1.5;
            word-wrap: break-word;
            white-space: pre-wrap;
            color: #d1d5db;
        }}
        .mention {{
            background: rgba(212, 175, 55, 0.2);
            color: #d4af37;
            padding: 1px 4px;
            border-radius: 4px;
            font-weight: 500;
        }}
        .mention.channel {{
            background: rgba(74, 222, 128, 0.2);
            color: #4ade80;
        }}
        .mention.role {{
            background: rgba(167, 139, 250, 0.2);
            color: #a78bfa;
        }}
        .mention.unknown {{
            background: rgba(107, 114, 128, 0.2);
            color: #9ca3af;
        }}
        .attachments {{
            margin-top: 10px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .attachment {{
            background: #1e2819;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 13px;
            color: #4ade80;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            border: 1px solid #2a3a20;
        }}
        .attachment:hover {{
            background: #2a3a20;
            border-color: #3a4a30;
        }}
        .attachment-image {{
            max-width: 400px;
            max-height: 300px;
            border-radius: 8px;
            cursor: pointer;
            transition: transform 0.2s;
            border: 1px solid #2a3a20;
        }}
        .attachment-image:hover {{
            transform: scale(1.02);
        }}
        .footer {{
            text-align: center;
            padding: 30px;
            color: #6b7c5a;
            font-size: 14px;
        }}
        .footer strong {{
            color: #d4af37;
        }}
        .status-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .status-open {{ background: #228b22; color: #fff; }}
        .status-claimed {{ background: #d4af37; color: #000; }}
        .status-closed {{ background: #8b0000; color: #fff; }}
        .empty-message {{
            color: #6b7c5a;
            font-style: italic;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><span class="emoji">🎫</span> Ticket {ticket["ticket_id"]}</h1>
            <div class="meta-grid">
                <div class="meta-item">
                    <div class="label">Category</div>
                    <div class="value">{cat_info["label"]}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Status</div>
                    <div class="value"><span class="status-badge status-{ticket["status"]}">{ticket["status"].title()}</span></div>
                </div>
                <div class="meta-item">
                    <div class="label">Opened By</div>
                    <div class="value">{html_lib.escape(user.display_name)}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Created</div>
                    <div class="value">{created_dt.strftime("%b %d, %Y %I:%M %p")}</div>
                </div>
                <div class="meta-item">
                    <div class="label">Subject</div>
                    <div class="value">{html_lib.escape(ticket["subject"][:50])}{"..." if len(ticket["subject"]) > 50 else ""}</div>
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

        # Determine author class
        author_class = ""
        if msg.get("is_bot", False):
            author_class = "bot"
        elif msg.get("is_staff", False):
            author_class = "staff"

        # Escape HTML in content, then resolve mentions
        if content:
            safe_content = html_lib.escape(content)
            safe_content = _resolve_mentions(safe_content, mention_map)
        else:
            safe_content = '<span class="empty-message">(no text content)</span>'

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
                # Check if it's an image
                is_image = any(filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp'])
                if is_image:
                    html_output += f'                        <a href="{att}" target="_blank"><img class="attachment-image" src="{att}" alt="{html_lib.escape(filename)}" loading="lazy"></a>\n'
                else:
                    html_output += f'                        <a class="attachment" href="{att}" target="_blank">📎 {html_lib.escape(filename[:30])}</a>\n'
            html_output += '                    </div>\n'

        html_output += '''                </div>
            </div>
'''

    html_output += f'''        </div>

        <div class="footer">
            Generated on {now_dt.strftime("%B %d, %Y at %I:%M %p %Z")}<br>
            <strong>🎫 AzabBot Ticket System</strong>
        </div>
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
