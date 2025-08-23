"""
Automated Database Backup System for AzabBot
=============================================

Handles scheduled backups and rotation of database files.
"""

import asyncio
import shutil
import gzip
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import hashlib
from src.core.logger import get_logger

class BackupManager:
    """Manages automated database backups."""
    
    def __init__(
        self,
        db_path: Path,
        backup_dir: Path = Path("backups"),
        max_backups: int = 10,
        compress: bool = True
    ):
        """
        Initialize backup manager.
        
        Args:
            db_path: Path to database file
            backup_dir: Directory for backups
            max_backups: Maximum number of backups to keep
            compress: Whether to compress backups
        """
        self.db_path = db_path
        self.backup_dir = backup_dir
        self.max_backups = max_backups
        self.compress = compress
        self.logger = get_logger()
        
        # Backup scheduling
        self.backup_interval = 3600  # 1 hour default
        self.backup_task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = {
            "total_backups": 0,
            "successful_backups": 0,
            "failed_backups": 0,
            "last_backup": None,
            "total_size_saved": 0
        }
        
        # Create backup directory
        self.backup_dir.mkdir(parents=True, exist_ok=True)
    
    async def start(self, interval: int = 3600):
        """
        Start automated backup schedule.
        
        Args:
            interval: Backup interval in seconds
        """
        self.backup_interval = interval
        self.backup_task = asyncio.create_task(self._backup_loop())
        
        # Perform initial backup
        await self.create_backup("initial")
        
        self.logger.log_info(
            f"Backup manager started (interval: {interval}s)"
        )
    
    async def stop(self):
        """Stop automated backups."""
        if self.backup_task:
            self.backup_task.cancel()
            try:
                await self.backup_task
            except asyncio.CancelledError:
                pass
        
        # Create final backup
        await self.create_backup("shutdown")
        
        self.logger.log_info(
            f"Backup manager stopped (total: {self.stats['total_backups']}, successful: {self.stats['successful_backups']})"
        )
    
    async def _backup_loop(self):
        """Main backup loop."""
        while True:
            try:
                await asyncio.sleep(self.backup_interval)
                await self.create_backup("scheduled")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.log_error(f"Backup loop error: {e}")
    
    async def create_backup(
        self, 
        reason: str = "manual",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Path]:
        """
        Create a database backup.
        
        Args:
            reason: Reason for backup
            metadata: Additional metadata to store
            
        Returns:
            Path to backup file or None if failed
        """
        self.stats["total_backups"] += 1
        
        try:
            # Check if database exists
            if not self.db_path.exists():
                self.logger.log_warning("Database file not found, skipping backup")
                return None
            
            # Generate backup filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"azabbot_{timestamp}_{reason}"
            
            if self.compress:
                backup_path = self.backup_dir / f"{backup_name}.db.gz"
            else:
                backup_path = self.backup_dir / f"{backup_name}.db"
            
            # Create backup
            self.logger.log_debug(
                f"Creating backup: {backup_path.name}",
                context={"reason": reason}
            )
            
            if self.compress:
                await self._create_compressed_backup(backup_path)
            else:
                await self._create_regular_backup(backup_path)
            
            # Calculate checksum
            checksum = await self._calculate_checksum(backup_path)
            
            # Save metadata
            await self._save_metadata(backup_path, {
                "timestamp": datetime.now().isoformat(),
                "reason": reason,
                "size": backup_path.stat().st_size,
                "checksum": checksum,
                "compressed": self.compress,
                "original_size": self.db_path.stat().st_size,
                **(metadata or {})
            })
            
            # Update statistics
            self.stats["successful_backups"] += 1
            self.stats["last_backup"] = datetime.now().isoformat()
            self.stats["total_size_saved"] += backup_path.stat().st_size
            
            self.logger.log_info(
                f"Backup created successfully",
                context={
                    "file": backup_path.name,
                    "size": f"{backup_path.stat().st_size / 1024:.1f}KB",
                    "reason": reason
                }
            )
            
            # Rotate old backups
            await self._rotate_backups()
            
            return backup_path
            
        except Exception as e:
            self.stats["failed_backups"] += 1
            self.logger.log_error(f"Backup failed: {e}")
            return None
    
    async def _create_regular_backup(self, backup_path: Path):
        """Create uncompressed backup."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            shutil.copy2,
            str(self.db_path),
            str(backup_path)
        )
    
    async def _create_compressed_backup(self, backup_path: Path):
        """Create compressed backup."""
        loop = asyncio.get_event_loop()
        
        def compress():
            with open(self.db_path, "rb") as f_in:
                with gzip.open(backup_path, "wb", compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)
        
        await loop.run_in_executor(None, compress)
    
    async def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of file."""
        loop = asyncio.get_event_loop()
        
        def checksum():
            sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256.update(chunk)
            return sha256.hexdigest()
        
        return await loop.run_in_executor(None, checksum)
    
    async def _save_metadata(self, backup_path: Path, metadata: Dict[str, Any]):
        """Save backup metadata."""
        metadata_path = backup_path.with_suffix(".meta.json")
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: metadata_path.write_text(
                json.dumps(metadata, indent=2)
            )
        )
    
    async def _rotate_backups(self):
        """Remove old backups exceeding max_backups limit."""
        try:
            # Get all backup files
            backups = []
            for ext in [".db", ".db.gz"]:
                backups.extend(self.backup_dir.glob(f"*{ext}"))
            
            # Sort by modification time
            backups.sort(key=lambda p: p.stat().st_mtime)
            
            # Remove oldest if exceeding limit
            while len(backups) > self.max_backups:
                old_backup = backups.pop(0)
                
                # Remove backup and metadata
                old_backup.unlink()
                
                meta_file = old_backup.with_suffix(".meta.json")
                if meta_file.exists():
                    meta_file.unlink()
                
                self.logger.log_debug(
                    f"Removed old backup: {old_backup.name}"
                )
        
        except Exception as e:
            self.logger.log_error(f"Error rotating backups: {e}")
    
    async def restore_backup(
        self, 
        backup_path: Optional[Path] = None
    ) -> bool:
        """
        Restore database from backup.
        
        Args:
            backup_path: Path to backup file (latest if None)
            
        Returns:
            True if successful
        """
        try:
            # Find backup to restore
            if backup_path is None:
                backups = []
                for ext in [".db", ".db.gz"]:
                    backups.extend(self.backup_dir.glob(f"*{ext}"))
                
                if not backups:
                    self.logger.log_error("No backups found")
                    return False
                
                # Use most recent
                backup_path = max(backups, key=lambda p: p.stat().st_mtime)
            
            if not backup_path.exists():
                self.logger.log_error(f"Backup not found: {backup_path}")
                return False
            
            # Verify checksum if metadata exists
            meta_file = backup_path.with_suffix(".meta.json")
            if meta_file.exists():
                metadata = json.loads(meta_file.read_text())
                expected_checksum = metadata.get("checksum")
                
                if expected_checksum:
                    actual_checksum = await self._calculate_checksum(backup_path)
                    if actual_checksum != expected_checksum:
                        self.logger.log_error(
                            "Backup checksum mismatch",
                            context={
                                "expected": expected_checksum,
                                "actual": actual_checksum
                            }
                        )
                        return False
            
            # Backup current database before restore
            if self.db_path.exists():
                pre_restore = self.db_path.with_suffix(".pre_restore.db")
                shutil.copy2(self.db_path, pre_restore)
            
            # Restore backup
            self.logger.log_info(
                f"Restoring from backup: {backup_path.name}"
            )
            
            if backup_path.suffix == ".gz":
                # Decompress
                loop = asyncio.get_event_loop()
                
                def decompress():
                    with gzip.open(backup_path, "rb") as f_in:
                        with open(self.db_path, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                
                await loop.run_in_executor(None, decompress)
            else:
                # Direct copy
                shutil.copy2(backup_path, self.db_path)
            
            self.logger.log_info("Database restored successfully")
            return True
            
        except Exception as e:
            self.logger.log_error(f"Restore failed: {e}")
            
            # Try to restore pre-restore backup
            pre_restore = self.db_path.with_suffix(".pre_restore.db")
            if pre_restore.exists():
                shutil.copy2(pre_restore, self.db_path)
                self.logger.log_info("Reverted to pre-restore database")
            
            return False
    
    async def list_backups(self) -> List[Dict[str, Any]]:
        """List all available backups."""
        backups = []
        
        for ext in [".db", ".db.gz"]:
            for backup_path in self.backup_dir.glob(f"*{ext}"):
                info = {
                    "path": str(backup_path),
                    "name": backup_path.name,
                    "size": backup_path.stat().st_size,
                    "modified": datetime.fromtimestamp(
                        backup_path.stat().st_mtime
                    ).isoformat()
                }
                
                # Add metadata if available
                meta_file = backup_path.with_suffix(".meta.json")
                if meta_file.exists():
                    try:
                        metadata = json.loads(meta_file.read_text())
                        info.update(metadata)
                    except:
                        pass
                
                backups.append(info)
        
        # Sort by modification time (newest first)
        backups.sort(key=lambda b: b["modified"], reverse=True)
        
        return backups
    
    def get_stats(self) -> Dict[str, Any]:
        """Get backup statistics."""
        return {
            **self.stats,
            "backup_count": len(list(self.backup_dir.glob("*.db*"))),
            "total_backup_size": sum(
                f.stat().st_size 
                for f in self.backup_dir.glob("*.db*")
            )
        }

# Global backup manager instance
_backup_manager: Optional[BackupManager] = None

def get_backup_manager() -> Optional[BackupManager]:
    """Get global backup manager."""
    return _backup_manager

def init_backup_manager(
    db_path: Path,
    backup_dir: Path = Path("backups"),
    max_backups: int = 10
) -> BackupManager:
    """Initialize global backup manager."""
    global _backup_manager
    _backup_manager = BackupManager(db_path, backup_dir, max_backups)
    return _backup_manager