# =============================================================================
# SaydnayaBot - Tree Style Logging Module (Based on QuranBot Architecture)
# =============================================================================
# Professional-grade logging system that creates beautiful, hierarchical logs
# with perfect tree structure, timestamps, and multi-destination output.
# Adapted from QuranBot's TreeLogger for SaydnayaBot architecture.
#
# Purpose:
# Professional-grade logging system that creates beautiful, hierarchical logs
# with perfect tree structure, timestamps, and multi-destination output.
#
# Key Features:
# - Beautiful tree-style log formatting
# - Multi-destination logging (console, files, JSON)
# - Perfect tree structure with proper indentation
# - Timezone-aware timestamps (EST/UTC)
# - Structured JSON log output
# - Emoji support for visual categorization
# - Run ID tracking for session management
#
# Technical Implementation:
# - Stack-based tree structure tracking
# - Atomic file writes for log persistence
# - Timezone handling with pytz
# - JSON serialization for structured logs
# - Unicode symbol management
#
# Log Structure:
# /logs/
#   YYYY-MM-DD/
#     logs.log      - All log messages
#     errors.log    - Only ERROR and CRITICAL level messages
#     logs.json     - Structured JSON log entries
#
# Required Dependencies:
# - pytz: Timezone handling
# =============================================================================

import json
import secrets
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pytz

# Global state tracking for tree structure
_is_first_section = True  # Controls top-level spacing
_tree_stack: List[bool] = []  # Tracks which levels have siblings
_current_depth = 0  # Current nesting level

# Unicode symbols for perfect tree structure
# Modify these to change the visual appearance of the tree
TREE_SYMBOLS = {
    "branch": "├─",  # Node with siblings below
    "last": "└─",  # Last node in current branch
    "pipe": "│ ",  # Vertical continuation line
    "space": "  ",  # Alignment spacing
    "nested_branch": "├─",  # Used in nested structures
    "nested_last": "└─",  # Last node in nested structure
}


class TreeLogger:
    """
    Professional-grade tree-style logging system for SaydnayaBot.

    Key Features:
    - Beautiful tree-style log formatting
    - Perfect hierarchical structure
    - Multi-destination output
    - Timezone-aware timestamps
    - Session tracking with run IDs
    - Structured JSON logging
    - Unicode symbol support

    Log Categories:
    1. General Logs:
       - Application events
       - State changes
       - User interactions

    2. Error Logs:
       - Exceptions with tracebacks
       - Warning messages
       - Critical errors

    3. Activity Logs:
       - User actions
       - System events
       - Performance metrics

    Usage Example:
    ```python
    # Log a simple message
    log_status("Bot started", status="INFO", emoji="🚀")

    # Log a tree structure
    log_perfect_tree_section(
        "Initialization",
        [
            ("status", "Starting up"),
            ("version", "1.0.0"),
            ("mode", "production")
        ],
        emoji="🎯"
    )
    ```
    """

    def __init__(self, cleanup_on_start=True):
        """Initialize the TreeLogger instance.

        Args:
            cleanup_on_start: If True, deletes ALL existing logs on startup for fresh start
        """
        # Clean up existing logs BEFORE setting up new directories
        if cleanup_on_start:
            self._cleanup_existing_logs()

        self.log_dir = self._setup_log_directories()
        self.run_id = self._generate_run_id()
        self.current_datetime_iso = self._get_current_datetime_iso()
        self.tree_level = 0
        self.tree_sections = []
        self.current_date = None
        self.mock_date = None  # For testing

    def _cleanup_existing_logs(self):
        """
        Clean up ALL existing logs on startup for completely fresh logging.

        This ensures fresh logs every time the bot starts, deleting ALL
        previous log files and folders to start with a completely clean slate.
        Same implementation as QuranBot for consistency.
        """
        try:
            project_root = Path(__file__).parent.parent.parent
            main_log_dir = project_root / "logs"

            print(f"🧹 Starting log cleanup in: {main_log_dir}")

            if not main_log_dir.exists():
                print("📁 Log folder doesn't exist, nothing to clean")
                return

            # Track cleanup statistics
            deleted_folders = 0
            deleted_files = 0

            # Delete ALL log folders for completely fresh start
            for item in main_log_dir.iterdir():
                if not item.is_dir():
                    # Skip non-directory items (like .DS_Store)
                    continue

                # Check if this is a date folder (YYYY-MM-DD format)
                if not self._is_date_folder(item.name):
                    continue

                print(f"🗑️  Deleting log folder: {item.name}")

                try:
                    # Count files before deleting
                    file_count = sum(1 for _ in item.rglob("*") if _.is_file())

                    # Delete the entire date folder
                    import shutil

                    shutil.rmtree(item)

                    deleted_folders += 1
                    deleted_files += file_count

                    print(f"✅ Deleted folder: {item.name} ({file_count} files)")

                except Exception as e:
                    print(f"⚠️  Error deleting {item.name}: {e}")

            if deleted_folders > 0:
                print(
                    f"🎯 Cleanup complete: Removed {deleted_folders} folders, {deleted_files} files"
                )
                print("📝 Starting fresh logging session...")
                print()
            else:
                print("✨ No old logs to clean up")
                print()

        except Exception as e:
            print(f"⚠️  Error during log cleanup: {e}")
            print("📝 Continuing with normal logging...")
            print()

    def _is_date_folder(self, name: str) -> bool:
        """Check if a folder name matches the date format YYYY-MM-DD."""
        try:
            from datetime import datetime

            datetime.strptime(name, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def _setup_log_directories(self):
        """Create log directory structure with date-based subdirectories and 3 log files."""
        try:
            # Create main logs directory (always relative to project root)
            project_root = Path(__file__).parent.parent.parent
            main_log_dir = project_root / "logs"
            main_log_dir.mkdir(parents=True, exist_ok=True)

            # Create today's date subdirectory
            date_str = self._get_log_date()
            date_log_dir = main_log_dir / date_str
            date_log_dir.mkdir(parents=True, exist_ok=True)

            return date_log_dir
        except Exception as e:
            print(f"Warning: Could not create log directory: {e}")
            return None

    def _generate_run_id(self):
        """Generate a unique run ID for each bot instance."""
        return secrets.token_hex(4).upper()

    def _get_log_date(self) -> str:
        """Get current date for log file naming (YYYY-MM-DD format)."""
        if hasattr(self, "mock_date") and self.mock_date:
            now = self.mock_date
            return now.strftime("%Y-%m-%d")
        else:
            try:
                est = pytz.timezone("US/Eastern")
                now_est = datetime.now(est)
                return now_est.strftime("%Y-%m-%d")
            except Exception:
                return datetime.now().strftime("%Y-%m-%d")

    def _get_current_datetime_iso(self):
        """Get current datetime in ISO format for JSON logs."""
        try:
            est = pytz.timezone("US/Eastern")
            now_est = datetime.now(est)
            return now_est.isoformat()
        except Exception:
            return datetime.now().isoformat()

    def _get_timestamp(self) -> str:
        """Get current timestamp in EST timezone with custom format."""
        if hasattr(self, "mock_date") and self.mock_date:
            now = self.mock_date
            formatted_time = now.strftime("%m/%d %I:%M %p EST")
            return f"[{formatted_time}]"
        else:
            try:
                # Create EST timezone
                est = pytz.timezone("US/Eastern")
                # Get current time in EST
                now_est = datetime.now(est)
                # Format as MM/DD HH:MM AM/PM EST
                formatted_time = now_est.strftime("%m/%d %I:%M %p EST")
                return f"[{formatted_time}]"
            except ImportError:
                # Fallback if pytz is not available
                now = datetime.now()
                formatted_time = now.strftime("%m/%d %I:%M %p")
                return f"[{formatted_time}]"
            except Exception:
                # Fallback if timezone handling fails
                now = datetime.now()
                formatted_time = now.strftime("%m/%d %I:%M %p")
                return f"[{formatted_time}]"

    def reset_tree_structure(self):
        """Reset the tree structure tracking."""
        global _tree_stack, _current_depth
        _tree_stack = []
        _current_depth = 0

    def get_tree_prefix(self, is_last_item=False, depth_override=None):
        """Generate the proper tree prefix based on current depth and structure."""
        # These are read-only access to globals
        depth = depth_override if depth_override is not None else _current_depth

        if depth == 0:
            return TREE_SYMBOLS["branch"] if not is_last_item else TREE_SYMBOLS["last"]

        prefix = ""
        for i in range(depth):
            if i < len(_tree_stack):
                if _tree_stack[i]:  # This level has more siblings
                    prefix += TREE_SYMBOLS["pipe"]
                else:  # This level is the last item
                    prefix += TREE_SYMBOLS["space"]
            else:
                prefix += TREE_SYMBOLS["space"]

        # Add the current level symbol
        prefix += TREE_SYMBOLS["branch"] if not is_last_item else TREE_SYMBOLS["last"]

        return prefix

    def log_perfect_tree_section(
        self,
        title: str,
        items: List[tuple],
        emoji: str = "🎯",
        nested_groups: Optional[Dict[str, List[tuple]]] = None,
    ):
        """
        Create a perfect tree structure with proper nesting and visual hierarchy.
        Automatically adds spacing before each section for better readability.

        Args:
            title: Section title
            items: List of (key, value) tuples for main items
            emoji: Emoji for the section header
            nested_groups: Dict of nested groups {group_name: [(key, value), ...]}
        """
        global _is_first_section

        timestamp = self._get_timestamp()

        # Add spacing before section (except for the very first section)
        if not _is_first_section:
            print("")
            self._write_to_log_files("", "INFO", "section_spacing")
        else:
            _is_first_section = False

        # Reset tree structure for this section
        self.reset_tree_structure()

        # Log section header
        section_header = f"{emoji} {title}"
        print(f"{timestamp} {section_header}")
        self._write_to_log_files(section_header, "INFO", "perfect_tree_section")

        # Calculate total items to determine which is last
        total_main_items = len(items) if items else 0
        total_nested_groups = len(nested_groups) if nested_groups else 0
        has_nested = total_nested_groups > 0

        # Log main items
        if items:
            for i, (key, value) in enumerate(items):
                is_last_main = (i == total_main_items - 1) and not has_nested
                prefix = self.get_tree_prefix(is_last_main, depth_override=0)
                message = f"{prefix} {key}: {value}"
                print(f"{timestamp} {message}")
                self._write_to_log_files(message, "INFO", "tree_item")

        # Log nested groups
        if nested_groups:
            nested_group_keys = list(nested_groups.keys())
            for i, (group_name, group_items) in enumerate(nested_groups.items()):
                is_last_group = i == len(nested_group_keys) - 1

                # Log group header
                group_prefix = self.get_tree_prefix(is_last_group, depth_override=0)
                group_header = f"{group_prefix} 📁 {group_name}"
                print(f"{timestamp} {group_header}")
                self._write_to_log_files(
                    group_header, "INFO", "perfect_tree_nested_group"
                )

                # Log group items with proper nesting
                if group_items:
                    for j, (key, value) in enumerate(group_items):
                        is_last_item = j == len(group_items) - 1

                        # Create nested prefix
                        nested_prefix = ""
                        if not is_last_group:
                            nested_prefix += TREE_SYMBOLS["pipe"]
                        else:
                            nested_prefix += TREE_SYMBOLS["space"]

                        nested_prefix += (
                            TREE_SYMBOLS["last"]
                            if is_last_item
                            else TREE_SYMBOLS["branch"]
                        )

                        nested_message = f"{nested_prefix} {key}: {value}"
                        print(f"{timestamp} {nested_message}")
                        self._write_to_log_files(
                            nested_message, "INFO", "perfect_tree_nested_item"
                        )

    def log_status(self, message: str, status: str = "INFO", emoji: str = "📍"):
        """Log status with emoji and message."""
        if status != "INFO":
            self.log_perfect_tree_section(
                "Status Update", [("message", message), ("level", status)], emoji
            )
        else:
            timestamp = self._get_timestamp()
            formatted_message = f"{emoji} {message}"
            print(f"{timestamp} {formatted_message}")
            self._write_to_log_files(formatted_message, status, "status")

    def log_error_with_traceback(
        self, message: str, exception: Optional[Exception] = None, level: str = "ERROR"
    ):
        """Enhanced error logging with full traceback support."""
        timestamp = self._get_timestamp()

        if exception:
            # Get the full traceback
            tb_lines = traceback.format_exception(
                type(exception), exception, exception.__traceback__
            )
            tb_string = "".join(tb_lines)

            # Log the main error message
            formatted_message = f"├─ {level}: {message}"
            print(f"{timestamp} {formatted_message}")
            self._write_to_log_files(formatted_message, level, "error")

            # Log exception details
            exception_details = f"├─ exception_type: {type(exception).__name__}"
            print(f"{timestamp} {exception_details}")
            self._write_to_log_files(exception_details, level, "error")

            exception_message = f"├─ exception_message: {str(exception)}"
            print(f"{timestamp} {exception_message}")
            self._write_to_log_files(exception_message, level, "error")

            # Log full traceback with tree formatting
            traceback_header = "└─ full_traceback:"
            print(f"{timestamp} {traceback_header}")
            self._write_to_log_files(traceback_header, level, "error")

            # Format traceback lines with proper indentation
            for line in tb_string.strip().split("\n"):
                if line.strip():
                    formatted_tb_line = f"   {line}"
                    print(f"{timestamp} {formatted_tb_line}")
                    self._write_to_log_files(formatted_tb_line, level, "error")
        else:
            # Simple error without exception
            formatted_message = f"├─ {level}: {message}"
            print(f"{timestamp} {formatted_message}")
            self._write_to_log_files(formatted_message, level, "error")

    def log_critical_error(self, message: str, exception: Optional[Exception] = None):
        """Log critical errors that might crash the application."""
        self.log_error_with_traceback(f"CRITICAL: {message}", exception, "CRITICAL")

    def log_spacing(self):
        """Add a blank line for visual separation."""
        print()
        self._write_to_log_files("", "INFO", "spacing")

    def log_run_separator(self):
        """Create a visual separator for new runs."""
        # Reset section tracking for new run
        self.reset_section_tracking()

        separator_line = "=" * 80
        timestamp = self._get_timestamp()

        # Print separator to console
        print(f"\n{separator_line}")
        print(f"{timestamp} 🚀 NEW BOT RUN STARTED")
        print(f"{separator_line}")

        # Write separator to log files
        self._write_to_log_files("", "INFO", "run_separator")
        self._write_to_log_files(separator_line, "INFO", "run_separator")
        self._write_to_log_files("🚀 NEW BOT RUN STARTED", "INFO", "run_separator")
        self._write_to_log_files(separator_line, "INFO", "run_separator")

    def log_run_header(self, bot_name: str, version: str, run_id: Optional[str] = None):
        """Log run header with bot info and unique run ID."""
        if run_id is None:
            run_id = self.run_id

        timestamp = self._get_timestamp()

        # Create run header
        header_info = [
            f"🎯 {bot_name} v{version} - Run ID: {run_id}",
            f"├─ started_at: {timestamp}",
            f"├─ version: {version}",
            f"├─ run_id: {run_id}",
            f"└─ log_session: {self._get_log_date()}",
        ]

        # Print to console
        for line in header_info:
            print(f"{timestamp} {line}")

        # Write to log files
        for line in header_info:
            self._write_to_log_files(line, "INFO", "run_header")

        return run_id

    def log_run_end(self, run_id: str, reason: str = "Normal shutdown"):
        """Log run end with run ID and reason."""
        timestamp = self._get_timestamp()

        end_info = [
            f"🏁 Bot Run Ended - Run ID: {run_id}",
            f"├─ ended_at: {timestamp}",
            f"├─ run_id: {run_id}",
            f"└─ reason: {reason}",
        ]

        # Print to console
        for line in end_info:
            print(f"{timestamp} {line}")

        # Write to log files
        for line in end_info:
            self._write_to_log_files(line, "INFO", "run_end")

        # Add spacing after run end
        self.log_spacing()

    def reset_section_tracking(self):
        """Reset the section tracking for a new run or major section group."""
        global _is_first_section
        _is_first_section = True

    def _write_to_log_files(
        self,
        message: str,
        level: str = "INFO",
        log_type: str = "general",
    ) -> None:
        """
        Write log message to 3 separate log files in date-based subdirectory.

        Creates logs/YYYY-MM-DD/ directory with:
        - logs.log: All log messages
        - errors.log: Only ERROR and CRITICAL level messages
        - logs.json: Structured JSON log entries

        Args:
            message: The log message to write
            level: Log level (INFO, ERROR, WARNING, etc.)
            log_type: Category of the log (for context)
        """
        try:
            # Check if the date has changed and update log directory if needed
            current_date = self._get_log_date()
            if not self.log_dir or self.log_dir.name != current_date:
                # Date has changed, create new log directory
                project_root = Path(__file__).parent.parent.parent
                main_log_dir = project_root / "logs"
                main_log_dir.mkdir(parents=True, exist_ok=True)

                new_date_log_dir = main_log_dir / current_date
                new_date_log_dir.mkdir(parents=True, exist_ok=True)

                # Update the log directory
                old_date = self.log_dir.name if self.log_dir else "None"
                self.log_dir = new_date_log_dir

                # Log the date change (but avoid infinite recursion)
                if old_date != "None" and old_date != current_date:
                    timestamp = self._get_timestamp()
                    print(
                        f"{timestamp} [INFO] 📅 Log date changed: {old_date} → {current_date}"
                    )

            if not self.log_dir:
                return

            # Create timestamp for the log entry
            timestamp = self._get_timestamp()

            # Format the log entry with level and category for context
            if message.strip():  # Only add level/category info for non-empty messages
                log_entry = f"{timestamp} [{level}] {message}\n"
            else:
                log_entry = "\n"  # Just a blank line for spacing

            # 1. Write to main logs.log file (all messages)
            main_log_file = self.log_dir / "logs.log"
            with open(main_log_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
                f.flush()

            # 2. Write to errors.log file (only ERROR and CRITICAL levels)
            if level in ["ERROR", "CRITICAL", "WARNING"]:
                error_log_file = self.log_dir / "errors.log"
                with open(error_log_file, "a", encoding="utf-8") as f:
                    f.write(log_entry)
                    f.flush()

            # 3. Write to logs.json file (structured JSON format)
            if message.strip():  # Only write non-empty messages to JSON
                json_log_file = self.log_dir / "logs.json"
                json_entry = {
                    "timestamp": timestamp,
                    "level": level,
                    "category": log_type,
                    "message": message.strip(),
                    "run_id": self.run_id,
                    "iso_datetime": self.current_datetime_iso,
                }

                # Append JSON entry as a single line
                with open(json_log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(json_entry) + "\n")
                    f.flush()

        except Exception as e:
            # Fallback to console if file writing fails
            print(f"LOG_ERROR: Failed to write to log file: {e}")

    def set_mock_date(self, mock_date: datetime) -> None:
        """Set mock date for testing."""
        self.mock_date = mock_date


# =============================================================================
# Global Logger Instance and Standalone Functions
# =============================================================================

# Global logger instance with cleanup on startup
_global_logger = TreeLogger(cleanup_on_start=True)


# Standalone functions for convenience
def log_perfect_tree_section(
    title: str,
    items: List[tuple],
    emoji: str = "🎯",
    nested_groups: Optional[Dict[str, List[tuple]]] = None,
):
    """Log a perfect tree section."""
    return _global_logger.log_perfect_tree_section(title, items, emoji, nested_groups)


def log_error_with_traceback(
    message: str, exception: Optional[Exception] = None, level: str = "ERROR"
):
    """Log an error with traceback."""
    return _global_logger.log_error_with_traceback(message, exception, level)


def log_critical_error(message: str, exception: Optional[Exception] = None):
    """Log a critical error."""
    return _global_logger.log_critical_error(message, exception)


def log_spacing():
    """Add spacing in logs."""
    return _global_logger.log_spacing()


def log_status(message: str, status: str = "INFO", emoji: str = "📍"):
    """Log a status message."""
    return _global_logger.log_status(message, status, emoji)


def log_run_separator():
    """Log a run separator."""
    return _global_logger.log_run_separator()


def log_run_header(bot_name: str, version: str, run_id: Optional[str] = None):
    """Log a run header."""
    return _global_logger.log_run_header(bot_name, version, run_id)


def log_run_end(run_id: str, reason: str = "Normal shutdown"):
    """Log a run end."""
    return _global_logger.log_run_end(run_id, reason)


def get_timestamp():
    """Get current timestamp."""
    return _global_logger._get_timestamp()
