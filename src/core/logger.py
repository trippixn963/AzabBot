"""
AzabBot - Core Logger Module
================================

This module provides a comprehensive logging system that integrates TreeLogger
with standard Python logging for complete application logging coverage.

The logging system combines beautiful tree-style structured logging with traditional
Python logging capabilities, providing both visual appeal and comprehensive
logging functionality. It serves as the central logging interface for the entire
application.

Key Features:
- Tree-style structured logging for complex operations and initialization
- Traditional Python logging for simple messages and integration
- Automatic error context extraction and formatting
- Run ID tracking for session management and correlation
- Multiple output destinations (console, files, JSON)
- Proper log level management and filtering
- Exception handling integration with detailed context
- Performance metrics logging
- User interaction tracking
- System event logging

The logger provides specialized methods for different types of logging needs
including startup/shutdown, initialization steps, user interactions, AI operations,
and error handling.
"""

import logging
import sys
from enum import Enum
from typing import Any, Dict, Optional, Union

from src.core.exceptions import AzabBotException
from src.utils.tree_log import (
    TreeLogger,
    log_error_with_traceback,
    log_perfect_tree_section,
    log_status,
)


class LogLevel(Enum):
    """
    Log level enumeration for consistent logging level management.
    
    Provides standardized log levels that can be used throughout the application
    for consistent logging behavior and filtering.
    """

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class BotLogger:
    """
    Comprehensive logging system for AzabBot.
    
    This class combines TreeLogger's beautiful tree-style output with traditional
    Python logging to provide complete logging coverage for the application.
    It offers structured logging for complex operations while maintaining
    compatibility with standard logging practices.
    
    The logger provides specialized methods for different types of logging needs:
    - Initialization and startup logging
    - User interaction tracking
    - AI operation logging
    - Error handling with context
    - Performance metrics
    - System events
    
    Features:
    - Tree-style structured logging for complex operations
    - Traditional logging for simple messages and integration
    - Automatic error context extraction and formatting
    - Run ID tracking for session management
    - Multiple output destinations (console, files, JSON)
    - Proper log level management and filtering
    - Exception handling integration with detailed context
    """

    def __init__(self, name: str = "AzabBot", cleanup_on_start: bool = True):
        """
        Initialize the bot logger with configuration.
        
        Sets up both the tree logger and traditional Python logger,
        establishing the foundation for comprehensive logging throughout
        the application.
        
        Args:
            name: Logger name for identification and filtering
            cleanup_on_start: If True, deletes ALL existing logs on startup
        """
        self.name = name
        self.tree_log = TreeLogger(cleanup_on_start=cleanup_on_start)
        self.python_logger = self._setup_python_logger()
        self.run_id = self.tree_log.run_id
        self.log_level = LogLevel.INFO

    def _setup_python_logger(self) -> logging.Logger:
        """
        Set up traditional Python logger for integration and compatibility.
        
        Creates a standard Python logger with console output and proper
        formatting that works well alongside the tree logger.
        
        Returns:
            Configured Python logger instance
        """
        logger = logging.getLogger(self.name)
        logger.setLevel(logging.DEBUG)

        # Clear any existing handlers to avoid duplication
        logger.handlers.clear()

        # Console handler for immediate feedback (INFO and above only)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        
        # Filter out DEBUG messages from console
        class NoDebugFilter(logging.Filter):
            def filter(self, record):
                # Skip messages containing "DEBUG:"
                return "DEBUG:" not in record.getMessage()
        
        console_handler.addFilter(NoDebugFilter())

        # Formatter that works well with tree logger output
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%m/%d %I:%M %p EST",
        )
        console_handler.setFormatter(formatter)

        logger.addHandler(console_handler)

        return logger

    def log_startup(
        self, version: str, config_summary: Optional[Dict[str, Any]] = None
    ):
        """
        Log application startup with comprehensive information.
        
        Creates a detailed startup log entry including version information,
        configuration summary, and system status. This is typically called
        once at the beginning of the application lifecycle.
        
        Args:
            version: Application version string
            config_summary: Optional configuration summary to log (sensitive data will be filtered)
        """
        # Log run separator and header
        self.tree_log.log_run_separator()
        self.run_id = self.tree_log.log_run_header(self.name, version)

        # Log startup information
        startup_items = [
            ("status", "Initializing"),
            ("version", version),
            ("run_id", self.run_id),
            ("log_session", self.tree_log._get_log_date()),
        ]

        nested_groups = {}

        if config_summary:
            config_items = list(config_summary.items())
            nested_groups["Configuration"] = config_items

        log_perfect_tree_section(
            "Bot Startup", startup_items, emoji="🚀", nested_groups=nested_groups
        )

    def log_initialization_step(
        self, component: str, status: str, details: str, emoji: str = "🔧"
    ):
        """
        Log individual initialization steps.

        Args:
            component: Component being initialized
            status: Status of initialization (success, error, in_progress)
            details: Additional details about the step
            emoji: Emoji for visual categorization
        """
        status_emojis = {
            "success": "✅",
            "error": "❌",
            "in_progress": "🔄",
            "warning": "⚠️",
        }

        status_emoji = status_emojis.get(status.lower(), "🔧")
        message = f"{component}: {status_emoji} {details}"

        log_status(message, status.upper(), emoji)

        # Also log to Python logger for integration
        if status.lower() == "error":
            self.python_logger.error(f"{component} initialization failed: {details}")
        elif status.lower() == "warning":
            self.python_logger.warning(f"{component} initialization warning: {details}")
        else:
            self.python_logger.info(f"{component} initialized: {details}")

    def log_service_status(
        self, service_name: str, status: str, details: Optional[Dict[str, Any]] = None
    ):
        """
        Log service status with detailed information.

        Args:
            service_name: Name of the service
            status: Service status
            details: Additional service details
        """
        items = [("service", service_name), ("status", status)]

        if details:
            for key, value in details.items():
                items.append((key, value))

        log_perfect_tree_section(f"Service Status: {service_name}", items, emoji="🔧")

    def log_user_interaction(
        self,
        interaction_type: str,
        user_name: str,
        user_id: int,
        action: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        Log user interactions with structured format.

        Args:
            interaction_type: Type of interaction
            user_name: User display name
            user_id: User ID
            action: Action performed
            details: Additional interaction details
        """
        items = [
            ("user", f"{user_name} ({user_id})"),
            ("interaction_type", interaction_type),
            ("action", action),
        ]

        nested_groups = {}

        if details:
            detail_items = list(details.items())
            nested_groups["Details"] = detail_items

        log_perfect_tree_section(
            "User Interaction", items, emoji="👤", nested_groups=nested_groups
        )

        # Also log to Python logger
        self.python_logger.info(
            f"User interaction: {user_name}({user_id}) - {interaction_type} - {action}"
        )

    def log_ai_operation(
        self,
        operation: str,
        user_input: Optional[str] = None,
        result: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """
        Log AI service operations.

        Args:
            operation: AI operation performed
            user_input: User input (truncated for privacy)
            result: AI result (truncated)
            context: Additional context information
        """
        items = [("operation", operation)]

        if user_input:
            truncated_input = (
                user_input[:100] + "..." if len(user_input) > 100 else user_input
            )
            items.append(("input", truncated_input))

        if result:
            truncated_result = result[:100] + "..." if len(result) > 100 else result
            items.append(("result", truncated_result))

        nested_groups = {}

        if context:
            context_items = list(context.items())
            nested_groups["Context"] = context_items

        log_perfect_tree_section(
            "AI Operation", items, emoji="🤖", nested_groups=nested_groups
        )

    def log_error(
        self,
        message: str,
        exception: Optional[Exception] = None,
        context: Optional[Dict[str, Any]] = None,
        level: str = "ERROR",
    ):
        """
        Log errors with comprehensive information.

        Args:
            message: Error message
            exception: Exception object if available
            context: Additional error context
            level: Error level (ERROR, WARNING, CRITICAL)
        """
        # Extract context from AzabBot exceptions
        error_context = {}
        if isinstance(exception, AzabBotException):
            error_context.update(exception.context)
            if exception.error_code:
                error_context["error_code"] = exception.error_code

        if context:
            error_context.update(context)

        # Use tree logger for structured error logging
        log_error_with_traceback(message, exception, level)

        # Log context if available
        if error_context:
            context_items = list(error_context.items())
            log_perfect_tree_section("Error Context", context_items, emoji="🔍")

        # Also log to Python logger
        if exception:
            self.python_logger.error(f"{message}: {str(exception)}", exc_info=True)
        else:
            self.python_logger.error(message)

    def log_warning(self, message: str, context: Optional[Dict[str, Any]] = None):
        """
        Log warning messages.

        Args:
            message: Warning message
            context: Additional context
        """
        if context:
            context_items = list(context.items())
            log_perfect_tree_section(
                "Warning",
                [("message", message)],
                emoji="⚠️",
                nested_groups={"Context": context_items},
            )
        else:
            log_status(message, "WARNING", "⚠️")

        self.python_logger.warning(message)

    
    def log_info(self, message: str, emoji: str = "ℹ️"):
        """
        Log informational messages.

        Args:
            message: Information message
            emoji: Emoji for visual categorization
        """
        log_status(message, "INFO", emoji)
        self.python_logger.info(message)

    def log_debug(self, message: str, context: Optional[Dict[str, Any]] = None):
        """
        Log debug messages to debug.log file only (not to console) with tree format.

        Args:
            message: Debug message
            context: Additional debug context
        """
        # Write to debug.log file directly with tree format
        from pathlib import Path
        from datetime import datetime
        import pytz
        
        try:
            est = pytz.timezone("US/Eastern")
            current_date = datetime.now(est).strftime("%Y-%m-%d")
            timestamp = datetime.now(est).strftime("[%m/%d %I:%M %p EST]")
            # Get hour for hourly folder structure
            hour_str = datetime.now(est).strftime("%I-%p")
            if hour_str.startswith('0'):
                hour_str = hour_str[1:]
        except:
            current_date = datetime.now().strftime("%Y-%m-%d")
            timestamp = datetime.now().strftime("[%m/%d %I:%M %p]")
            hour_str = datetime.now().strftime("%I-%p")
            if hour_str.startswith('0'):
                hour_str = hour_str[1:]
        
        # Create debug.log path in hourly folder
        project_root = Path(__file__).parent.parent.parent
        debug_log_path = project_root / "logs" / current_date / hour_str / "debug.log"
        debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Format the debug message with tree structure
        if context:
            # Create tree structure for context
            formatted_lines = []
            formatted_lines.append(f"{timestamp} [DEBUG] 🔍 {message}")
            formatted_lines.append(f"{timestamp} [DEBUG] └─ 📁 Context")
            
            context_items = list(context.items())
            for i, (key, value) in enumerate(context_items):
                is_last = i == len(context_items) - 1
                prefix = "  └─" if is_last else "  ├─"
                formatted_lines.append(f"{timestamp} [DEBUG] {prefix} {key}: {value}")
            
            debug_output = "\n".join(formatted_lines) + "\n"
        else:
            # Simple debug message
            debug_output = f"{timestamp} [DEBUG] 🔍 {message}\n"
        
        # Write to debug.log
        try:
            with open(debug_log_path, "a", encoding="utf-8") as f:
                f.write(debug_output)
                f.flush()
        except Exception as e:
            # Fallback to Python logger if direct write fails
            if self.python_logger:
                self.python_logger.debug(f"🔍 DEBUG: {message}")

    def log_system_event(
        self,
        event_type: str,
        description: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        Log system events with structured format.

        Args:
            event_type: Type of system event
            description: Event description
            details: Additional event details
        """
        items = [("event_type", event_type), ("description", description)]

        nested_groups = {}

        if details:
            detail_items = list(details.items())
            nested_groups["Details"] = detail_items

        log_perfect_tree_section(
            "System Event", items, emoji="⚡", nested_groups=nested_groups
        )

        self.python_logger.info(f"System event: {event_type} - {description}")

    def log_performance_metric(
        self,
        metric_name: str,
        value: Union[int, float],
        unit: str = "",
        context: Optional[Dict[str, Any]] = None,
    ):
        """
        Log performance metrics.

        Args:
            metric_name: Name of the metric
            value: Metric value
            unit: Unit of measurement
            context: Additional metric context
        """
        items = [("metric", metric_name), ("value", f"{value} {unit}".strip())]

        nested_groups = {}

        if context:
            context_items = list(context.items())
            nested_groups["Context"] = context_items

        log_perfect_tree_section(
            "Performance Metric", items, emoji="📊", nested_groups=nested_groups
        )

    def log_shutdown(self, reason: str = "Normal shutdown"):
        """
        Log application shutdown.

        Args:
            reason: Reason for shutdown
        """
        self.tree_log.log_run_end(self.run_id, reason)
        self.python_logger.info(f"Bot shutdown: {reason}")

    def get_run_id(self) -> str:
        """Get the current run ID."""
        return self.run_id

    def set_log_level(self, level: Union[str, LogLevel]):
        """
        Set the log level for Python logger.

        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        if isinstance(level, LogLevel):
            self.log_level = level
            level_str = level.value
        else:
            level_str = level.upper()
            self.log_level = LogLevel(level_str)

        numeric_level = getattr(logging, level_str, logging.INFO)
        self.python_logger.setLevel(numeric_level)


# =============================================================================
# Global Logger Instance
# =============================================================================

# Create a global logger instance for use throughout the application
_global_bot_logger = BotLogger()


# Convenience functions for global access
def get_logger() -> BotLogger:
    """Get the global bot logger instance."""
    return _global_bot_logger


def log_startup(version: str, config_summary: Optional[Dict[str, Any]] = None):
    """Log application startup."""
    return _global_bot_logger.log_startup(version, config_summary)


def log_initialization_step(
    component: str, status: str, details: str, emoji: str = "🔧"
):
    """Log initialization step."""
    return _global_bot_logger.log_initialization_step(component, status, details, emoji)


def log_error(
    message: str,
    exception: Optional[Exception] = None,
    context: Optional[Dict[str, Any]] = None,
):
    """Log error with context."""
    return _global_bot_logger.log_error(message, exception, context)


def log_warning(message: str, context: Optional[Dict[str, Any]] = None):
    """Log warning message."""
    return _global_bot_logger.log_warning(message, context)


def log_info(message: str, emoji: str = "ℹ️"):
    """Log informational message."""
    return _global_bot_logger.log_info(message, emoji)


def log_user_interaction(
    interaction_type: str,
    user_name: str,
    user_id: int,
    action: str,
    details: Optional[Dict[str, Any]] = None,
):
    """Log user interaction."""
    return _global_bot_logger.log_user_interaction(
        interaction_type, user_name, user_id, action, details
    )


def log_system_event(
    event_type: str, description: str, details: Optional[Dict[str, Any]] = None
):
    """Log system event."""
    return _global_bot_logger.log_system_event(event_type, description, details)
