# =============================================================================
# SaydnayaBot - Instance Management System
# =============================================================================
# Prevents multiple bot instances from running simultaneously by detecting
# and automatically terminating existing instances before starting.
# =============================================================================

import os
import time
from pathlib import Path
from typing import List, Optional

import psutil

from src.core.logger import get_logger

class InstanceManager:
    """
    Manages bot instances to prevent conflicts.

    Features:
    - Detects existing bot instances
    - Automatically terminates old instances
    - Provides graceful shutdown with force-kill fallback
    - Cross-platform compatibility
    """

    def __init__(self, bot_name: str = "SaydnayaBot"):
        """
        Initialize instance manager.

        Args:
            bot_name: Name of the bot for detection
        """
        self.bot_name = bot_name
        self.logger = get_logger()
        self.current_pid = os.getpid()
        self.project_root = Path.cwd()

    def check_and_terminate_existing(self) -> bool:
        """
        Check for existing instances and terminate them.

        Returns:
            True if safe to proceed, False if critical error
        """
        try:
            existing_processes = self._find_existing_instances()

            if not existing_processes:
                self.logger.log_info("No existing instances detected", "✅")
                return True

            self.logger.log_info(
                f"Found {len(existing_processes)} existing instance(s), terminating...",
                "🔍",
            )

            return self._terminate_processes(existing_processes)

        except Exception as e:
            self.logger.log_error(f"Error checking instances: {e}")
            # Proceed anyway - better to try than fail completely
            return True

    def _find_existing_instances(self) -> List[psutil.Process]:
        """
        Find all existing bot instances.

        Returns:
            List of process objects for existing instances
        """
        bot_processes = []

        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
                try:
                    # Skip current process
                    if proc.info["pid"] == self.current_pid:
                        continue

                    # Check if it's a Python process
                    if (
                        not proc.info["name"]
                        or "python" not in proc.info["name"].lower()
                    ):
                        continue

                    # Check command line for bot files
                    cmdline = proc.info.get("cmdline")
                    if not cmdline:
                        continue

                    cmdline_str = " ".join(cmdline).lower()

                    # Look for bot-specific indicators
                    if any(
                        indicator in cmdline_str
                        for indicator in [
                            "saydnayabot",
                            "saydnaya_bot",
                            "app/main.py",
                            "main.py",
                        ]
                    ):
                        # Verify it's from the same project directory
                        try:
                            proc_cwd = proc.cwd()
                            if self.bot_name.lower() in proc_cwd.lower():
                                bot_processes.append(proc)
                                self.logger.log_info(
                                    f"Found existing instance: PID {proc.pid}"
                                )
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue

                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ):
                    continue

        except Exception as e:
            self.logger.log_warning(f"Error scanning processes: {e}")

        return bot_processes

    def _terminate_processes(self, processes: List[psutil.Process]) -> bool:
        """
        Terminate the given processes.

        Args:
            processes: List of processes to terminate

        Returns:
            True if all processes terminated successfully
        """
        terminated_count = 0
        failed_count = 0

        for proc in processes:
            try:
                pid = proc.pid

                # Try graceful termination first
                self.logger.log_info(f"Terminating process {pid} gracefully...")
                proc.terminate()

                try:
                    # Wait up to 5 seconds for graceful shutdown
                    proc.wait(timeout=5)
                    terminated_count += 1
                    self.logger.log_info(f"Process {pid} terminated gracefully", "✅")

                except psutil.TimeoutExpired:
                    # Force kill if graceful shutdown failed
                    self.logger.log_warning(
                        f"Process {pid} didn't stop gracefully, force killing..."
                    )
                    proc.kill()
                    proc.wait(timeout=3)
                    terminated_count += 1
                    self.logger.log_info(f"Process {pid} force killed", "⚡")

            except psutil.NoSuchProcess:
                # Process already gone
                terminated_count += 1

            except psutil.AccessDenied:
                failed_count += 1
                self.logger.log_error(f"Access denied to terminate process {proc.pid}")

            except Exception as e:
                failed_count += 1
                self.logger.log_error(f"Failed to terminate process {proc.pid}: {e}")

        # Give processes time to fully release resources
        if processes:
            time.sleep(2)

        # Report results
        if failed_count == 0:
            self.logger.log_info(
                f"All {terminated_count} instances terminated successfully", "✅"
            )
            return True
        else:
            self.logger.log_warning(
                f"Terminated {terminated_count} instances, " f"{failed_count} failed",
                "⚠️",
            )
            # Still proceed if we terminated some
            return terminated_count > 0 or failed_count < len(processes)

    def create_pid_file(self, pid_file: Path = Path("bot.pid")) -> bool:
        """
        Create a PID file for the current process.

        Args:
            pid_file: Path to PID file

        Returns:
            True if created successfully
        """
        try:
            # Check if PID file exists and process is still running
            if pid_file.exists():
                try:
                    old_pid = int(pid_file.read_text().strip())

                    # Check if old process still exists
                    if psutil.pid_exists(old_pid):
                        try:
                            old_proc = psutil.Process(old_pid)
                            # Verify it's a Python process
                            if "python" in old_proc.name().lower():
                                self.logger.log_warning(
                                    f"Found stale PID file for process {old_pid}"
                                )
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                except (ValueError, IOError):
                    pass

                # Remove stale PID file
                pid_file.unlink()

            # Create new PID file
            pid_file.write_text(str(self.current_pid))
            self.logger.log_info(f"Created PID file: {pid_file}")
            return True

        except Exception as e:
            self.logger.log_error(f"Failed to create PID file: {e}")
            return False

    def cleanup_pid_file(self, pid_file: Path = Path("bot.pid")):
        """Remove PID file on shutdown."""
        try:
            if pid_file.exists():
                pid_file.unlink()
                self.logger.log_info("Removed PID file")
        except Exception as e:
            self.logger.log_error(f"Failed to remove PID file: {e}")

# Global instance manager
_instance_manager: Optional[InstanceManager] = None

def get_instance_manager() -> InstanceManager:
    """Get or create the global instance manager."""
    global _instance_manager
    if _instance_manager is None:
        _instance_manager = InstanceManager()
    return _instance_manager
