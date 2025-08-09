# =============================================================================
# SaydnayaBot - Log Optimization & Deletion System
# =============================================================================
# Manages log files efficiently by:
# - Automatically deleting old logs to save disk space
# - Compressing logs older than 1 day
# - Batching log writes to reduce disk I/O
# - Keeping only essential logs for debugging
# =============================================================================

import asyncio
import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.logger import get_logger

class LogDeletionManager:
    """
    Manages automatic log deletion and compression.

    Features:
    - Deletes logs older than configured retention period
    - Compresses logs between 1-7 days old
    - Maintains separate retention for error logs
    - Runs automatically in the background
    """

    def __init__(
        self,
        log_dir: Path,
        retention_days: int = 7,
        compress_after_days: int = 1,
        error_retention_days: int = 30,
    ):
        """
        Initialize the log deletion manager.

        Args:
            log_dir: Base directory for logs
            retention_days: Days to keep logs (default: 7)
            compress_after_days: Compress logs older than this (default: 1)
            error_retention_days: Days to keep error logs (default: 30)
        """
        self.log_dir = log_dir
        self.retention_days = retention_days
        self.compress_after_days = compress_after_days
        self.error_retention_days = error_retention_days

        self.logger = get_logger()
        self._deletion_task: Optional[asyncio.Task] = None
        self._shutdown = False

        # Statistics
        self.stats = {
            "files_deleted": 0,
            "files_compressed": 0,
            "bytes_freed": 0,
            "bytes_saved": 0,
            "last_cleanup": None,
        }

    async def start(self):
        """Start the automatic log deletion process."""
        self.logger.log_info("Starting log deletion manager", "🧹")

        # Run initial cleanup
        await self.cleanup_logs()

        # Start background task
        self._deletion_task = asyncio.create_task(self._deletion_loop())

    async def stop(self):
        """Stop the log deletion process."""
        self._shutdown = True

        if self._deletion_task and not self._deletion_task.done():
            self._deletion_task.cancel()
            try:
                await self._deletion_task
            except asyncio.CancelledError:
                pass

        self.logger.log_info(
            f"Log deletion manager stopped - Freed {self._format_bytes(self.stats['bytes_freed'])}",
            "🛑",
        )

    async def _deletion_loop(self):
        """Background loop for periodic log cleanup."""
        while not self._shutdown:
            try:
                # Run cleanup every 6 hours
                await asyncio.sleep(21600)  # 6 hours
                await self.cleanup_logs()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.log_error(f"Log cleanup error: {e}")

    async def cleanup_logs(self):
        """Perform log cleanup - compress and delete old files."""
        if not self.log_dir.exists():
            return

        now = datetime.now()
        compress_cutoff = now - timedelta(days=self.compress_after_days)
        delete_cutoff = now - timedelta(days=self.retention_days)
        error_delete_cutoff = now - timedelta(days=self.error_retention_days)

        cleanup_stats = {
            "compressed": 0,
            "deleted": 0,
            "bytes_freed": 0,
            "bytes_saved": 0,
        }

        # Process all files in log directory
        for file_path in self._get_all_log_files():
            try:
                # Skip already compressed files
                if file_path.suffix == ".gz":
                    # Check if compressed file should be deleted
                    if self._should_delete_file(
                        file_path, delete_cutoff, error_delete_cutoff
                    ):
                        size = file_path.stat().st_size
                        file_path.unlink()
                        cleanup_stats["deleted"] += 1
                        cleanup_stats["bytes_freed"] += size
                    continue

                # Check if file should be deleted
                if self._should_delete_file(
                    file_path, delete_cutoff, error_delete_cutoff
                ):
                    size = file_path.stat().st_size
                    file_path.unlink()
                    cleanup_stats["deleted"] += 1
                    cleanup_stats["bytes_freed"] += size

                # Check if file should be compressed
                elif self._should_compress_file(file_path, compress_cutoff):
                    saved = await self._compress_file(file_path)
                    if saved > 0:
                        cleanup_stats["compressed"] += 1
                        cleanup_stats["bytes_saved"] += saved

            except Exception as e:
                self.logger.log_error(f"Error processing {file_path}: {e}")

        # Update total statistics
        self.stats["files_deleted"] += cleanup_stats["deleted"]
        self.stats["files_compressed"] += cleanup_stats["compressed"]
        self.stats["bytes_freed"] += cleanup_stats["bytes_freed"]
        self.stats["bytes_saved"] += cleanup_stats["bytes_saved"]
        self.stats["last_cleanup"] = now.isoformat()

        # Log results if any action was taken
        if cleanup_stats["deleted"] > 0 or cleanup_stats["compressed"] > 0:
            self.logger.log_info(
                f"Log cleanup completed - Deleted: {cleanup_stats['deleted']} files "
                f"({self._format_bytes(cleanup_stats['bytes_freed'])}), "
                f"Compressed: {cleanup_stats['compressed']} files "
                f"({self._format_bytes(cleanup_stats['bytes_saved'])} saved)",
                "🧹",
            )

    def _get_all_log_files(self) -> list[Path]:
        """Get all log files in the directory recursively."""
        log_files = []

        for pattern in ["*.log", "*.json", "*.log.gz", "*.json.gz"]:
            log_files.extend(self.log_dir.rglob(pattern))

        return log_files

    def _should_delete_file(
        self, file_path: Path, delete_cutoff: datetime, error_delete_cutoff: datetime
    ) -> bool:
        """Check if a file should be deleted based on age."""
        try:
            # Get file modification time
            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

            # Error logs get longer retention
            if "error" in file_path.name.lower():
                return file_mtime < error_delete_cutoff
            else:
                return file_mtime < delete_cutoff

        except Exception:
            return False

    def _should_compress_file(self, file_path: Path, compress_cutoff: datetime) -> bool:
        """Check if a file should be compressed based on age."""
        try:
            # Don't compress tiny files
            if file_path.stat().st_size < 1024:  # Less than 1KB
                return False

            # Check age
            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            return file_mtime < compress_cutoff

        except Exception:
            return False

    async def _compress_file(self, file_path: Path) -> int:
        """
        Compress a log file using gzip.

        Returns:
            Bytes saved by compression
        """
        try:
            compressed_path = file_path.with_suffix(file_path.suffix + ".gz")

            # Get original size
            original_size = file_path.stat().st_size

            # Compress file
            with open(file_path, "rb") as f_in:
                with gzip.open(compressed_path, "wb", compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)

            # Get compressed size
            compressed_size = compressed_path.stat().st_size

            # Remove original file
            file_path.unlink()

            # Return bytes saved
            return original_size - compressed_size

        except Exception as e:
            self.logger.log_error(f"Failed to compress {file_path}: {e}")
            return 0

    def _format_bytes(self, bytes_value: int) -> str:
        """Format bytes into human-readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_value < 1024.0:
                return f"{bytes_value:.1f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.1f} TB"

    def get_stats(self) -> Dict[str, Any]:
        """Get cleanup statistics."""
        return {
            **self.stats,
            "bytes_freed_formatted": self._format_bytes(self.stats["bytes_freed"]),
            "bytes_saved_formatted": self._format_bytes(self.stats["bytes_saved"]),
            "current_log_size": self._get_current_log_size(),
        }

    def _get_current_log_size(self) -> str:
        """Get current total size of log directory."""
        try:
            total_size = sum(
                f.stat().st_size for f in self._get_all_log_files() if f.is_file()
            )
            return self._format_bytes(total_size)
        except Exception:
            return "Unknown"

class LogRotationManager:
    """
    Manages log rotation to prevent single files from growing too large.

    Features:
    - Rotates logs when they exceed size limit
    - Maintains numbered backups
    - Integrates with compression system
    """

    def __init__(self, max_file_size_mb: int = 10, max_backups: int = 5):
        """
        Initialize log rotation manager.

        Args:
            max_file_size_mb: Maximum size per log file in MB
            max_backups: Maximum number of backup files to keep
        """
        self.max_file_size = max_file_size_mb * 1024 * 1024  # Convert to bytes
        self.max_backups = max_backups
        self.logger = get_logger()

    def should_rotate(self, file_path: Path) -> bool:
        """Check if a file needs rotation."""
        try:
            return file_path.exists() and file_path.stat().st_size > self.max_file_size
        except Exception:
            return False

    def rotate_file(self, file_path: Path):
        """Rotate a log file."""
        if not file_path.exists():
            return

        try:
            # Find next available backup number
            backup_num = 1
            while backup_num <= self.max_backups:
                backup_path = file_path.with_suffix(f".{backup_num}{file_path.suffix}")
                if not backup_path.exists():
                    break
                backup_num += 1

            # If we've exceeded max backups, remove the oldest
            if backup_num > self.max_backups:
                oldest = file_path.with_suffix(f".{self.max_backups}{file_path.suffix}")
                if oldest.exists():
                    oldest.unlink()
                backup_num = self.max_backups

            # Rotate existing backups
            for i in range(backup_num - 1, 0, -1):
                old_path = file_path.with_suffix(f".{i}{file_path.suffix}")
                new_path = file_path.with_suffix(f".{i + 1}{file_path.suffix}")
                if old_path.exists():
                    old_path.rename(new_path)

            # Move current file to backup.1
            file_path.rename(file_path.with_suffix(f".1{file_path.suffix}"))

            self.logger.log_info(f"Rotated log file: {file_path.name}")

        except Exception as e:
            self.logger.log_error(f"Failed to rotate {file_path}: {e}")

# Global instance for easy access
_log_deletion_manager: Optional[LogDeletionManager] = None
_log_rotation_manager: Optional[LogRotationManager] = None

async def initialize_log_management(
    log_dir: Path,
    retention_days: int = 7,
    compress_after_days: int = 1,
    error_retention_days: int = 30,
    max_file_size_mb: int = 10,
):
    """Initialize the global log management system."""
    global _log_deletion_manager, _log_rotation_manager

    _log_deletion_manager = LogDeletionManager(
        log_dir=log_dir,
        retention_days=retention_days,
        compress_after_days=compress_after_days,
        error_retention_days=error_retention_days,
    )

    _log_rotation_manager = LogRotationManager(max_file_size_mb=max_file_size_mb)

    await _log_deletion_manager.start()

async def shutdown_log_management():
    """Shutdown the log management system."""
    global _log_deletion_manager

    if _log_deletion_manager:
        await _log_deletion_manager.stop()
        _log_deletion_manager = None

def get_log_deletion_manager() -> Optional[LogDeletionManager]:
    """Get the global log deletion manager instance."""
    return _log_deletion_manager

def get_log_rotation_manager() -> Optional[LogRotationManager]:
    """Get the global log rotation manager instance."""
    return _log_rotation_manager
