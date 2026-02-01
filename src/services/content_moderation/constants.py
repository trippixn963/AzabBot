"""
AzabBot - Content Moderation Constants
======================================

Configuration values and prompts for AI content moderation.
"""

# =============================================================================
# Classification Thresholds
# =============================================================================

# Confidence threshold for taking action (0.0 - 1.0)
# Higher = fewer false positives but may miss some violations
CONFIDENCE_THRESHOLD_DELETE = 0.85  # Auto-delete threshold
CONFIDENCE_THRESHOLD_ALERT = 0.60   # Alert mods threshold

# Minimum message length to check (skip very short messages)
MIN_MESSAGE_LENGTH = 15

# Maximum message length to send to API (truncate longer messages)
MAX_MESSAGE_LENGTH = 2000

# =============================================================================
# Rate Limiting
# =============================================================================

# Maximum API calls per minute (to control costs)
MAX_API_CALLS_PER_MINUTE = 30

# Cooldown between checks for same user (seconds)
USER_CHECK_COOLDOWN = 5

# =============================================================================
# Caching
# =============================================================================

# Cache size for recent classifications (to avoid re-checking duplicates)
CLASSIFICATION_CACHE_SIZE = 500

# Cache TTL in seconds
CLASSIFICATION_CACHE_TTL = 300  # 5 minutes

# =============================================================================
# OpenAI Configuration
# =============================================================================

# Model to use (gpt-4o-mini is fast and cheap)
OPENAI_MODEL = "gpt-4o-mini"

# Max tokens for response
MAX_TOKENS = 100

# Temperature (lower = more deterministic)
TEMPERATURE = 0.1

# =============================================================================
# Classification Prompt
# =============================================================================

SYSTEM_PROMPT = """You are a content moderator for a Syrian Discord server with a strict "NO RELIGION TALK" rule.

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

USER_PROMPT_TEMPLATE = """Classify this message:
"{message}"

JSON response:"""

# =============================================================================
# Spam Types for Display
# =============================================================================

VIOLATION_TYPE = "Religion Discussion"
VIOLATION_EMOJI = "🕌"
