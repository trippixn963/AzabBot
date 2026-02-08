"""
AzabBot - Content Moderation Constants
======================================

Configuration values and prompts for AI content moderation.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# =============================================================================
# Classification Thresholds
# =============================================================================

CONFIDENCE_THRESHOLD_DELETE: float = 0.92
"""
Confidence threshold for auto-delete action (0.0 - 1.0).
Messages with confidence >= this value are automatically deleted.
Higher = fewer false positives but may miss some violations.
"""

CONFIDENCE_THRESHOLD_ALERT: float = 0.60
"""
Confidence threshold for alerting mods (0.0 - 1.0).
Messages with confidence >= this value (but < delete threshold)
are flagged for moderator review without deletion.
"""

MIN_MESSAGE_LENGTH: int = 15
"""
Minimum message length to check.
Messages shorter than this are skipped to avoid wasting API calls
on greetings and short phrases.
"""

MAX_MESSAGE_LENGTH: int = 2000
"""
Maximum message length to send to API.
Longer messages are truncated to control token usage and costs.
"""

# =============================================================================
# Rate Limiting
# =============================================================================

MAX_API_CALLS_PER_MINUTE: int = 30
"""
Maximum OpenAI API calls per minute.
Prevents runaway costs during spam attacks or high activity.
Typical cost at 30/min: ~$0.50/hour max at full utilization.
"""

USER_CHECK_COOLDOWN: int = 5
"""
Cooldown between checks for same user (seconds).
Prevents repeated API calls for rapid-fire messages from one user.
"""

# =============================================================================
# Caching
# =============================================================================

CLASSIFICATION_CACHE_SIZE: int = 500
"""
Maximum number of cached classifications.
Uses LRU eviction when limit is reached.
"""

CLASSIFICATION_CACHE_TTL: int = 300
"""
Cache TTL in seconds (5 minutes).
Cached results expire after this time to handle evolving context.
"""

# =============================================================================
# OpenAI Configuration
# =============================================================================

OPENAI_MODEL: str = "gpt-4o-mini"
"""
OpenAI model to use for classification.
gpt-4o-mini is fast (~500ms) and cheap (~$0.15/1M input tokens).
"""

MAX_TOKENS: int = 100
"""
Maximum tokens for API response.
Small value since we only need a short JSON response.
"""

TEMPERATURE: float = 0.1
"""
Model temperature (0.0 - 2.0).
Low value for more deterministic, consistent classifications.
"""

# =============================================================================
# Classification Prompt
# =============================================================================

SYSTEM_PROMPT: str = """You are a content moderator for a Syrian Discord server. Your ONLY task is detecting ACTIVE RELIGIOUS DEBATES or ATTACKS.

CRITICAL: Syrian/Arabic dialect uses religious words casually. This is NOT religious discussion:
- "اله" often means "له" (to him) in dialect, NOT "الله" (God)
- "والله", "يا الله", "الله يلعنك" = casual expressions, NOT religious
- Questions/complaints about people = NOT religious even if they mention beliefs
- Jokes, insults, regional banter = NOT religious unless explicitly about theology

NEVER FLAG (examples):
- "صار اله لسان" = dialect phrase, not religious
- "ليش انتوا مماحين" = "why are you annoying" = NOT religious
- "يلعن دينك" = common curse, NOT theological debate
- Regional jokes (Idlib, Homs, etc.) = NOT religious
- General complaints about people = NOT religious
- Anything questioning people's behavior (not their religion)

ONLY FLAG (very specific):
- "Islam is better than Christianity" = DEBATE
- "The Prophet was wrong about X" = ATTACK on religious figure
- "Sunnis/Shias are kafir" = SECTARIAN attack
- Quoting Quran/Bible to prove religious points = PROSELYTIZING
- "Why do Muslims believe X when Y" = PROVOCATIVE theological question

If the message is ambiguous or could be casual speech, DO NOT flag it.
Confidence should be 0.95+ ONLY for clear, unambiguous religious debates/attacks.

Respond in JSON format ONLY:
{"violation": true/false, "confidence": 0.0-1.0, "reason": "brief explanation"}

DEFAULT TO NOT FLAGGING. Only flag obvious, intentional religious debates."""
"""
System prompt for the OpenAI classifier.
Defines what constitutes a violation vs allowed cultural expressions.
"""

USER_PROMPT_TEMPLATE: str = """Classify this message:
"{message}"

JSON response:"""
"""
User prompt template with placeholder for message content.
"""

# =============================================================================
# Display Constants
# =============================================================================

VIOLATION_TYPE: str = "Religion Discussion"
"""Display name for this violation type in embeds and logs."""

VIOLATION_EMOJI: str = "🕌"
"""Emoji used for this violation type in embeds and logs."""


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "CONFIDENCE_THRESHOLD_DELETE",
    "CONFIDENCE_THRESHOLD_ALERT",
    "MIN_MESSAGE_LENGTH",
    "MAX_MESSAGE_LENGTH",
    "MAX_API_CALLS_PER_MINUTE",
    "USER_CHECK_COOLDOWN",
    "CLASSIFICATION_CACHE_SIZE",
    "CLASSIFICATION_CACHE_TTL",
    "OPENAI_MODEL",
    "MAX_TOKENS",
    "TEMPERATURE",
    "SYSTEM_PROMPT",
    "USER_PROMPT_TEMPLATE",
    "VIOLATION_TYPE",
    "VIOLATION_EMOJI",
]
