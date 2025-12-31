"""
Mod Tracker Service - Constants
===============================

Configuration constants for the mod tracker service.
Imports shared constants from core and defines mod-tracker-specific values.

Author: John Hamwi
Server: discord.gg/syria
"""

from src.core.constants import (
    CACHE_TTL,
    MESSAGE_CACHE_TTL,
    MESSAGE_CACHE_SIZE,
    MESSAGE_CACHE_MAX_MODS,
    BULK_ACTION_WINDOW,
    BULK_DELETE_THRESHOLD,
    SUSPICIOUS_UNBAN_WINDOW,
    BAN_HISTORY_TTL,
    MASS_PERMISSION_WINDOW,
    TARGET_HARASSMENT_WINDOW,
    TARGET_HARASSMENT_THRESHOLD,
    TARGET_HARASSMENT_TTL,
    QUEUE_MAX_SIZE,
    SECONDS_PER_HOUR,
)

# =============================================================================
# Retry Configuration
# =============================================================================

MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0  # seconds
RATE_LIMIT_DELAY = 1.5  # seconds between API calls

# =============================================================================
# Inactivity Alerts
# =============================================================================

INACTIVITY_DAYS = 7  # Days before alerting about inactive mod

# =============================================================================
# Bulk Action Detection (thresholds)
# =============================================================================

BULK_BAN_THRESHOLD = 5  # Bans in window to trigger alert
BULK_TIMEOUT_THRESHOLD = 8  # Timeouts in window to trigger alert

# =============================================================================
# Mass Permission Change Detection
# =============================================================================

MASS_PERMISSION_THRESHOLD = 5  # Permission changes in window to trigger alert

# =============================================================================
# Priority Queue Configuration
# =============================================================================

# Priority levels (lower = higher priority)
PRIORITY_CRITICAL = 0  # Security alerts, raid detection
PRIORITY_HIGH = 1      # Harassment alerts, bulk action warnings
PRIORITY_NORMAL = 2    # Regular mod action logs
PRIORITY_LOW = 3       # Informational logs (avatar changes, etc.)

# Queue processing
QUEUE_PROCESS_INTERVAL = 0.5  # Seconds between processing items
QUEUE_BATCH_SIZE = 5  # Max items to process per batch (prioritized)
