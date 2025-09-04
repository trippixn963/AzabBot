"""
Azab Discord Bot - Advanced Logger Module
========================================

Structured logging system with tree formatting for all events.
Every log entry is part of a hierarchical tree structure.

Features:
- All logs in tree format
- Clean date-only log files (YYYY-MM-DD.log)
- Automatic log rotation and cleanup
- Size-limited log files
- Old log compression
- EST timezone with clean timestamps
- No message content logging

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import gzip
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Tuple, Optional


class TreeLogger:
    """
    Advanced tree-structured logger for Discord bot events.
    
    Every single log entry is part of a tree structure for maximum clarity.
    Includes automatic log management for 24/7 VPS deployment.
    """
    
    # Log management settings
    MAX_LOG_SIZE_MB = 10  # Maximum size per log file in MB
    MAX_LOG_DAYS = 7      # Keep logs for 7 days
    COMPRESS_AFTER_DAYS = 1  # Compress logs older than 1 day
    
    def __init__(self):
        """Initialize the logger with clean daily log files and rotation."""
        # Create logs directory
        self.log_dir = Path('logs')
        self.log_dir.mkdir(exist_ok=True)
        
        # Simple date-based log file (YYYY-MM-DD.log)
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        self.log_file = self.log_dir / f'{self.current_date}.log'
        
        # Session tracking
        self.session_start = datetime.now()
        self.entries_count = 0
        
        # Perform cleanup on startup
        self._cleanup_old_logs()
        
        # Write session header
        self._write_session_header()
    
    def _cleanup_old_logs(self):
        """Clean up old logs and compress recent ones."""
        now = datetime.now()
        
        for log_path in self.log_dir.glob("*.log*"):
            # Skip today's log
            if log_path.name == f"{self.current_date}.log":
                continue
                
            # Try to parse date from filename
            try:
                if log_path.suffix == '.log':
                    date_str = log_path.stem
                    log_date = datetime.strptime(date_str, "%Y-%m-%d")
                    days_old = (now - log_date).days
                    
                    # Delete logs older than MAX_LOG_DAYS
                    if days_old > self.MAX_LOG_DAYS:
                        log_path.unlink()
                        print(f"[CLEANUP] Deleted old log: {log_path.name}")
                    
                    # Compress logs older than COMPRESS_AFTER_DAYS
                    elif days_old > self.COMPRESS_AFTER_DAYS:
                        compressed_path = log_path.with_suffix('.log.gz')
                        if not compressed_path.exists():
                            with open(log_path, 'rb') as f_in:
                                with gzip.open(compressed_path, 'wb') as f_out:
                                    shutil.copyfileobj(f_in, f_out)
                            log_path.unlink()
                            print(f"[CLEANUP] Compressed log: {log_path.name}")
                
                elif log_path.suffix == '.gz':
                    # Check compressed logs for deletion
                    date_str = log_path.stem.replace('.log', '')
                    log_date = datetime.strptime(date_str, "%Y-%m-%d")
                    days_old = (now - log_date).days
                    
                    if days_old > self.MAX_LOG_DAYS:
                        log_path.unlink()
                        print(f"[CLEANUP] Deleted old compressed log: {log_path.name}")
                        
            except (ValueError, AttributeError):
                # Skip files that don't match our date format
                continue
    
    def _check_rotation(self):
        """Check if log rotation is needed (new day or size limit)."""
        # Check if date has changed
        current_date = datetime.now().strftime("%Y-%m-%d")
        if current_date != self.current_date:
            self.current_date = current_date
            self.log_file = self.log_dir / f'{self.current_date}.log'
            self._cleanup_old_logs()
            self._write_session_header()
            return True
        
        # Check if current log exceeds size limit
        if self.log_file.exists():
            size_mb = self.log_file.stat().st_size / (1024 * 1024)
            if size_mb >= self.MAX_LOG_SIZE_MB:
                # Rotate to a new file with timestamp
                timestamp = datetime.now().strftime("%H%M%S")
                rotated_file = self.log_dir / f'{self.current_date}_{timestamp}.log'
                self.log_file.rename(rotated_file)
                
                # Compress the rotated file
                with open(rotated_file, 'rb') as f_in:
                    with gzip.open(rotated_file.with_suffix('.log.gz'), 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                rotated_file.unlink()
                
                # Start new log file
                self.log_file = self.log_dir / f'{self.current_date}.log'
                self._write_session_header()
                print(f"[LOG ROTATION] Rotated large log file (>{self.MAX_LOG_SIZE_MB}MB)")
                return True
        
        return False
    
    def _write_session_header(self):
        """Write a clean session header."""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'═'*70}\n")
            f.write(f"  SESSION STARTED: {self._get_timestamp()}\n")
            f.write(f"{'═'*70}\n")
    
    def _get_timestamp(self) -> str:
        """Get current timestamp in EST timezone."""
        est = timezone(timedelta(hours=-5))
        return datetime.now(est).strftime('%I:%M:%S %p EST')
    
    def _write_tree(self, title: str, items: Optional[List[Tuple[str, str]]] = None, 
                    emoji: str = "•", timestamp: bool = True):
        """
        Write a tree structure to the log.
        
        Args:
            title: Main tree title
            items: List of (key, value) tuples for tree items
            emoji: Emoji/symbol for the tree
            timestamp: Whether to include timestamp
        """
        # Check for rotation before writing
        self._check_rotation()
        
        # Increment entry counter
        self.entries_count += 1
        
        # Periodic cleanup (every 1000 entries)
        if self.entries_count % 1000 == 0:
            self._cleanup_old_logs()
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            # Add blank line before entry for spacing
            f.write("\n")
            
            # Write title with optional timestamp
            if timestamp:
                f.write(f"[{self._get_timestamp()}] {emoji} {title}\n")
            else:
                f.write(f"  {emoji} {title}\n")
            
            # Write tree items if provided
            if items:
                for i, (key, value) in enumerate(items):
                    is_last = (i == len(items) - 1)
                    prefix = "└─" if is_last else "├─"
                    f.write(f"  {prefix} {key}: {value}\n")
            
            # Console output with spacing (only in development)
            if os.getenv('ENV') != 'production':
                print()  # Blank line before
                if timestamp:
                    print(f"[{self._get_timestamp()}] {emoji} {title}")
                else:
                    print(f"  {emoji} {title}")
                if items:
                    for i, (key, value) in enumerate(items):
                        is_last = (i == len(items) - 1)
                        prefix = "└─" if is_last else "├─"
                        print(f"  {prefix} {key}: {value}")
    
    # Event-specific logging methods
    
    def bot_start(self, version_info: dict = None, commands: int = 2):
        """Log bot initialization with version information."""
        if version_info is None:
            # Fallback for backward compatibility
            version_info = {"version": "Modular", "codename": "Unknown"}
        
        self._write_tree(
            "BOT INITIALIZING",
            [
                ("Version", version_info.get("version", "Unknown")),
                ("Codename", version_info.get("codename", "Unknown")),
                ("Release Type", version_info.get("release_type", "Unknown")),
                ("Server", "discord.gg/syria"),
                ("Architecture", "Modular"),
                ("Commands", f"{commands} slash commands"),
                ("Max Log Size", f"{self.MAX_LOG_SIZE_MB}MB"),
                ("Log Retention", f"{self.MAX_LOG_DAYS} days")
            ],
            emoji="🔥"
        )
    
    def bot_ready(self, bot_name: str, bot_id: str, guild_count: int):
        """Log bot ready event."""
        self._write_tree(
            "BOT ONLINE",
            [
                ("Name", bot_name),
                ("ID", bot_id),
                ("Servers", str(guild_count)),
                ("Status", "Active")
            ],
            emoji="✅"
        )
    
    def command_used(self, command: str, user: str, guild: str):
        """Log command usage."""
        self._write_tree(
            f"COMMAND: /{command}",
            [
                ("User", user),
                ("Server", guild),
                ("Time", datetime.now().strftime('%I:%M %p'))
            ],
            emoji="⚡"
        )
    
    def prisoner_event(self, event_type: str, user: str, reason: Optional[str] = None):
        """Log prisoner-related events."""
        items = [("User", user)]
        if reason:
            items.append(("Reason", reason[:50] + "..." if len(reason) > 50 else reason))
        
        emoji = "🔒" if event_type in ["MUTED", "ARRIVING", "DETECTED"] else "🔓"
        self._write_tree(f"PRISONER {event_type}", items, emoji=emoji)
    
    def mute_embed_found(self, user_id: Optional[str] = None, username: Optional[str] = None, 
                         reason: Optional[str] = None, moderator: Optional[str] = None,
                         duration: Optional[str] = None):
        """Log mute embed processing."""
        items = []
        if user_id:
            items.append(("User ID", user_id))
        if username:
            items.append(("Username", username))
        if moderator:
            items.append(("Moderator", moderator[:30]))
        if duration:
            items.append(("Duration", duration))
        if reason:
            items.append(("Reason", reason[:50] + "..." if len(reason) > 50 else reason))
        
        if items:
            self._write_tree("MUTE EMBED", items, emoji="📋")
    
    def ragebait_sent(self, target: str):
        """Log ragebait response (without the actual content)."""
        self._write_tree(
            "RAGEBAIT",
            [("Target", target)],
            emoji="😈"
        )
    
    def service_status(self, service: str, status: str):
        """Log service status changes."""
        emoji = "✅" if "online" in status.lower() or "synced" in status.lower() else "⚠️"
        self._write_tree(
            f"{service.upper()} SERVICE",
            [("Status", status)],
            emoji=emoji
        )
    
    def activation_change(self, activated: bool, user: str, muted_count: int = 0):
        """Log bot activation/deactivation."""
        if activated:
            self._write_tree(
                "BOT ACTIVATED",
                [
                    ("By", user),
                    ("Prisoners", str(muted_count)),
                    ("Mode", "Ragebaiting enabled")
                ],
                emoji="🟢"
            )
        else:
            self._write_tree(
                "BOT DEACTIVATED",
                [
                    ("By", user),
                    ("Mode", "Standby")
                ],
                emoji="🔴"
            )
    
    def database_event(self, operation: str, table: str = "messages", count: int = 0):
        """Log database operations."""
        self._write_tree(
            f"DATABASE: {operation.upper()}",
            [
                ("Table", table),
                ("Records", str(count))
            ],
            emoji="💾"
        )
    
    def error(self, error_type: str, details: str):
        """Log errors in tree format."""
        self._write_tree(
            f"ERROR: {error_type}",
            [("Details", details[:100])],
            emoji="❌"
        )
    
    def warning(self, warning_type: str, details: str):
        """Log warnings in tree format."""
        self._write_tree(
            f"WARNING: {warning_type}",
            [("Details", details[:100])],
            emoji="⚠️"
        )
    
    def get_log_stats(self) -> dict:
        """Get current log statistics."""
        stats = {
            "current_log": self.log_file.name,
            "current_size_mb": 0,
            "total_logs": 0,
            "total_size_mb": 0,
            "compressed_logs": 0
        }
        
        if self.log_file.exists():
            stats["current_size_mb"] = round(self.log_file.stat().st_size / (1024 * 1024), 2)
        
        for log_path in self.log_dir.glob("*.log*"):
            stats["total_logs"] += 1
            stats["total_size_mb"] += log_path.stat().st_size / (1024 * 1024)
            if log_path.suffix == '.gz':
                stats["compressed_logs"] += 1
        
        stats["total_size_mb"] = round(stats["total_size_mb"], 2)
        return stats
    
    # Convenience methods for backward compatibility
    
    def info(self, msg: str):
        """Log info as a simple tree node."""
        self._write_tree(msg, emoji="ℹ️")
    
    def success(self, msg: str):
        """Log success as a simple tree node."""
        self._write_tree(msg, emoji="✅")
    
    def tree(self, title: str, items: list, emoji: str = "📦"):
        """Generic tree logging for custom events."""
        self._write_tree(title, items, emoji=emoji)


# Global logger instance
logger = TreeLogger()