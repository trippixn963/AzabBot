"""
Dashboard Integration Service for AzabBot
==========================================

Connects AzabBot to the multi-bot dashboard.
"""

import asyncio
import psutil
from typing import Dict, Any, Optional
from datetime import datetime
import os

# Import the dashboard client (this would normally be installed via pip)
import sys
from pathlib import Path
dashboard_client_path = Path(__file__).parent.parent.parent.parent / "BotDashboard" / "bot_dashboard_client"
sys.path.insert(0, str(dashboard_client_path))

# from client import DashboardClient, BotStatus  # TODO: Implement dashboard client
# Temporary mock classes
class DashboardClient:
    def __init__(self, *args, **kwargs):
        pass
    async def connect(self):
        pass
    async def update_status(self, *args):
        pass
    async def close(self):
        pass

class BotStatus:
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"
from src.core.logger import get_logger


class DashboardService:
    """Service for dashboard integration."""
    
    def __init__(self, bot_instance):
        """
        Initialize dashboard service.
        
        Args:
            bot_instance: The AzabBot instance
        """
        self.bot = bot_instance
        self.logger = get_logger()
        
        # Dashboard configuration
        self.dashboard_url = os.getenv("DASHBOARD_URL", "http://localhost:8000")
        self.dashboard_api_key = os.getenv("DASHBOARD_API_KEY", "azabbot-api-key")
        
        # Create dashboard client
        self.client = DashboardClient(
            bot_name="AzabBot",
            api_url=self.dashboard_url,
            api_key=self.dashboard_api_key,
            auto_heartbeat=True,
            heartbeat_interval=30
        )
        
        # Override metrics collection
        self.client._collect_metrics = self._collect_bot_metrics
        
        # Register command handlers
        self._register_commands()
        
        self.connected = False
    
    async def start(self):
        """Start dashboard connection."""
        try:
            # Connect to dashboard
            success = await self.client.connect()
            if success:
                self.connected = True
                self.logger.log_info("📊 Connected to dashboard")
                
                # Send initial status
                await self.client.update_status(BotStatus.ONLINE)
                
                # Send initial metrics
                await self._send_initial_metrics()
            else:
                self.logger.log_warning("Failed to connect to dashboard")
                
        except Exception as e:
            self.logger.log_error(f"Dashboard connection error: {e}")
    
    async def stop(self):
        """Stop dashboard connection."""
        if self.connected:
            await self.client.update_status(BotStatus.OFFLINE)
            await self.client.disconnect()
            self.connected = False
            self.logger.log_info("📊 Disconnected from dashboard")
    
    async def _collect_bot_metrics(self) -> Dict[str, Any]:
        """Collect current bot metrics."""
        metrics = {}
        
        try:
            # System metrics
            process = psutil.Process()
            metrics["cpu"] = {
                "value": process.cpu_percent(),
                "unit": "%"
            }
            metrics["memory"] = {
                "value": process.memory_info().rss / 1024 / 1024,
                "unit": "MB"
            }
            
            # Discord metrics
            if self.bot.user:
                metrics["guilds"] = {
                    "value": len(self.bot.guilds),
                    "unit": "count"
                }
                
                total_users = sum(guild.member_count for guild in self.bot.guilds)
                metrics["users"] = {
                    "value": total_users,
                    "unit": "count"
                }
                
                # Voice connections
                voice_connections = len(self.bot.voice_clients) if hasattr(self.bot, "voice_clients") else 0
                metrics["voice_connections"] = {
                    "value": voice_connections,
                    "unit": "count"
                }
            
            # Bot-specific metrics
            if hasattr(self.bot, "database_service"):
                db_service = self.bot.database_service
                if hasattr(db_service, "get_prisoner_count"):
                    prisoner_count = await db_service.get_prisoner_count()
                    metrics["prisoners"] = {
                        "value": prisoner_count,
                        "unit": "count"
                    }
            
            # Response metrics
            if hasattr(self.bot, "response_count"):
                metrics["responses_today"] = {
                    "value": self.bot.response_count,
                    "unit": "count"
                }
            
            # Uptime
            if hasattr(self.bot, "start_time"):
                uptime = (datetime.utcnow() - self.bot.start_time).total_seconds()
                metrics["uptime"] = {
                    "value": uptime,
                    "unit": "seconds"
                }
            
        except Exception as e:
            self.logger.log_error(f"Error collecting metrics: {e}")
        
        return metrics
    
    async def _send_initial_metrics(self):
        """Send initial metrics after connection."""
        try:
            # Bot information
            await self.client.send_metric(
                "bot_version",
                0,
                metadata={"version": "3.0.0"}
            )
            
            # Features
            features = [
                "torture_system",
                "ai_responses",
                "prison_mode",
                "psychological_profiling",
                "memory_system"
            ]
            await self.client.send_metric(
                "features",
                len(features),
                metadata={"features": features}
            )
            
            # Flush metrics
            await self.client.flush_metrics()
            
        except Exception as e:
            self.logger.log_error(f"Error sending initial metrics: {e}")
    
    def _register_commands(self):
        """Register dashboard command handlers."""
        
        @self.client.command("restart")
        async def restart_bot(params: Dict[str, Any]):
            """Restart the bot."""
            self.logger.log_warning("Restart requested from dashboard")
            await self.client.update_status(BotStatus.STOPPING)
            
            # Schedule restart
            asyncio.create_task(self._restart_bot())
            return {"message": "Restarting bot..."}
        
        @self.client.command("status")
        async def get_status(params: Dict[str, Any]):
            """Get bot status."""
            return {
                "online": True,
                "guilds": len(self.bot.guilds),
                "users": sum(g.member_count for g in self.bot.guilds),
                "uptime": (datetime.utcnow() - self.bot.start_time).total_seconds() if hasattr(self.bot, "start_time") else 0
            }
        
        @self.client.command("reload_config")
        async def reload_config(params: Dict[str, Any]):
            """Reload bot configuration."""
            try:
                if hasattr(self.bot, "reload_config"):
                    await self.bot.reload_config()
                    return {"success": True, "message": "Configuration reloaded"}
                else:
                    return {"success": False, "message": "Reload not supported"}
            except Exception as e:
                return {"success": False, "message": str(e)}
        
        @self.client.command("clear_cache")
        async def clear_cache(params: Dict[str, Any]):
            """Clear bot caches."""
            try:
                # Clear various caches
                cleared = 0
                
                if hasattr(self.bot, "_cache_manager"):
                    for cache in self.bot._cache_manager.caches.values():
                        await cache.clear()
                    cleared += 1
                
                return {"success": True, "caches_cleared": cleared}
            except Exception as e:
                return {"success": False, "message": str(e)}
        
        @self.client.command("backup_database")
        async def backup_database(params: Dict[str, Any]):
            """Trigger database backup."""
            try:
                if hasattr(self.bot, "backup_manager"):
                    backup_path = await self.bot.backup_manager.create_backup("dashboard_request")
                    return {
                        "success": True,
                        "backup_path": str(backup_path) if backup_path else None
                    }
                return {"success": False, "message": "Backup manager not available"}
            except Exception as e:
                return {"success": False, "message": str(e)}
    
    async def _restart_bot(self):
        """Restart the bot process."""
        await asyncio.sleep(2)  # Give time for response
        
        # Close bot
        await self.bot.close()
        
        # Exit process (systemd or docker will restart it)
        import sys
        sys.exit(0)
    
    # Logging integration
    
    async def log_event(self, level: str, message: str, context: Dict = None):
        """Send log event to dashboard."""
        if self.connected:
            await self.client.log(level, message, "AzabBot", context)
    
    async def log_command_usage(self, command_name: str, user_id: int, guild_id: int = None, success: bool = True):
        """Log command usage to dashboard."""
        if self.connected:
            await self.client.log_command(
                command_name,
                str(user_id),
                str(guild_id) if guild_id else None,
                success
            )
    
    async def send_alert(self, alert_type: str, message: str, severity: str = "warning"):
        """Send alert to dashboard."""
        if self.connected:
            await self.client.log(
                severity.upper(),
                f"[ALERT] {alert_type}: {message}",
                "alerts"
            )