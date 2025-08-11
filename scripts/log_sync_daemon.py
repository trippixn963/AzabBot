#!/usr/bin/env python3
"""
AzabBot Log Sync Daemon (Python Version)
========================================

Advanced log synchronization daemon with the following features:
- Efficient incremental syncing using rsync
- Automatic reconnection on connection loss
- Progress tracking and statistics
- Intelligent sync intervals (more frequent when active)
- Compression for faster transfers
- Bandwidth limiting to avoid network congestion
"""

import os
import sys
import time
import subprocess
import logging
import signal
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

# Configuration
CONFIG = {
    "remote_host": "root@159.89.90.90",
    "remote_path": "/root/AzabBot/logs/",
    "local_path": "/Users/johnhamwi/Developer/AzabBot/logs/",
    "sync_interval": 30,  # Base sync interval in seconds
    "quick_sync_interval": 10,  # Faster sync when files are changing
    "bandwidth_limit": 1000,  # KB/s (0 for unlimited)
    "compression": True,
    "delete_missing": True,  # Delete local files not on remote
    "ssh_timeout": 10,
    "max_retries": 3,
    "retry_delay": 60,
}

# Setup logging
log_dir = Path(CONFIG["local_path"])
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "sync_daemon.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class LogSyncDaemon:
    """Advanced log synchronization daemon."""
    
    def __init__(self, config: Dict):
        """Initialize the sync daemon."""
        self.config = config
        self.running = True
        self.last_sync_time = None
        self.last_file_count = 0
        self.last_total_size = 0
        self.consecutive_failures = 0
        self.stats = {
            "syncs_completed": 0,
            "syncs_failed": 0,
            "bytes_transferred": 0,
            "files_synced": 0,
            "start_time": datetime.now().isoformat()
        }
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        signal.signal(signal.SIGINT, self.handle_shutdown)
        
    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
        self.save_stats()
        sys.exit(0)
        
    def save_stats(self):
        """Save statistics to file."""
        stats_file = Path(self.config["local_path"]) / "sync_stats.json"
        try:
            with open(stats_file, 'w') as f:
                json.dump(self.stats, f, indent=2)
            logger.info(f"Statistics saved to {stats_file}")
        except Exception as e:
            logger.error(f"Failed to save stats: {e}")
            
    def check_remote_connection(self) -> bool:
        """Check if remote host is reachable."""
        try:
            cmd = [
                "ssh",
                "-o", f"ConnectTimeout={self.config['ssh_timeout']}",
                "-o", "BatchMode=yes",
                self.config["remote_host"],
                "exit"
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=self.config['ssh_timeout'])
            return result.returncode == 0
        except (subprocess.TimeoutExpired, Exception) as e:
            logger.warning(f"Connection check failed: {e}")
            return False
            
    def get_remote_stats(self) -> Optional[Dict]:
        """Get statistics about remote log directory."""
        try:
            cmd = [
                "ssh",
                "-o", f"ConnectTimeout={self.config['ssh_timeout']}",
                "-o", "BatchMode=yes",
                self.config["remote_host"],
                f"find {self.config['remote_path']} -type f -name '*.log' | wc -l && "
                f"du -sb {self.config['remote_path']} | cut -f1"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.config['ssh_timeout'])
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 2:
                    return {
                        "file_count": int(lines[0]),
                        "total_size": int(lines[1])
                    }
        except Exception as e:
            logger.debug(f"Failed to get remote stats: {e}")
        return None
        
    def sync_logs(self) -> bool:
        """Perform log synchronization using rsync."""
        try:
            # Build rsync command
            rsync_cmd = ["rsync", "-az"]
            
            # Add verbose for progress tracking
            rsync_cmd.append("--info=progress2")
            
            # Add compression if enabled
            if not self.config["compression"]:
                rsync_cmd.append("--no-compress")
                
            # Add bandwidth limit if set
            if self.config["bandwidth_limit"] > 0:
                rsync_cmd.append(f"--bwlimit={self.config['bandwidth_limit']}")
                
            # Add delete option if enabled
            if self.config["delete_missing"]:
                rsync_cmd.append("--delete")
                
            # Add exclusions
            rsync_cmd.extend([
                "--exclude", "sync_daemon.log",
                "--exclude", "sync_stats.json",
                "--exclude", ".DS_Store",
                "--exclude", "*.swp",
                "--exclude", "*.tmp"
            ])
            
            # Add source and destination
            rsync_cmd.append(f"{self.config['remote_host']}:{self.config['remote_path']}")
            rsync_cmd.append(self.config["local_path"])
            
            # Execute rsync
            logger.debug(f"Running: {' '.join(rsync_cmd)}")
            result = subprocess.run(
                rsync_cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout for large syncs
            )
            
            if result.returncode == 0:
                # Parse rsync output for statistics
                if result.stdout:
                    self.parse_rsync_output(result.stdout)
                    
                self.stats["syncs_completed"] += 1
                self.consecutive_failures = 0
                return True
            else:
                logger.error(f"Rsync failed with code {result.returncode}: {result.stderr}")
                self.stats["syncs_failed"] += 1
                self.consecutive_failures += 1
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("Rsync timed out after 5 minutes")
            self.stats["syncs_failed"] += 1
            self.consecutive_failures += 1
            return False
        except Exception as e:
            logger.error(f"Sync failed with exception: {e}")
            self.stats["syncs_failed"] += 1
            self.consecutive_failures += 1
            return False
            
    def parse_rsync_output(self, output: str):
        """Parse rsync output for statistics."""
        try:
            # Look for transferred bytes in rsync output
            for line in output.split('\n'):
                if 'bytes received' in line:
                    # Extract bytes from line like "sent 1234 bytes  received 5678 bytes"
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'received' and i > 0:
                            bytes_received = int(parts[i-1].replace(',', ''))
                            self.stats["bytes_transferred"] += bytes_received
                            logger.debug(f"Transferred {bytes_received} bytes")
                            break
        except Exception as e:
            logger.debug(f"Failed to parse rsync output: {e}")
            
    def determine_sync_interval(self) -> int:
        """Determine sync interval based on activity."""
        # Get current remote stats
        remote_stats = self.get_remote_stats()
        
        if remote_stats:
            # Check if files are actively changing
            if (self.last_file_count > 0 and 
                remote_stats["file_count"] != self.last_file_count):
                # Files are changing, use quick sync
                logger.debug("Files changing, using quick sync interval")
                return self.config["quick_sync_interval"]
                
            self.last_file_count = remote_stats["file_count"]
            self.last_total_size = remote_stats["total_size"]
            
        # Use normal interval
        return self.config["sync_interval"]
        
    def run(self):
        """Main daemon loop."""
        logger.info("=" * 60)
        logger.info("AzabBot Log Sync Daemon Starting")
        logger.info(f"Remote: {self.config['remote_host']}:{self.config['remote_path']}")
        logger.info(f"Local: {self.config['local_path']}")
        logger.info(f"Sync interval: {self.config['sync_interval']}s (quick: {self.config['quick_sync_interval']}s)")
        logger.info(f"Bandwidth limit: {self.config['bandwidth_limit']} KB/s" if self.config['bandwidth_limit'] > 0 else "Bandwidth: unlimited")
        logger.info("=" * 60)
        
        # Initial sync
        logger.info("Performing initial sync...")
        if self.check_remote_connection():
            if self.sync_logs():
                logger.info("Initial sync completed successfully")
            else:
                logger.warning("Initial sync failed")
        else:
            logger.error("Cannot connect to remote host for initial sync")
            
        # Main loop
        while self.running:
            try:
                # Determine dynamic sync interval
                sync_interval = self.determine_sync_interval()
                
                # Wait for next sync
                time.sleep(sync_interval)
                
                # Check connection
                if not self.check_remote_connection():
                    logger.warning(f"Cannot reach {self.config['remote_host']}")
                    
                    # Exponential backoff on connection failures
                    if self.consecutive_failures > 0:
                        backoff = min(300, self.config["retry_delay"] * (2 ** self.consecutive_failures))
                        logger.info(f"Waiting {backoff}s before retry (failure #{self.consecutive_failures})")
                        time.sleep(backoff)
                    continue
                    
                # Perform sync
                sync_start = time.time()
                if self.sync_logs():
                    sync_duration = time.time() - sync_start
                    if sync_duration > 1:  # Only log if sync took more than 1 second
                        logger.info(f"Sync completed in {sync_duration:.1f}s")
                    self.last_sync_time = datetime.now()
                else:
                    logger.error(f"Sync failed (attempt #{self.consecutive_failures})")
                    
                # Save stats periodically (every 100 syncs)
                if self.stats["syncs_completed"] % 100 == 0:
                    self.save_stats()
                    
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                time.sleep(self.config["retry_delay"])
                
        # Cleanup
        self.save_stats()
        logger.info("Sync daemon stopped")


if __name__ == "__main__":
    daemon = LogSyncDaemon(CONFIG)
    daemon.run()