"""
Case Log Utilities
==================

Helper functions for duration parsing, formatting, and media validation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import re
from datetime import datetime
from typing import Optional


def has_valid_media_evidence(evidence: Optional[str]) -> bool:
    """
    Check if evidence contains a valid media attachment URL.

    Valid sources:
    - Discord CDN (cdn.discordapp.com, media.discordapp.net)
    - Direct image/video links (.png, .jpg, .gif, .mp4, .webm, etc.)
    - Image hosting sites (imgur, gyazo, postimg, ibb.co, etc.)
    - Cloud storage (Google Drive, Dropbox, OneDrive)
    - Video platforms (YouTube, Streamable, Medal.tv)

    Args:
        evidence: The evidence string to check.

    Returns:
        True if evidence contains valid media, False otherwise.
    """
    if not evidence:
        return False

    evidence_lower = evidence.lower()

    # Check for Discord CDN URLs
    discord_cdn_pattern = r'(cdn\.discordapp\.com|media\.discordapp\.net)/attachments/'
    if re.search(discord_cdn_pattern, evidence):
        return True

    # Check for direct media file extensions
    media_extensions = r'\.(png|jpg|jpeg|gif|webp|mp4|webm|mov|avi)(\?|$|\s)'
    if re.search(media_extensions, evidence, re.IGNORECASE):
        return True

    # Image hosting sites
    image_hosts = [
        'imgur.com', 'i.imgur.com',
        'gyazo.com', 'i.gyazo.com',
        'postimg.cc', 'postimg.org', 'i.postimg.cc',
        'ibb.co', 'i.ibb.co',
        'prnt.sc', 'prntscr.com',
        'lightshot.com',
        'tinypic.com',
        'imgbb.com',
        'flickr.com', 'flic.kr',
        'photobucket.com',
    ]
    if any(host in evidence_lower for host in image_hosts):
        return True

    # Cloud storage links
    cloud_hosts = [
        'drive.google.com',
        'docs.google.com',
        'dropbox.com', 'dl.dropboxusercontent.com',
        'onedrive.live.com', '1drv.ms',
        'icloud.com',
        'box.com',
        'mega.nz', 'mega.io',
    ]
    if any(host in evidence_lower for host in cloud_hosts):
        return True

    # Video platforms
    video_hosts = [
        'youtube.com', 'youtu.be',
        'streamable.com',
        'medal.tv',
        'twitch.tv', 'clips.twitch.tv',
        'vimeo.com',
        'gfycat.com',
        'tenor.com',
        'giphy.com',
        'reddit.com/gallery', 'i.redd.it', 'v.redd.it',
    ]
    if any(host in evidence_lower for host in video_hosts):
        return True

    return False


def parse_duration_to_seconds(duration: str) -> Optional[int]:
    """
    Parse duration string to seconds.

    Supports formats like: 1h, 30m, 1d, 2d12h, permanent, perm, forever

    Args:
        duration: Duration string.

    Returns:
        Total seconds, or None for permanent/invalid durations.
    """
    if not duration:
        return None

    duration_lower = duration.lower().strip()

    # Permanent durations
    if duration_lower in ("permanent", "perm", "forever", "indefinite"):
        return None

    total_seconds = 0

    # Match patterns like 1d, 2h, 30m, 15s
    pattern = r"(\d+)\s*(d|h|m|s)"
    matches = re.findall(pattern, duration_lower)

    if not matches:
        return None

    multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}

    for value, unit in matches:
        total_seconds += int(value) * multipliers.get(unit, 0)

    return total_seconds if total_seconds > 0 else None


def format_duration_precise(seconds: float) -> str:
    """
    Format duration with precision (seconds, minutes, hours, days).

    Args:
        seconds: Duration in seconds.

    Returns:
        Human-readable duration string.
    """
    seconds = int(seconds)

    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    elif seconds < 86400:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if minutes > 0:
            return f"{hours}h {minutes}m"
        return f"{hours} hour{'s' if hours != 1 else ''}"
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        if hours > 0:
            return f"{days}d {hours}h"
        return f"{days} day{'s' if days != 1 else ''}"


def format_age(start: datetime, end: datetime) -> str:
    """
    Format age as years, months, and days.

    Args:
        start: Start datetime.
        end: End datetime.

    Returns:
        Formatted string like "1y 6m 15d".
    """
    total_days = (end - start).days

    years = total_days // 365
    remaining_days = total_days % 365
    months = remaining_days // 30
    days = remaining_days % 30

    parts = []
    if years > 0:
        parts.append(f"{years}y")
    if months > 0:
        parts.append(f"{months}m")
    if days > 0 or not parts:
        parts.append(f"{days}d")

    return " ".join(parts)


def format_duration_short(duration: str) -> str:
    """
    Format duration for display (e.g., "1d 12h" or "Permanent").

    Args:
        duration: Duration string from database.

    Returns:
        Formatted display string.
    """
    if not duration:
        return "Unknown"

    duration_lower = duration.lower().strip()
    if duration_lower in ("permanent", "perm", "forever", "indefinite"):
        return "Permanent"

    return duration


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "has_valid_media_evidence",
    "parse_duration_to_seconds",
    "format_duration_precise",
    "format_age",
    "format_duration_short",
]
