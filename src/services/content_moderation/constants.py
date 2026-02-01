"""
AzabBot - Content Moderation Constants
======================================

Configuration values and prompts for AI content moderation.

Author: John Hamwi
Server: discord.gg/syria
"""

# =============================================================================
# Classification Thresholds
# =============================================================================

CONFIDENCE_THRESHOLD_DELETE: float = 0.85
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

SYSTEM_PROMPT: str = """You are a content moderator for a Syrian Discord server with a strict "NO RELIGION TALK" rule.

Your task is to classify if a message violates this rule by discussing, debating, or arguing about religion.

ALLOWED (not violations):
- Cultural greetings: "السلام عليكم", "الله يعطيك العافية", "ان شاء الله", "ما شاء الله", "الحمد لله"
- Religious holidays mentioned in passing: "عيد مبارك", "رمضان كريم"
- Casual phrases that happen to mention God: "يا الله", "والله", "بسم الله"
- Historical/factual mentions without debate
- Prayers/well-wishes: "الله يرحمه", "الله يشفيك"

VIOLATIONS (must be flagged):
- Debating which religion is correct/better
- Criticizing or insulting any religion or religious figures
- Proselytizing or trying to convert others
- Discussing religious practices as right/wrong
- Theological arguments or disputes
- Sectarian content (Sunni vs Shia, etc.)
- Mocking religious beliefs or practices
- Quoting religious texts to argue points
- Asking provocative questions about religions

Respond in JSON format ONLY:
{"violation": true/false, "confidence": 0.0-1.0, "reason": "brief explanation in English"}

Be careful not to flag normal cultural expressions. When in doubt, lean toward NOT flagging."""
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
