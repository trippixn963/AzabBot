"""
AzabBot - Anti-Spam Detection Helpers
=====================================

Functions for detecting various types of spam patterns.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
from typing import List, Pattern

import discord

from .constants import (
    ARABIC_RANGE,
    ARABIC_TASHKEEL,
    CAPS_MIN_LENGTH,
    CHAR_REPEAT_LIMIT,
    CRYPTO_WALLET_PATTERN,
    DISCORD_INVITE_PATTERN,
    DUPLICATE_SIMILARITY_THRESHOLD,
    EXEMPT_ARABIC_GREETINGS,
    PHISHING_DOMAINS,
    SAFE_LINK_DOMAINS,
    SCAM_PHRASES,
    WHITELISTED_INVITE_CODES,
    ZALGO_COMBINING_LIMIT,
)


# =============================================================================
# Compiled Regex Patterns
# =============================================================================

LINK_PATTERN: Pattern = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')
EMOJI_PATTERN: Pattern = re.compile(r'<a?:\w+:\d+>|[\U0001F300-\U0001F9FF]')
CHAR_REPEAT_PATTERN: Pattern = re.compile(r'(.)\1{' + str(CHAR_REPEAT_LIMIT - 1) + r',}')
CRYPTO_WALLET_REGEX: Pattern = re.compile(CRYPTO_WALLET_PATTERN)


# =============================================================================
# Basic Content Analysis
# =============================================================================

def count_emojis(content: str) -> int:
    """Count emojis in message content."""
    return len(EMOJI_PATTERN.findall(content))


def count_links(content: str) -> int:
    """Count links in message content."""
    return len(LINK_PATTERN.findall(content))


def count_newlines(content: str) -> int:
    """Count newlines in message content."""
    return content.count('\n')


def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    # Remove protocol
    url = url.lower()
    if url.startswith("https://"):
        url = url[8:]
    elif url.startswith("http://"):
        url = url[7:]
    # Remove www.
    if url.startswith("www."):
        url = url[4:]
    # Get domain (before first /)
    domain = url.split("/")[0]
    return domain


def is_safe_link(url: str) -> bool:
    """Check if a link is from a safe/whitelisted domain."""
    domain = extract_domain(url)
    # Check exact match or subdomain match
    for safe_domain in SAFE_LINK_DOMAINS:
        if domain == safe_domain or domain.endswith("." + safe_domain):
            return True
    return False


def has_links(content: str) -> bool:
    """Check if content contains any links."""
    return bool(LINK_PATTERN.search(content))


def has_unsafe_links(content: str) -> bool:
    """Check if content contains non-whitelisted links (for spam detection)."""
    links = LINK_PATTERN.findall(content)
    for link in links:
        if not is_safe_link(link):
            return True
    return False


# =============================================================================
# Arabic Text Detection
# =============================================================================

def is_arabic_char(char: str) -> bool:
    """Check if a character is Arabic."""
    return ord(char) in ARABIC_RANGE if char else False


def strip_arabic_tashkeel(text: str) -> str:
    """Remove Arabic diacritical marks (tashkeel) from text."""
    return ''.join(c for c in text if c not in ARABIC_TASHKEEL)


def is_exempt_greeting(text: str) -> bool:
    """Check if text is a common Arabic/Islamic greeting (always exempt)."""
    if not text:
        return False
    # Normalize: strip whitespace, punctuation, and tashkeel
    normalized = text.strip().rstrip('!.،؟؛:')
    normalized = strip_arabic_tashkeel(normalized)
    return normalized in EXEMPT_ARABIC_GREETINGS


def is_mostly_arabic(text: str) -> bool:
    """Check if text is mostly Arabic (exempt from some spam checks)."""
    if not text:
        return False
    arabic_chars = sum(1 for c in text if ord(c) in ARABIC_RANGE)
    total_letters = sum(1 for c in text if c.isalpha())
    if total_letters == 0:
        return False
    # Lenient threshold - 30% Arabic is enough
    return (arabic_chars / total_letters) >= 0.3


# =============================================================================
# Spam Pattern Detection
# =============================================================================

def is_emoji_only(text: str) -> bool:
    """Check if message is mostly emojis (exempt from duplicate detection)."""
    if not text:
        return False
    # Remove custom Discord emojis <:name:id> and <a:name:id>
    text_no_custom = re.sub(r'<a?:\w+:\d+>', '', text)
    # Remove standard Unicode emojis
    text_no_emoji = EMOJI_PATTERN.sub('', text_no_custom)
    # Remove whitespace
    text_clean = text_no_emoji.strip()
    # If nothing left (or very little), it's emoji-only
    return len(text_clean) < 10


def has_char_repeat(content: str) -> bool:
    """Check for repeated characters (excluding Arabic)."""
    match = CHAR_REPEAT_PATTERN.search(content)
    if not match:
        return False
    repeated_char = match.group(1)
    if is_arabic_char(repeated_char):
        return False
    return True


def get_caps_percentage(content: str) -> float:
    """Get percentage of capital letters in content."""
    letters = [c for c in content if c.isalpha()]
    if len(letters) < CAPS_MIN_LENGTH:
        return 0
    caps = sum(1 for c in letters if c.isupper())
    return (caps / len(letters)) * 100


def is_similar(text1: str, text2: str) -> bool:
    """Check if two texts are similar using fuzzy matching."""
    if not text1 or not text2:
        return False
    ratio = SequenceMatcher(None, text1, text2).ratio()
    return ratio >= DUPLICATE_SIMILARITY_THRESHOLD


def count_combining_chars(content: str) -> int:
    """Count Unicode combining characters (used in Zalgo text), excluding Arabic tashkeel."""
    count = 0
    for c in content:
        if unicodedata.category(c) == 'Mn':
            if c not in ARABIC_TASHKEEL:
                count += 1
    return count


def is_zalgo(content: str) -> bool:
    """Check if text contains Zalgo/excessive combining characters."""
    # Skip Zalgo check entirely for Arabic text
    if is_mostly_arabic(content):
        return False
    return count_combining_chars(content) >= ZALGO_COMBINING_LIMIT


# =============================================================================
# Scam/Phishing Detection
# =============================================================================

def is_scam(content: str) -> bool:
    """Check if message contains scam/phishing patterns."""
    content_lower = content.lower()

    # Check scam phrases
    for phrase in SCAM_PHRASES:
        if phrase in content_lower:
            return True

    # Check phishing domains
    for domain in PHISHING_DOMAINS:
        if domain in content_lower:
            return True

    # Check crypto wallet + suspicious context
    if CRYPTO_WALLET_REGEX.search(content):
        suspicious_words = ["send", "gift", "free", "claim", "win", "airdrop"]
        if any(word in content_lower for word in suspicious_words):
            return True

    return False


# =============================================================================
# Invite Detection
# =============================================================================

def extract_invites(content: str) -> List[str]:
    """Extract Discord invite codes from message."""
    return DISCORD_INVITE_PATTERN.findall(content)


def is_whitelisted_invite(invite_code: str) -> bool:
    """Check if invite code is whitelisted."""
    return invite_code.lower() in WHITELISTED_INVITE_CODES


def has_non_whitelisted_invites(content: str) -> bool:
    """Check if content contains non-whitelisted invites."""
    invites = extract_invites(content)
    if not invites:
        return False
    non_whitelisted = [i for i in invites if not is_whitelisted_invite(i)]
    return bool(non_whitelisted)


# =============================================================================
# Image/Attachment Hashing
# =============================================================================

def hash_attachment(attachment: discord.Attachment) -> str:
    """Generate a hash for an attachment based on URL and size."""
    data = f"{attachment.filename}:{attachment.size}:{attachment.content_type}"
    return hashlib.md5(data.encode()).hexdigest()[:16]


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Patterns
    "LINK_PATTERN",
    "EMOJI_PATTERN",
    "CHAR_REPEAT_PATTERN",
    "CRYPTO_WALLET_REGEX",
    # Basic Content Analysis
    "count_emojis",
    "count_links",
    "count_newlines",
    "extract_domain",
    "is_safe_link",
    "has_links",
    "has_unsafe_links",
    # Arabic Text Detection
    "is_arabic_char",
    "strip_arabic_tashkeel",
    "is_exempt_greeting",
    "is_mostly_arabic",
    # Spam Pattern Detection
    "is_emoji_only",
    "has_char_repeat",
    "get_caps_percentage",
    "is_similar",
    "count_combining_chars",
    "is_zalgo",
    # Scam/Phishing Detection
    "is_scam",
    # Invite Detection
    "extract_invites",
    "is_whitelisted_invite",
    "has_non_whitelisted_invites",
    # Image/Attachment Hashing
    "hash_attachment",
]
