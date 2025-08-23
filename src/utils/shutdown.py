"""
Graceful Shutdown Handler for AzabBot
======================================

Ensures clean shutdown and resource cleanup.
"""

import asyncio
import signal
import sys
import time
from typing import List, Callable, Optional, Any
from pathlib import Path
from src.core.logger import get_logger

class ShutdownHandler:
    """Manages graceful shutdown of the bot."""
    
    def __init__(self):
        """Initialize shutdown handler."""
        self.logger = get_logger()
        self.shutdown_callbacks: List[Callable] = []
        self.is_shutting_down = False
        self.shutdown_event = asyncio.Event()
        self.max_shutdown_time = 30  # Maximum seconds to wait for shutdown
        
        # Track resources
        self.resources = {
            "database_connections": [],
            "active_tasks": [],
            "voice_connections": [],
            "file_handles": [],
        }
        
        # Shutdown state file
        self.state_file = Path("data/shutdown_state.json")
    
    def register_signal_handlers(self):
        """Register system signal handlers."""
        signals = [signal.SIGINT, signal.SIGTERM]
        
        for sig in signals:
            signal.signal(sig, self._signal_handler)
        
        # Windows specific
        if sys.platform == "win32":
            signal.signal(signal.SIGBREAK, self._signal_handler)
        
        self.logger.log_info("Shutdown signal handlers registered")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        signal_name = signal.Signals(signum).name
        self.logger.log_warning(
            f"Received shutdown signal: {signal_name}",
            context={"signal": signum}
        )
        
        # Trigger shutdown
        asyncio.create_task(self.shutdown(f"Signal {signal_name}"))
    
    async def shutdown(self, reason: str = "Unknown"):
        """
        Perform graceful shutdown.
        
        Args:
            reason: Reason for shutdown
        """
        if self.is_shutting_down:
            self.logger.log_debug("Shutdown already in progress")
            return
        
        self.is_shutting_down = True
        self.shutdown_event.set()
        
        self.logger.log_warning(
            "Starting graceful shutdown",
            context={"reason": reason}
        )
        
        start_time = time.time()
        
        try:
            # Save state
            await self._save_state()
            
            # Execute callbacks with timeout
            await asyncio.wait_for(
                self._execute_callbacks(),
                timeout=self.max_shutdown_time
            )
            
            # Clean up resources
            await self._cleanup_resources()
            
            elapsed = time.time() - start_time
            self.logger.log_info(
                f"Graceful shutdown completed in {elapsed:.2f}s",
                context={"reason": reason}
            )
            
        except asyncio.TimeoutError:
            self.logger.log_error(
                f"Shutdown timeout after {self.max_shutdown_time}s, forcing exit"
            )
            sys.exit(1)
        except Exception as e:
            self.logger.log_error(f"Error during shutdown: {e}")
            sys.exit(1)
        
        # Exit cleanly
        sys.exit(0)
    
    async def _execute_callbacks(self):
        """Execute all registered shutdown callbacks."""
        self.logger.log_debug(
            f"Executing {len(self.shutdown_callbacks)} shutdown callbacks"
        )
        
        for callback in self.shutdown_callbacks:
            try:
                callback_name = callback.__name__
                self.logger.log_debug(f"Executing callback: {callback_name}")
                
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    await asyncio.get_event_loop().run_in_executor(
                        None, callback
                    )
                    
            except Exception as e:
                self.logger.log_error(
                    f"Error in shutdown callback {callback.__name__}: {e}"
                )
    
    async def _cleanup_resources(self):
        """Clean up tracked resources."""
        self.logger.log_debug("Cleaning up resources")
        
        # Close database connections
        for conn in self.resources["database_connections"]:
            try:
                if hasattr(conn, "close"):
                    if asyncio.iscoroutinefunction(conn.close):
                        await conn.close()
                    else:
                        conn.close()
            except Exception as e:
                self.logger.log_error(f"Error closing database connection: {e}")
        
        # Cancel active tasks
        for task in self.resources["active_tasks"]:
            try:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            except Exception as e:
                self.logger.log_error(f"Error cancelling task: {e}")
        
        # Disconnect voice connections
        for vc in self.resources["voice_connections"]:
            try:
                if hasattr(vc, "disconnect"):
                    await vc.disconnect(force=True)
            except Exception as e:
                self.logger.log_error(f"Error disconnecting voice: {e}")
        
        # Close file handles
        for fh in self.resources["file_handles"]:
            try:
                if hasattr(fh, "close"):
                    fh.close()
            except Exception as e:
                self.logger.log_error(f"Error closing file handle: {e}")
        
        self.logger.log_debug("Resource cleanup completed")
    
    async def _save_state(self):
        """Save current state for recovery."""
        try:
            import json
            from datetime import datetime
            
            state = {
                "shutdown_time": datetime.now().isoformat(),
                "reason": "graceful_shutdown",
                "active_users": [],  # Would be populated from bot
                "pending_tasks": [],  # Would be populated from queue
            }
            
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
            
            self.logger.log_debug(f"State saved to {self.state_file}")
            
        except Exception as e:
            self.logger.log_error(f"Failed to save state: {e}")
    
    def register_callback(self, callback: Callable):
        """
        Register a callback to be executed during shutdown.
        
        Args:
            callback: Function to call during shutdown
        """
        self.shutdown_callbacks.append(callback)
        self.logger.log_debug(
            f"Registered shutdown callback: {callback.__name__}"
        )
    
    def track_resource(self, resource_type: str, resource: Any):
        """
        Track a resource for cleanup.
        
        Args:
            resource_type: Type of resource
            resource: The resource object
        """
        if resource_type in self.resources:
            self.resources[resource_type].append(resource)
        else:
            self.logger.log_warning(
                f"Unknown resource type: {resource_type}"
            )
    
    def untrack_resource(self, resource_type: str, resource: Any):
        """
        Remove a resource from tracking.
        
        Args:
            resource_type: Type of resource
            resource: The resource object
        """
        if resource_type in self.resources:
            try:
                self.resources[resource_type].remove(resource)
            except ValueError:
                pass
    
    async def wait_for_shutdown(self):
        """Wait for shutdown signal."""
        await self.shutdown_event.wait()
    
    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress."""
        return self.is_shutting_down

class EmergencyShutdown:
    """Emergency shutdown for critical failures."""
    
    @staticmethod
    def execute(reason: str, exit_code: int = 1):
        """
        Perform emergency shutdown.
        
        Args:
            reason: Reason for emergency shutdown
            exit_code: System exit code
        """
        logger = get_logger()
        
        logger.log_error(
            f"EMERGENCY SHUTDOWN: {reason}",
            context={"exit_code": exit_code}
        )
        
        # Try to save minimal state
        try:
            import json
            from datetime import datetime
            
            emergency_file = Path("data/emergency_shutdown.json")
            emergency_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(emergency_file, "w") as f:
                json.dump({
                    "time": datetime.now().isoformat(),
                    "reason": reason,
                    "exit_code": exit_code
                }, f)
        except:
            pass
        
        # Force exit
        sys.exit(exit_code)

# Global shutdown handler instance
_shutdown_handler = ShutdownHandler()

def get_shutdown_handler() -> ShutdownHandler:
    """Get global shutdown handler."""
    return _shutdown_handler

# Convenience functions
def register_shutdown_callback(callback: Callable):
    """Register a shutdown callback."""
    _shutdown_handler.register_callback(callback)

def track_resource(resource_type: str, resource: Any):
    """Track a resource for cleanup."""
    _shutdown_handler.track_resource(resource_type, resource)

async def graceful_shutdown(reason: str = "User requested"):
    """Trigger graceful shutdown."""
    await _shutdown_handler.shutdown(reason)