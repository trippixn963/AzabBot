"""
AzabBot - Ticket HTML Transcript Generator
==========================================

Generates responsive HTML transcripts with gold/green theme.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import html as html_lib
import io
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

import discord

from src.core.config import NY_TZ
from src.core.logger import logger
from ..constants import TICKET_CATEGORIES
from .collectors import resolve_mentions


# =============================================================================
# CSS Styles
# =============================================================================

TRANSCRIPT_CSS = '''
:root {
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
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
    -webkit-tap-highlight-color: transparent;
}

html { scroll-behavior: smooth; }

body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg-dark);
    color: var(--text);
    min-height: 100vh;
    min-height: 100dvh;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
}

.app {
    min-height: 100vh;
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
}

.container {
    width: 100%;
    max-width: 800px;
    margin: 0 auto;
    padding: 0 16px;
}

.header {
    background: linear-gradient(135deg, var(--gold) 0%, var(--green-dark) 100%);
    padding: 24px 0;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
}

.header-content {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
}

.header-left {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
}

.ticket-icon {
    width: 48px;
    height: 48px;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    flex-shrink: 0;
}

.header-info { min-width: 0; }

.header-info h1 {
    font-size: 20px;
    font-weight: 700;
    color: white;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.header-info p {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.8);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.status-badge {
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
}

.status-open {
    background: rgba(34, 197, 94, 0.2);
    color: #4ade80;
    border: 1px solid rgba(34, 197, 94, 0.3);
}

.status-claimed {
    background: rgba(212, 175, 55, 0.2);
    color: var(--gold-light);
    border: 1px solid rgba(212, 175, 55, 0.3);
}

.status-closed {
    background: rgba(239, 68, 68, 0.2);
    color: #f87171;
    border: 1px solid rgba(239, 68, 68, 0.3);
}

.live-indicator {
    width: 8px;
    height: 8px;
    background: #4ade80;
    border-radius: 50%;
    animation: pulse 2s infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.9); }
}

.meta { padding: 20px 0; }

.meta-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
}

.meta-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 14px 16px;
}

.meta-card.full { grid-column: 1 / -1; }

.meta-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    margin-bottom: 4px;
}

.meta-value {
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.meta-value.gold { color: var(--gold); }

.messages {
    flex: 1;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius) var(--radius) 0 0;
    overflow: hidden;
    display: flex;
    flex-direction: column;
}

.messages-header {
    background: var(--bg-message);
    padding: 14px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 10;
}

.messages-header-left {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
    color: var(--gold);
}

.message-count {
    background: var(--border);
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
}

.messages-list {
    flex: 1;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
}

.message {
    display: flex;
    padding: 16px 20px;
    gap: 14px;
    border-bottom: 1px solid rgba(42, 58, 32, 0.5);
    transition: background 0.15s ease;
    animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

.message:hover { background: var(--bg-hover); }
.message:last-child { border-bottom: none; }

.avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    flex-shrink: 0;
    background: var(--border);
    object-fit: cover;
}

.message-body {
    flex: 1;
    min-width: 0;
}

.message-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
    flex-wrap: wrap;
}

.author {
    font-weight: 600;
    font-size: 14px;
}

.author.staff { color: var(--staff); }
.author.user { color: var(--user); }
.author.bot { color: var(--bot); }

.role-badge {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    padding: 2px 6px;
    border-radius: 4px;
    letter-spacing: 0.3px;
}

.role-badge.staff {
    background: rgba(212, 175, 55, 0.15);
    color: var(--gold);
}

.role-badge.bot {
    background: rgba(167, 139, 250, 0.15);
    color: var(--bot);
}

.timestamp {
    font-size: 12px;
    color: var(--text-muted);
}

.content {
    font-size: 14px;
    line-height: 1.6;
    color: var(--text);
    word-wrap: break-word;
    white-space: pre-wrap;
}

.mention {
    background: rgba(212, 175, 55, 0.15);
    color: var(--gold);
    padding: 1px 6px;
    border-radius: 4px;
    font-weight: 500;
}

.mention.channel {
    background: rgba(74, 222, 128, 0.15);
    color: var(--green);
}

.mention.role {
    background: rgba(167, 139, 250, 0.15);
    color: var(--bot);
}

.empty-message {
    color: var(--text-muted);
    font-style: italic;
}

.attachments {
    margin-top: 12px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}

.attachment {
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
}

.attachment:hover {
    background: var(--border);
    transform: translateY(-1px);
}

.attachment-image {
    max-width: 100%;
    max-height: 300px;
    border-radius: 8px;
    cursor: pointer;
    transition: transform 0.2s ease;
}

.attachment-image:hover { transform: scale(1.02); }

.embed {
    margin-top: 12px;
    background: var(--bg-dark);
    border-left: 4px solid var(--gold);
    border-radius: 4px;
    padding: 12px 16px;
    max-width: 520px;
}

.embed-author {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
}

.embed-author-icon {
    width: 24px;
    height: 24px;
    border-radius: 50%;
}

.embed-author-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
}

.embed-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--gold);
    margin-bottom: 8px;
}

.embed-title a {
    color: var(--gold);
    text-decoration: none;
}

.embed-title a:hover { text-decoration: underline; }

.embed-description {
    font-size: 14px;
    color: var(--text);
    line-height: 1.5;
    white-space: pre-wrap;
    margin-bottom: 8px;
}

.embed-fields {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 8px;
    margin-top: 8px;
}

.embed-field { min-width: 0; }
.embed-field.inline { grid-column: span 1; }
.embed-field:not(.inline) { grid-column: 1 / -1; }

.embed-field-name {
    font-size: 12px;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 2px;
}

.embed-field-value {
    font-size: 13px;
    color: var(--text-muted);
    white-space: pre-wrap;
}

.embed-image {
    margin-top: 12px;
    max-width: 100%;
    border-radius: 4px;
}

.embed-thumbnail {
    float: right;
    margin-left: 16px;
    width: 80px;
    height: 80px;
    border-radius: 4px;
    object-fit: cover;
}

.embed-footer {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
    font-size: 12px;
    color: var(--text-muted);
}

.embed-footer-icon {
    width: 20px;
    height: 20px;
    border-radius: 50%;
}

.footer {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-top: none;
    border-radius: 0 0 var(--radius) var(--radius);
    padding: 20px;
    text-align: center;
    margin-bottom: 24px;
}

.footer p {
    font-size: 12px;
    color: var(--text-muted);
}

.footer strong { color: var(--gold); }

@media (max-width: 640px) {
    .container { padding: 0 12px; }
    .header { padding: 16px 0; }
    .ticket-icon { width: 40px; height: 40px; font-size: 20px; }
    .header-info h1 { font-size: 16px; }
    .header-info p { font-size: 12px; }
    .status-badge { padding: 5px 10px; font-size: 10px; }
    .meta-grid { grid-template-columns: 1fr 1fr; gap: 8px; }
    .meta-card { padding: 12px 14px; }
    .meta-label { font-size: 10px; }
    .meta-value { font-size: 13px; }
    .message { padding: 14px 16px; gap: 12px; }
    .avatar { width: 36px; height: 36px; }
    .author { font-size: 13px; }
    .content { font-size: 13px; }
    .messages-header { padding: 12px 16px; }
    .attachment-image { max-height: 200px; }
}

::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg-dark); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #3a4a30; }
'''


# =============================================================================
# Auto-refresh Script
# =============================================================================

AUTO_REFRESH_SCRIPT = '''
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
'''


# =============================================================================
# HTML Generation
# =============================================================================

def generate_html_transcript(
    ticket: dict,
    messages: List[Dict[str, Any]],
    user: discord.User,
    closed_by: Optional[discord.Member] = None,
    mention_map: Optional[Dict[int, str]] = None,
) -> str:
    """
    Generate a modern, responsive HTML transcript with gold/green theme.

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
    auto_refresh = AUTO_REFRESH_SCRIPT if is_open else ""

    # Build messages HTML
    messages_html = _render_messages(messages, mention_map)

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
    <style>{TRANSCRIPT_CSS}</style>
    {auto_refresh}
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
{messages_html}
                </div>
            </section>

            <footer class="footer">
                <p>Generated {now_dt.strftime("%b %d, %Y at %I:%M %p")} • <strong>AzabBot</strong></p>
            </footer>
        </main>
    </div>
</body>
</html>'''

    logger.debug("HTML Transcript Generated", [
        ("Ticket ID", ticket["ticket_id"]),
        ("Messages", str(len(messages))),
        ("Status", ticket["status"]),
    ])

    return html_output


def _render_messages(messages: List[Dict[str, Any]], mention_map: Dict[int, str]) -> str:
    """Render messages to HTML."""
    html_parts = []

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
            safe_content = resolve_mentions(safe_content, mention_map)
        else:
            safe_content = '<span class="empty-message">(no text content)</span>'

        # Render attachments
        attachments_html = _render_attachments(attachments)

        # Render embeds
        embeds_html = _render_embeds(embeds, mention_map)

        html_parts.append(f'''
                    <div class="message">
                        <img class="avatar" src="{avatar_url or 'https://cdn.discordapp.com/embed/avatars/0.png'}" alt="" loading="lazy" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
                        <div class="message-body">
                            <div class="message-meta">
                                <span class="author {author_class}">{html_lib.escape(author)}</span>
                                {role_badge}
                                <span class="timestamp">{timestamp}</span>
                            </div>
                            <div class="content">{safe_content}</div>
{attachments_html}{embeds_html}
                        </div>
                    </div>''')

    return '\n'.join(html_parts)


def _render_attachments(attachments: List[str]) -> str:
    """Render attachments to HTML."""
    if not attachments:
        return ""

    parts = ['                            <div class="attachments">']
    for att in attachments:
        filename = att.split("/")[-1].split("?")[0] if att else "attachment"
        is_image = any(filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp'])
        if is_image:
            parts.append(f'                                <a href="{att}" target="_blank"><img class="attachment-image" src="{att}" alt="{html_lib.escape(filename)}" loading="lazy"></a>')
        else:
            parts.append(f'                                <a class="attachment" href="{att}" target="_blank">📎 {html_lib.escape(filename[:25])}</a>')
    parts.append('                            </div>')
    return '\n'.join(parts)


def _render_embeds(embeds: List[dict], mention_map: Dict[int, str]) -> str:
    """Render embeds to HTML."""
    if not embeds:
        return ""

    parts = []
    for embed in embeds:
        if not embed:
            continue

        embed_color = f"#{embed.get('color', 0):06x}" if embed.get('color') else "var(--gold)"
        embed_parts = [f'                            <div class="embed" style="border-left-color: {embed_color}">']

        # Thumbnail
        if embed.get("thumbnail") and embed["thumbnail"].get("url"):
            embed_parts.append(f'                                <img class="embed-thumbnail" src="{embed["thumbnail"]["url"]}" alt="" loading="lazy">')

        # Author
        if embed.get("author"):
            author_data = embed["author"]
            embed_parts.append('                                <div class="embed-author">')
            if author_data.get("icon_url"):
                embed_parts.append(f'                                    <img class="embed-author-icon" src="{author_data["icon_url"]}" alt="">')
            author_name = html_lib.escape(author_data.get("name", ""))
            if author_data.get("url"):
                embed_parts.append(f'                                    <a href="{author_data["url"]}" class="embed-author-name">{author_name}</a>')
            else:
                embed_parts.append(f'                                    <span class="embed-author-name">{author_name}</span>')
            embed_parts.append('                                </div>')

        # Title
        if embed.get("title"):
            title = html_lib.escape(embed["title"])
            if embed.get("url"):
                embed_parts.append(f'                                <div class="embed-title"><a href="{embed["url"]}">{title}</a></div>')
            else:
                embed_parts.append(f'                                <div class="embed-title">{title}</div>')

        # Description
        if embed.get("description"):
            desc = html_lib.escape(embed["description"])
            desc = resolve_mentions(desc, mention_map)
            embed_parts.append(f'                                <div class="embed-description">{desc}</div>')

        # Fields
        if embed.get("fields"):
            embed_parts.append('                                <div class="embed-fields">')
            for field in embed["fields"]:
                inline_class = "inline" if field.get("inline") else ""
                field_name = html_lib.escape(field.get("name", ""))
                field_value = html_lib.escape(field.get("value", ""))
                field_value = resolve_mentions(field_value, mention_map)
                embed_parts.append(f'                                    <div class="embed-field {inline_class}">')
                embed_parts.append(f'                                        <div class="embed-field-name">{field_name}</div>')
                embed_parts.append(f'                                        <div class="embed-field-value">{field_value}</div>')
                embed_parts.append('                                    </div>')
            embed_parts.append('                                </div>')

        # Image
        if embed.get("image") and embed["image"].get("url"):
            embed_parts.append(f'                                <img class="embed-image" src="{embed["image"]["url"]}" alt="" loading="lazy">')

        # Footer
        if embed.get("footer"):
            footer_data = embed["footer"]
            embed_parts.append('                                <div class="embed-footer">')
            if footer_data.get("icon_url"):
                embed_parts.append(f'                                    <img class="embed-footer-icon" src="{footer_data["icon_url"]}" alt="">')
            if footer_data.get("text"):
                embed_parts.append(f'                                    <span>{html_lib.escape(footer_data["text"])}</span>')
            embed_parts.append('                                </div>')

        embed_parts.append('                            </div>')
        parts.extend(embed_parts)

    return '\n'.join(parts)


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
    file_size = buffer.getbuffer().nbytes

    logger.debug("Transcript File Created", [
        ("Ticket ID", ticket_id),
        ("Filename", f"transcript_{ticket_id}.html"),
        ("Size", f"{file_size / 1024:.1f} KB"),
    ])

    return discord.File(buffer, filename=f"transcript_{ticket_id}.html")


__all__ = [
    "generate_html_transcript",
    "create_transcript_file",
    "TRANSCRIPT_CSS",
]
