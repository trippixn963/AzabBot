"""
Azab Discord Bot - Logger Module
===============================

Custom logging system with EST timezone support and tree-style formatting.
Provides structured logging for Discord bot events with visual formatting
and file output for debugging and monitoring.

Features:
- Unique run ID generation for tracking bot sessions
- EST timezone timestamp formatting
- Tree-style log formatting for structured data
- Console and file output simultaneously
- Emoji-enhanced log levels for visual clarity

Author: حَـــــنَّـــــا
Server: discord.gg/syria
Version: Modular
"""

import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path


class MiniTreeLogger:
    """
    Custom logger with tree-style formatting and EST timezone support.
    
    Provides structured logging capabilities for the Azab Discord bot:
    - Unique run ID for each bot session
    - EST timezone timestamps (UTC-5)
    - Tree-style formatting for hierarchical data
    - Simultaneous console and file output
    - Emoji-enhanced log levels for visual clarity
    
    Log files are stored in logs/ directory with daily rotation.
    """
    
    def __init__(self):
        """
        Initialize the logger with unique run ID and daily log file rotation.
        
        Creates logs directory if it doesn't exist and generates a unique
        run ID for tracking this bot session.
        """
        self.run_id = str(uuid.uuid4())[:8]  # Short unique ID for this run
        self.log_file = Path('logs') / f'azab_{datetime.now().strftime("%Y-%m-%d")}.log'
        self.log_file.parent.mkdir(exist_ok=True)
        
        # Write session start header with run ID
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"NEW SESSION STARTED - RUN ID: {self.run_id}\n")
            f.write(f"{self._get_timestamp()}\n")
            f.write(f"{'='*60}\n\n")
    
    def _get_timestamp(self) -> str:
        """
        Get current timestamp in EST timezone.
        
        Returns:
            str: Formatted timestamp string in EST (UTC-5)
        """
        est = timezone(timedelta(hours=-5))  # EST is UTC-5
        return datetime.now(est).strftime('[%I:%M:%S %p EST]')
    
    def _write(self, message: str, emoji: str = "", include_timestamp: bool = True):
        """
        Write log message to both console and file.
        
        Args:
            message (str): The log message to write
            emoji (str): Optional emoji to prefix the message
            include_timestamp (bool): Whether to include timestamp
        """
        if include_timestamp:
            timestamp = self._get_timestamp()
            full_message = f"{timestamp} {emoji} {message}" if emoji else f"{timestamp} {message}"
        else:
            full_message = f"{emoji} {message}" if emoji else message
        
        # Output to console
        print(full_message)
        
        # Write to log file (without RUN ID on every line)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"{full_message}\n")
    
    def tree(self, title: str, items: list, emoji: str = "📦"):
        """
        Log structured data in tree format.
        
        Creates a hierarchical tree structure for logging structured data
        like bot status, command execution details, etc.
        
        Args:
            title (str): Main title for the tree
            items (list): List of (key, value) tuples to display
            emoji (str): Emoji to prefix the title
        """
        # Add line break before tree for better readability
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write("\n")
        
        self._write(f"{title}", emoji=emoji)
        for i, (key, value) in enumerate(items):
            prefix = "└─" if i == len(items) - 1 else "├─"
            self._write(f"  {prefix} {key}: {value}", include_timestamp=False)
        
        # Add line break after tree
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write("\n")
    
    def info(self, msg: str):
        """Log an informational message."""
        self._write(msg, "ℹ️")
    
    def success(self, msg: str):
        """Log a success message."""
        self._write(msg, "✅")
    
    def error(self, msg: str):
        """Log an error message."""
        self._write(msg, "❌")
    
    def warning(self, msg: str):
        """Log a warning message."""
        self._write(msg, "⚠️")


# Global logger instance for use throughout the bot
logger = MiniTreeLogger()