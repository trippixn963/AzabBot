"""
AzabBot - Ticket Transcript Package
====================================

HTML and JSON transcript generation for tickets.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .models import (
    TicketTranscriptAttachment,
    TicketTranscriptMessage,
    TicketTranscript,
)
from .collectors import (
    collect_transcript_messages,
    resolve_mentions,
)
from .html_generator import (
    generate_html_transcript,
    create_transcript_file,
)
from .json_builder import (
    build_json_transcript,
)

# Backwards compatibility aliases
_resolve_mentions = resolve_mentions

__all__ = [
    # Models
    "TicketTranscriptAttachment",
    "TicketTranscriptMessage",
    "TicketTranscript",
    # Collectors
    "collect_transcript_messages",
    "resolve_mentions",
    # HTML
    "generate_html_transcript",
    "create_transcript_file",
    # JSON
    "build_json_transcript",
    # Backwards compat
    "_resolve_mentions",
]
