"""
Mod Tracker Service - Constants
===============================

Configuration constants for the mod tracker service.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

# =============================================================================
# Retry Configuration
# =============================================================================

MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0  # seconds
RATE_LIMIT_DELAY = 1.5  # seconds between API calls
CACHE_TTL = 300  # 5 minutes cache for forum channel

# =============================================================================
# Inactivity Alerts
# =============================================================================

INACTIVITY_DAYS = 7  # Days before alerting about inactive mod

# =============================================================================
# Message Caching
# =============================================================================

MESSAGE_CACHE_SIZE = 50  # Messages to cache per mod
MESSAGE_CACHE_TTL = 3600  # 1 hour cache for messages

# =============================================================================
# Bulk Action Detection
# =============================================================================

BULK_ACTION_WINDOW = 300  # 5 minutes window
BULK_BAN_THRESHOLD = 5  # Bans in window to trigger alert
BULK_DELETE_THRESHOLD = 10  # Message deletes in window to trigger alert
BULK_TIMEOUT_THRESHOLD = 8  # Timeouts in window to trigger alert

# =============================================================================
# Suspicious Pattern Detection
# =============================================================================

SUSPICIOUS_UNBAN_WINDOW = 3600  # 1 hour - alert if unban within this time of ban
BAN_HISTORY_TTL = 86400  # 24 hours - how long to keep ban history

# =============================================================================
# Mass Permission Change Detection
# =============================================================================

MASS_PERMISSION_WINDOW = 300  # 5 minutes
MASS_PERMISSION_THRESHOLD = 5  # Permission changes in window to trigger alert
