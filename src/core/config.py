"""
Azab Discord Bot - Configuration Module
========================================

Centralized configuration management with environment variable validation.

DESIGN:
    This module provides a single source of truth for all configuration,
    loaded from environment variables at startup. Using a dataclass ensures
    type safety and immutability once loaded.

    Key patterns:
    - Singleton pattern via get_config() ensures one Config instance
    - Validation happens once at load time, not on every access
    - Permission helpers centralize authorization logic

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
from dataclasses import dataclass
from typing import Optional, Set
from zoneinfo import ZoneInfo


# =============================================================================
# Timezone Configuration
# =============================================================================

NY_TZ = ZoneInfo("America/New_York")
"""
Eastern timezone for consistent timestamps across all bot operations.

DESIGN:
    Using America/New_York instead of a fixed UTC offset ensures automatic
    handling of EST/EDT transitions. All log timestamps and scheduled
    operations use this timezone.
"""


# =============================================================================
# Configuration Dataclass
# =============================================================================

@dataclass
class Config:
    """
    Bot configuration loaded from environment variables.

    DESIGN:
        Required fields raise ConfigValidationError if missing.
        Optional fields have sensible defaults for development.
        All IDs are integers to prevent string comparison bugs.

    Attributes:
        discord_token: Discord bot authentication token.
        developer_id: User ID of the bot developer.
        logs_channel_id: Channel ID for mod action logs.
        prison_channel_ids: Set of channel IDs where prisoners can be roasted.
        general_channel_id: Main server channel ID.
        muted_role_id: Role ID assigned to muted/timed-out users.
        openai_api_key: OpenAI API key for AI responses.
    """

    # -------------------------------------------------------------------------
    # Required: Discord
    # -------------------------------------------------------------------------

    discord_token: str
    developer_id: int

    # -------------------------------------------------------------------------
    # Required: Channels
    # -------------------------------------------------------------------------

    logs_channel_id: int
    prison_channel_ids: Set[int]
    general_channel_id: int

    # -------------------------------------------------------------------------
    # Required: Roles
    # -------------------------------------------------------------------------

    muted_role_id: int

    # -------------------------------------------------------------------------
    # Required: OpenAI
    # -------------------------------------------------------------------------

    openai_api_key: str

    # -------------------------------------------------------------------------
    # Optional: Channels
    # -------------------------------------------------------------------------

    polls_only_channel_id: Optional[int] = None
    permanent_polls_channel_id: Optional[int] = None
    case_log_forum_id: Optional[int] = None
    links_allowed_channel_id: Optional[int] = None
    alliances_channel_id: Optional[int] = None  # Channel for alliance posts (auto-delete on leave)
    verification_role_id: Optional[int] = None  # Role given to verified members

    # -------------------------------------------------------------------------
    # Optional: Roles
    # -------------------------------------------------------------------------

    moderation_role_id: Optional[int] = None

    # -------------------------------------------------------------------------
    # Optional: Mod Tracker
    # -------------------------------------------------------------------------

    mod_server_id: Optional[int] = None
    mod_tracker_forum_id: Optional[int] = None
    alert_channel_id: Optional[int] = None  # Channel for critical alerts (raids, nuke attempts)

    # -------------------------------------------------------------------------
    # Optional: Appeals
    # -------------------------------------------------------------------------

    appeal_forum_id: Optional[int] = None  # Forum channel for ban/mute appeals

    # -------------------------------------------------------------------------
    # Optional: Tickets
    # -------------------------------------------------------------------------

    ticket_channel_id: Optional[int] = None  # Text channel for ticket threads
    ticket_staff_role_id: Optional[int] = None  # Role that can manage tickets
    ticket_partnership_user_id: Optional[int] = None  # User to assign partnership tickets
    ticket_suggestion_user_id: Optional[int] = None  # User to assign suggestion tickets
    ticket_support_user_ids: Set[int] = None  # Users to assign support tickets

    # -------------------------------------------------------------------------
    # Optional: Modmail (for banned users)
    # -------------------------------------------------------------------------

    modmail_forum_id: Optional[int] = None  # Forum channel for modmail threads (mods server)

    # -------------------------------------------------------------------------
    # Optional: Server Logs
    # -------------------------------------------------------------------------

    server_logs_forum_id: Optional[int] = None
    logging_guild_id: Optional[int] = None  # Main guild ID (for logging and cross-server moderation)

    # -------------------------------------------------------------------------
    # Optional: Lockdown Exclusions
    # -------------------------------------------------------------------------

    lockdown_exclude_ids: Set[int] = None  # Channel/category IDs to exclude from lockdown

    # -------------------------------------------------------------------------
    # Optional: Command Permissions
    # -------------------------------------------------------------------------

    link_allowed_user_ids: Set[int] = None  # User IDs allowed to use /link command
    appeal_allowed_user_ids: Set[int] = None  # User IDs allowed to approve/deny appeals

    # -------------------------------------------------------------------------
    # Optional: AI Settings
    # -------------------------------------------------------------------------

    ai_model: str = "gpt-4o-mini"
    response_probability: int = 70
    max_response_length: int = 150

    # -------------------------------------------------------------------------
    # Optional: Rate Limiting
    # -------------------------------------------------------------------------

    cooldown_seconds: int = 10
    prisoner_cooldown_seconds: int = 30

    # -------------------------------------------------------------------------
    # Optional: Scheduler Intervals (seconds)
    # -------------------------------------------------------------------------

    mute_check_interval: int = 30           # How often to check for expired mutes
    presence_update_interval: int = 30      # How often to rotate presence status
    presence_retry_delay: int = 5           # Delay before retrying presence update
    hourly_task_interval: int = 3600        # Interval for hourly background tasks
    rate_limit_delay: float = 1.0           # Delay between rate-limited operations

    # -------------------------------------------------------------------------
    # Optional: Limits
    # -------------------------------------------------------------------------

    mute_reason_max_length: int = 100
    message_content_max_length: int = 500
    log_truncate_length: int = 50
    prison_message_scan_limit: int = 500
    polls_cleanup_limit: int = 100
    message_history_size: int = 10
    log_retention_days: int = 30  # Auto-delete logs older than this (0 = disabled)

    # -------------------------------------------------------------------------
    # Optional: Display
    # -------------------------------------------------------------------------

    developer_name: str = "حَـــــنَّـــــا"
    server_name: str = "discord.gg/syria"

    # -------------------------------------------------------------------------
    # Optional: Permissions
    # -------------------------------------------------------------------------

    moderator_ids: Set[int] = None

    # -------------------------------------------------------------------------
    # Optional: Webhooks
    # -------------------------------------------------------------------------

    alert_webhook_url: Optional[str] = None
    error_webhook_url: Optional[str] = None
    interaction_webhook_url: Optional[str] = None

    # -------------------------------------------------------------------------
    # Optional: Logging Exclusions
    # -------------------------------------------------------------------------

    ignored_bot_ids: Set[int] = None  # Bot IDs to exclude from logging


# =============================================================================
# Embed Colors
# =============================================================================

class EmbedColors:
    """
    Standardized color palette for Discord embeds.

    Public embeds: GREEN and GOLD only (matches TahaBot/OthmanBot)
    Internal logs: Can use full palette including RED
    """

    # Primary colors (TahaBot/OthmanBot color scheme - for public embeds)
    GREEN = 0x1F5E2E    # #1F5E2E - Primary success/positive
    GOLD = 0xE6B84A     # #E6B84A - Warnings/info/neutral

    # Extended colors (for internal logs only)
    RED = 0xDC3545      # #DC3545 - Negative actions (bans, kicks, deletes)
    BLUE = 0x3498DB     # #3498DB - Informational logs
    PURPLE = 0x9B59B6   # #9B59B6 - Appeals
    TEAL = 0x1ABC9C     # #1ABC9C - Modmail
    ORANGE = 0xFF9800   # #FF9800 - High priority / warnings
    BLURPLE = 0x5865F2  # #5865F2 - Discord blurple / info

    # Semantic aliases for clarity
    SUCCESS = GREEN     # ✅ Operation completed, positive actions
    ERROR = GOLD        # ⚠️ Errors, failures (using gold for visibility on public)
    WARNING = GOLD      # ⚠️ Caution, warnings
    INFO = GREEN        # ℹ️ Informational
    PRISON = GOLD       # 🔒 Prisoner context, mutes
    RELEASE = GREEN     # 🔓 Freedom, unmutes

    # Log-specific colors (internal use)
    LOG_NEGATIVE = RED  # 🔴 Bans, kicks, deletes, leaves
    LOG_WARNING = GOLD  # 🟡 Timeouts, edits, warnings
    LOG_POSITIVE = GREEN  # 🟢 Joins, unbans, boosts
    LOG_INFO = BLUE     # 🔵 Channel updates, role changes

    # Service-specific colors (for interaction logger)
    TICKET = BLUE       # 🎫 Ticket actions
    APPEAL = PURPLE     # 📨 Appeal actions
    MODMAIL = TEAL      # 📬 Modmail actions
    PRIORITY_LOW = 0x95A5A6     # Gray
    PRIORITY_NORMAL = BLUE      # Blue
    PRIORITY_HIGH = ORANGE      # Orange
    PRIORITY_URGENT = RED       # Red


# =============================================================================
# Validation
# =============================================================================

class ConfigValidationError(Exception):
    """
    Raised when required configuration is missing or invalid.

    DESIGN:
        Custom exception type allows callers to distinguish config
        errors from other startup failures.
    """

    pass


def _parse_int(value: Optional[str], name: str) -> int:
    """
    Parse string to integer with descriptive error handling.

    Args:
        value: String value from environment variable.
        name: Variable name for error messages.

    Returns:
        Parsed integer value.

    Raises:
        ConfigValidationError: If value is missing or not a valid integer.
    """
    if not value:
        raise ConfigValidationError(f"Missing required: {name}")
    try:
        return int(value)
    except ValueError:
        raise ConfigValidationError(f"Invalid integer for {name}: {value}")


def _parse_int_optional(value: Optional[str]) -> Optional[int]:
    """
    Parse optional string to integer, returning None on failure.

    Args:
        value: String value from environment variable, may be None.

    Returns:
        Parsed integer or None if parsing fails.
    """
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_int_set(value: Optional[str]) -> Set[int]:
    """
    Parse comma-separated string to set of integers.

    Args:
        value: Comma-separated string of integers (e.g., "123,456,789").

    Returns:
        Set of parsed integers, empty set if input is None or empty.
    """
    if not value:
        return set()
    result = set()
    for part in value.split(","):
        part = part.strip()
        if part:
            try:
                result.add(int(part))
            except ValueError:
                pass  # Skip invalid entries silently
    return result


def _parse_int_with_default(value: Optional[str], default: int, name: str, min_val: int = None, max_val: int = None) -> int:
    """
    Parse optional integer with default and range validation.

    Args:
        value: String value from environment variable.
        default: Default value if not set or invalid.
        name: Variable name for warning messages.
        min_val: Minimum allowed value (inclusive).
        max_val: Maximum allowed value (inclusive).

    Returns:
        Parsed integer within valid range, or default.
    """
    if not value:
        return default
    try:
        parsed = int(value)
        if min_val is not None and parsed < min_val:
            from src.core.logger import logger
            logger.warning(f"Config {name}={parsed} below min {min_val}, using {min_val}")
            return min_val
        if max_val is not None and parsed > max_val:
            from src.core.logger import logger
            logger.warning(f"Config {name}={parsed} above max {max_val}, using {max_val}")
            return max_val
        return parsed
    except ValueError:
        from src.core.logger import logger
        logger.warning(f"Config {name}='{value}' invalid, using default {default}")
        return default


def _validate_url(value: Optional[str], name: str) -> Optional[str]:
    """
    Validate URL format for webhooks.

    Args:
        value: URL string to validate.
        name: Variable name for warning messages.

    Returns:
        URL if valid, None if invalid or empty.
    """
    if not value:
        return None
    if not value.startswith(("https://", "http://")):
        from src.core.logger import logger
        logger.warning(f"Config {name} invalid URL format, ignoring")
        return None
    return value


# =============================================================================
# Configuration Loading
# =============================================================================

def load_config() -> Config:
    """
    Load and validate configuration from environment variables.

    DESIGN:
        Validates all required variables upfront before creating the
        Config object. This fail-fast approach prevents partial
        initialization and unclear runtime errors.

    Returns:
        Validated Config object with all settings.

    Raises:
        ConfigValidationError: If any required variable is missing or invalid.
    """
    missing = []

    # -------------------------------------------------------------------------
    # Collect Required Variables
    # -------------------------------------------------------------------------

    discord_token = os.getenv("DISCORD_TOKEN")
    if not discord_token:
        missing.append("DISCORD_TOKEN")

    developer_id_str = os.getenv("DEVELOPER_ID")
    if not developer_id_str:
        missing.append("DEVELOPER_ID")

    logs_channel_id_str = os.getenv("LOGS_CHANNEL_ID")
    if not logs_channel_id_str:
        missing.append("LOGS_CHANNEL_ID")

    prison_channel_ids_str = os.getenv("PRISON_CHANNEL_IDS")
    if not prison_channel_ids_str:
        missing.append("PRISON_CHANNEL_IDS")

    general_channel_id_str = os.getenv("GENERAL_CHANNEL_ID")
    if not general_channel_id_str:
        missing.append("GENERAL_CHANNEL_ID")

    muted_role_id_str = os.getenv("MUTED_ROLE_ID")
    if not muted_role_id_str:
        missing.append("MUTED_ROLE_ID")

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        missing.append("OPENAI_API_KEY")

    # -------------------------------------------------------------------------
    # Fail Fast on Missing Required
    # -------------------------------------------------------------------------

    if missing:
        raise ConfigValidationError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    # -------------------------------------------------------------------------
    # Parse Required Values
    # -------------------------------------------------------------------------

    developer_id = _parse_int(developer_id_str, "DEVELOPER_ID")
    logs_channel_id = _parse_int(logs_channel_id_str, "LOGS_CHANNEL_ID")
    prison_channel_ids = _parse_int_set(prison_channel_ids_str)
    general_channel_id = _parse_int(general_channel_id_str, "GENERAL_CHANNEL_ID")
    muted_role_id = _parse_int(muted_role_id_str, "MUTED_ROLE_ID")

    # -------------------------------------------------------------------------
    # Parse Optional Values
    # -------------------------------------------------------------------------

    polls_only_channel_id = _parse_int_optional(os.getenv("POLLS_ONLY_CHANNEL_ID"))
    permanent_polls_channel_id = _parse_int_optional(os.getenv("PERMANENT_POLLS_CHANNEL_ID"))
    case_log_forum_id = _parse_int_optional(os.getenv("CASE_LOG_FORUM_ID"))
    links_allowed_channel_id = _parse_int_optional(os.getenv("LINKS_ALLOWED_CHANNEL_ID"))
    alliances_channel_id = _parse_int_optional(os.getenv("ALLIANCES_CHANNEL_ID"))
    verification_role_id = _parse_int_optional(os.getenv("VERIFICATION_ROLE_ID"))
    moderation_role_id = _parse_int_optional(os.getenv("MODERATION_ROLE_ID"))
    mod_server_id = _parse_int_optional(os.getenv("MOD_SERVER_ID"))
    mod_tracker_forum_id = _parse_int_optional(os.getenv("MOD_TRACKER_FORUM_ID"))
    alert_channel_id = _parse_int_optional(os.getenv("ALERT_CHANNEL_ID"))
    appeal_forum_id = _parse_int_optional(os.getenv("APPEAL_FORUM_ID"))
    ticket_channel_id = _parse_int_optional(os.getenv("TICKET_CHANNEL_ID"))
    ticket_staff_role_id = _parse_int_optional(os.getenv("TICKET_STAFF_ROLE_ID"))
    ticket_partnership_user_id = _parse_int_optional(os.getenv("TICKET_PARTNERSHIP_USER_ID"))
    ticket_suggestion_user_id = _parse_int_optional(os.getenv("TICKET_SUGGESTION_USER_ID"))
    ticket_support_user_ids = _parse_int_set(os.getenv("TICKET_SUPPORT_USER_IDS", ""))
    server_logs_forum_id = _parse_int_optional(os.getenv("SERVER_LOGS_FORUM_ID"))
    logging_guild_id = _parse_int_optional(os.getenv("LOGGING_GUILD_ID"))
    moderator_ids = _parse_int_set(os.getenv("MODERATOR_IDS"))
    ignored_bot_ids = _parse_int_set(os.getenv("IGNORED_BOT_IDS"))
    lockdown_exclude_ids = _parse_int_set(os.getenv("LOCKDOWN_EXCLUDE_IDS"))
    link_allowed_user_ids = _parse_int_set(os.getenv("LINK_ALLOWED_USER_IDS"))
    appeal_allowed_user_ids = _parse_int_set(os.getenv("APPEAL_ALLOWED_USER_IDS"))
    modmail_forum_id = _parse_int_optional(os.getenv("MODMAIL_FORUM_ID"))

    # -------------------------------------------------------------------------
    # Build Config Object
    # -------------------------------------------------------------------------

    return Config(
        discord_token=discord_token,
        developer_id=developer_id,
        logs_channel_id=logs_channel_id,
        prison_channel_ids=prison_channel_ids,
        general_channel_id=general_channel_id,
        muted_role_id=muted_role_id,
        openai_api_key=openai_api_key,
        polls_only_channel_id=polls_only_channel_id,
        permanent_polls_channel_id=permanent_polls_channel_id,
        case_log_forum_id=case_log_forum_id,
        links_allowed_channel_id=links_allowed_channel_id,
        alliances_channel_id=alliances_channel_id,
        verification_role_id=verification_role_id,
        moderation_role_id=moderation_role_id,
        mod_server_id=mod_server_id,
        mod_tracker_forum_id=mod_tracker_forum_id,
        alert_channel_id=alert_channel_id,
        appeal_forum_id=appeal_forum_id,
        ticket_channel_id=ticket_channel_id,
        ticket_staff_role_id=ticket_staff_role_id,
        ticket_partnership_user_id=ticket_partnership_user_id,
        ticket_suggestion_user_id=ticket_suggestion_user_id,
        ticket_support_user_ids=ticket_support_user_ids,
        server_logs_forum_id=server_logs_forum_id,
        logging_guild_id=logging_guild_id,
        ai_model=os.getenv("AI_MODEL", "gpt-4o-mini"),
        response_probability=_parse_int_with_default(
            os.getenv("RESPONSE_PROBABILITY"), 70, "RESPONSE_PROBABILITY", min_val=0, max_val=100
        ),
        max_response_length=_parse_int_with_default(
            os.getenv("MAX_RESPONSE_LENGTH"), 150, "MAX_RESPONSE_LENGTH", min_val=10, max_val=2000
        ),
        cooldown_seconds=_parse_int_with_default(
            os.getenv("COOLDOWN_SECONDS"), 10, "COOLDOWN_SECONDS", min_val=0, max_val=300
        ),
        prisoner_cooldown_seconds=_parse_int_with_default(
            os.getenv("PRISONER_COOLDOWN_SECONDS"), 30, "PRISONER_COOLDOWN_SECONDS", min_val=0, max_val=600
        ),
        mute_reason_max_length=_parse_int_with_default(
            os.getenv("MUTE_REASON_MAX_LENGTH"), 100, "MUTE_REASON_MAX_LENGTH", min_val=10, max_val=500
        ),
        message_content_max_length=_parse_int_with_default(
            os.getenv("MESSAGE_CONTENT_MAX_LENGTH"), 500, "MESSAGE_CONTENT_MAX_LENGTH", min_val=50, max_val=2000
        ),
        log_truncate_length=_parse_int_with_default(
            os.getenv("LOG_TRUNCATE_LENGTH"), 50, "LOG_TRUNCATE_LENGTH", min_val=10, max_val=500
        ),
        prison_message_scan_limit=_parse_int_with_default(
            os.getenv("PRISON_MESSAGE_SCAN_LIMIT"), 500, "PRISON_MESSAGE_SCAN_LIMIT", min_val=10, max_val=1000
        ),
        developer_name=os.getenv("DEVELOPER_NAME", "حَـــــنَّـــــا"),
        server_name=os.getenv("SERVER_NAME", "discord.gg/syria"),
        moderator_ids=moderator_ids if moderator_ids else None,
        alert_webhook_url=_validate_url(os.getenv("ALERT_WEBHOOK_URL"), "ALERT_WEBHOOK_URL"),
        error_webhook_url=_validate_url(os.getenv("ERROR_WEBHOOK_URL"), "ERROR_WEBHOOK_URL"),
        interaction_webhook_url=_validate_url(os.getenv("INTERACTION_WEBHOOK_URL"), "INTERACTION_WEBHOOK_URL"),
        ignored_bot_ids=ignored_bot_ids if ignored_bot_ids else None,
        lockdown_exclude_ids=lockdown_exclude_ids if lockdown_exclude_ids else None,
        link_allowed_user_ids=link_allowed_user_ids if link_allowed_user_ids else None,
        appeal_allowed_user_ids=appeal_allowed_user_ids if appeal_allowed_user_ids else None,
        modmail_forum_id=modmail_forum_id,
    )


# =============================================================================
# Global Config Instance
# =============================================================================

_config: Optional[Config] = None


def get_config() -> Config:
    """
    Get the global configuration instance, loading if needed.

    DESIGN:
        Singleton pattern ensures config is loaded once and reused.
        Thread-safe for Discord.py's async context since Python's
        GIL protects the assignment.

    Returns:
        The global Config instance.

    Raises:
        ConfigValidationError: On first call if config is invalid.
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


# =============================================================================
# Config Validation & Logging
# =============================================================================

def validate_and_log_config() -> None:
    """
    Validate configuration and log results at startup.

    Loads the config (triggering validation) and logs the configuration
    summary for debugging and verification.

    Raises:
        ConfigValidationError: If required configuration is missing.
    """
    from src.core.logger import logger

    # This will raise ConfigValidationError if config is invalid
    config = get_config()

    # Log optional features status
    optional_features = []
    if config.case_log_forum_id:
        optional_features.append("Case Logging")
    if config.mod_tracker_forum_id:
        optional_features.append("Mod Tracker")
    if config.server_logs_forum_id:
        optional_features.append("Server Logs")
    if config.alert_webhook_url:
        optional_features.append("Webhook Alerts")

    missing_optional = []
    if not config.case_log_forum_id:
        missing_optional.append("CASE_LOG_FORUM_ID")
    if not config.mod_tracker_forum_id:
        missing_optional.append("MOD_TRACKER_FORUM_ID")
    if not config.server_logs_forum_id:
        missing_optional.append("SERVER_LOGS_FORUM_ID")

    # Log missing optional (info level, not warning)
    for var in missing_optional:
        logger.info(f"Optional config not set: {var}")

    logger.tree("Configuration Validated", [
        ("Required", "✅ All required variables set"),
        ("Optional Features", ", ".join(optional_features) if optional_features else "None"),
        ("Prison Channels", str(len(config.prison_channel_ids))),
        ("AI Model", config.ai_model),
    ], emoji="⚙️")


# =============================================================================
# Permission Helpers
# =============================================================================

def is_developer(user_id: int) -> bool:
    """
    Check if user is the bot developer.

    Args:
        user_id: Discord user ID to check.

    Returns:
        True if user is the developer.
    """
    return user_id == get_config().developer_id


def is_moderator(user_id: int) -> bool:
    """
    Check if user is a moderator.

    Args:
        user_id: Discord user ID to check.

    Returns:
        True if user is in the moderator list.
    """
    config = get_config()
    if config.moderator_ids:
        return user_id in config.moderator_ids
    return False


def has_mod_role(member) -> bool:
    """
    Check if a member has the moderation role.

    Args:
        member: Discord member object to check.

    Returns:
        True if member has the moderation role or is developer/admin.
    """
    if member is None:
        return False

    # Developer always has access
    if is_developer(member.id):
        return True

    # Check moderator IDs list
    if is_moderator(member.id):
        return True

    # Check for administrator permission
    if member.guild_permissions.administrator:
        return True

    # Check for moderation role
    config = get_config()
    if config.moderation_role_id:
        for role in member.roles:
            if role.id == config.moderation_role_id:
                return True

    return False


async def check_mod_permission(interaction) -> bool:
    """
    Check mod permission and send error if not authorized.

    Args:
        interaction: Discord interaction to check.

    Returns:
        True if authorized, False if not (error already sent).
    """
    if not has_mod_role(interaction.user):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True
        )
        return False
    return True


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Core classes
    "Config",
    "ConfigValidationError",
    "EmbedColors",
    # Constants
    "NY_TZ",
    # Functions
    "get_config",
    "load_config",
    "validate_and_log_config",
    # Permission helpers
    "is_developer",
    "is_moderator",
    "has_mod_role",
    "check_mod_permission",
]
