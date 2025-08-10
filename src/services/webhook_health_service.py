"""
AzabBot - Webhook Health Check Service
======================================

This service provides automated health status reporting via Discord webhooks.
It monitors the bot's health metrics and sends hourly status reports with
color-coded embeds indicating the overall system health.

Features:
- Hourly automated health checks
- Color-coded status embeds (green/yellow/red)
- Comprehensive metrics reporting
- Service status monitoring
- Memory and performance tracking
- Error rate analysis
- Beautiful Discord embeds with bot thumbnail
"""

import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from enum import Enum

from src.services.base_service import BaseService, ServiceStatus, HealthCheckResult
from src.core.logger import BotLogger


class HealthStatus(Enum):
    """Overall health status levels."""
    HEALTHY = ("🟢 Healthy", 0x00FF00)  # Green
    WARNING = ("🟡 Warning", 0xFFFF00)  # Yellow
    CRITICAL = ("🔴 Critical", 0xFF0000)  # Red
    DEAD = ("💀 Dead", 0x000000)  # Black


class WebhookHealthService(BaseService):
    """
    Automated health check reporting via Discord webhooks.
    
    This service monitors the bot's health and sends periodic status
    reports to a Discord channel via webhook. The reports include
    comprehensive metrics, service status, and performance data.
    """
    
    def __init__(self):
        """Initialize the webhook health service."""
        super().__init__("WebhookHealthService")
        self.webhooks: List[Dict[str, str]] = []  # List of webhook configs
        self.check_interval: int = 3600  # Default 1 hour
        self.health_monitor = None
        self.bot_instance = None
        self.last_check: Optional[datetime] = None
        self.consecutive_failures: int = 0
        self.health_task: Optional[asyncio.Task] = None
        
    async def initialize(self, config: Dict[str, Any], **kwargs) -> None:
        """Initialize the service with configuration."""
        await super().initialize(config, **kwargs)
        
        # Check for multiple webhook configurations
        # Try new format first (HEALTH_WEBHOOK_URL_1, HEALTH_WEBHOOK_URL_2, etc.)
        webhook_found = False
        for i in range(1, 5):  # Support up to 4 webhooks
            webhook_url = config.get(f"HEALTH_WEBHOOK_URL_{i}")
            if webhook_url:
                webhook_config = {
                    "url": webhook_url,
                    "thread_id": config.get(f"HEALTH_THREAD_ID_{i}", ""),
                    "name": f"Webhook {i}"
                }
                self.webhooks.append(webhook_config)
                self.logger.log_info(f"Configured webhook {i}: {webhook_url[:50]}...")
                if webhook_config["thread_id"]:
                    self.logger.log_info(f"Thread ID {i}: {webhook_config['thread_id']}")
                webhook_found = True
        
        # Fallback to legacy format if no numbered webhooks found
        if not webhook_found:
            webhook_url = config.get("HEALTH_WEBHOOK_URL")
            if webhook_url:
                webhook_config = {
                    "url": webhook_url,
                    "thread_id": config.get("HEALTH_THREAD_ID", ""),
                    "name": "Primary Webhook"
                }
                self.webhooks.append(webhook_config)
                self.logger.log_info(f"Configured legacy webhook: {webhook_url[:50]}...")
                webhook_found = True
        
        if not webhook_found:
            self.logger.log_info("No health webhooks configured, service disabled")
            return
            
        # Get check interval (in hours, convert to seconds)
        interval_hours = config.get("HEALTH_CHECK_INTERVAL_HOURS", 1)
        if interval_hours:
            interval_hours = float(interval_hours)
        else:
            interval_hours = 1.0
        self.check_interval = int(interval_hours * 3600)
        self.logger.log_info(f"Check interval set to {interval_hours} hours ({self.check_interval} seconds)")
        
        # Don't resolve HealthMonitor here - it will be set later
        # to avoid circular dependency during initialization
        self.logger.log_info("Skipping HealthMonitor resolution during init (will be set later)")
        
        self.logger.log_info(
            f"Webhook health service initialized (interval: {interval_hours}h)",
            "🏥"
        )
        
    def set_bot_instance(self, bot):
        """Set reference to bot instance for avatar URL."""
        self.bot_instance = bot
    
    def set_health_monitor(self, health_monitor):
        """Set reference to health monitor service."""
        self.health_monitor = health_monitor
        self.logger.log_info("Health monitor set successfully")
        
    async def start_health_checks(self):
        """Start the periodic health check task."""
        if not self.webhooks:
            return
            
        # Cancel existing task if any
        if self.health_task and not self.health_task.done():
            self.health_task.cancel()
            
        # Start new health check task
        self.health_task = asyncio.create_task(self._health_check_loop())
        self.logger.log_info("Started hourly health check task", "⏰")
        
    async def stop_health_checks(self):
        """Stop the health check task."""
        if self.health_task and not self.health_task.done():
            self.health_task.cancel()
            try:
                await self.health_task
            except asyncio.CancelledError:
                pass
            self.logger.log_info("Stopped health check task")
            
    async def _health_check_loop(self):
        """Main loop for periodic health checks."""
        while True:
            try:
                # Wait for next check interval
                await asyncio.sleep(self.check_interval)
                
                # Perform health check
                await self.send_health_report()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.log_error(f"Error in health check loop: {e}")
                self.consecutive_failures += 1
                
                # If too many failures, increase interval
                if self.consecutive_failures > 3:
                    await asyncio.sleep(self.check_interval * 2)
                    
    async def send_health_report(self, force: bool = False) -> bool:
        """
        Send a health status report via webhook.
        
        Args:
            force: Send immediately regardless of interval
            
        Returns:
            Success status
        """
        try:
            # Check if we should send (unless forced)
            if not force and self.last_check:
                time_since = datetime.now() - self.last_check
                if time_since < timedelta(seconds=self.check_interval - 60):
                    return False
                    
            # Gather health metrics
            health_data = await self._gather_health_metrics()
            
            # Determine overall status
            overall_status = self._determine_health_status(health_data)
            
            # Build embed
            embed = self._build_health_embed(health_data, overall_status)
            
            # Send webhook
            success = await self._send_webhook(embed)
            
            if success:
                self.last_check = datetime.now()
                self.consecutive_failures = 0
                self.logger.log_info(
                    f"Health report sent: {overall_status.value[0]}",
                    "📊"
                )
            else:
                self.consecutive_failures += 1
                
            return success
            
        except Exception as e:
            self.logger.log_error(f"Failed to send health report: {e}")
            return False
            
    async def _gather_health_metrics(self) -> Dict[str, Any]:
        """Gather comprehensive health metrics."""
        metrics = {
            "timestamp": datetime.now(),
            "uptime": None,
            "services": {},
            "performance": {},
            "errors": {},
            "bot_stats": {}
        }
        
        try:
            # Get bot stats if available
            if self.bot_instance:
                metrics["bot_stats"] = {
                    "guilds": len(self.bot_instance.guilds),
                    "users": sum(g.member_count for g in self.bot_instance.guilds),
                    "latency": round(self.bot_instance.latency * 1000, 2),
                    "prisoners": len(getattr(self.bot_instance, "current_prisoners", set())),
                    "messages_seen": getattr(self.bot_instance.metrics, "messages_seen", 0),
                    "responses_generated": getattr(self.bot_instance.metrics, "responses_generated", 0)
                }
                
                # Calculate uptime
                if hasattr(self.bot_instance, "start_time"):
                    uptime = datetime.now() - self.bot_instance.start_time
                    metrics["uptime"] = str(uptime).split('.')[0]
                    
            # Get service health from health monitor
            if self.health_monitor:
                service_statuses = await self.health_monitor.get_all_service_status()
                for service_name, status in service_statuses.items():
                    metrics["services"][service_name] = {
                        "status": status.status.value,
                        "healthy": status.status == ServiceStatus.HEALTHY
                    }
                    
                # Get system metrics
                system_metrics = await self.health_monitor.get_system_metrics()
                metrics["performance"] = {
                    "cpu_percent": system_metrics.get("cpu_usage", 0),
                    "memory_percent": system_metrics.get("memory_usage", {}).get("percent", 0),
                    "memory_mb": system_metrics.get("memory_usage", {}).get("used_mb", 0)
                }
                
        except Exception as e:
            self.logger.log_error(f"Error gathering metrics: {e}")
            
        return metrics
        
    def _determine_health_status(self, health_data: Dict[str, Any]) -> HealthStatus:
        """Determine overall health status from metrics."""
        try:
            # Check if bot is dead (no stats)
            if not health_data["bot_stats"] or health_data["bot_stats"].get("guilds", 0) == 0:
                return HealthStatus.DEAD
                
            # Count unhealthy services
            unhealthy_count = sum(
                1 for s in health_data["services"].values()
                if not s.get("healthy", True)
            )
            
            # Check performance metrics
            cpu = health_data["performance"].get("cpu_percent", 0)
            memory = health_data["performance"].get("memory_percent", 0)
            
            # Determine status based on conditions
            if unhealthy_count >= 3 or cpu > 90 or memory > 90:
                return HealthStatus.CRITICAL
            elif unhealthy_count >= 1 or cpu > 70 or memory > 70:
                return HealthStatus.WARNING
            else:
                return HealthStatus.HEALTHY
                
        except Exception:
            return HealthStatus.WARNING
            
    def _build_health_embed(self, health_data: Dict[str, Any], status: HealthStatus) -> Dict[str, Any]:
        """Build Discord embed for health report."""
        status_text, color = status.value
        
        # Get stats
        bot_stats = health_data.get("bot_stats", {})
        perf = health_data.get("performance", {})
        services = health_data.get("services", {})
        
        # Create status indicators with emojis
        cpu_percent = perf.get('cpu_percent', 0)
        mem_percent = perf.get('memory_percent', 0)
        
        # CPU status bar
        cpu_bar = self._create_progress_bar(cpu_percent, 10)
        mem_bar = self._create_progress_bar(mem_percent, 10)
        
        # Service health summary
        healthy_services = sum(1 for s in services.values() if s.get("healthy", True))
        total_services = len(services)
        service_health_pct = (healthy_services / total_services * 100) if total_services > 0 else 100
        
        # Determine overall health emoji and message
        if status == HealthStatus.HEALTHY:
            status_emoji = "✅"
            status_msg = "All systems operational"
        elif status == HealthStatus.WARNING:
            status_emoji = "⚠️"
            status_msg = "Minor issues detected"
        elif status == HealthStatus.CRITICAL:
            status_emoji = "🔴"
            status_msg = "Critical issues require attention"
        else:
            status_emoji = "💀"
            status_msg = "System offline"
        
        embed = {
            "author": {
                "name": "AzabBot System Monitor",
                "icon_url": "https://github.com/trippixn963/AzabBot/raw/main/images/PFP.gif",
                "url": "https://github.com/trippixn963/AzabBot"
            },
            "title": f"{status_emoji} System Health Report",
            "description": f"**Status:** {status_msg}\n**Uptime:** {health_data.get('uptime', 'Unknown')}\n\n"
                          f"**Performance Overview:**\n"
                          f"CPU Usage: {cpu_bar} {cpu_percent:.1f}%\n"
                          f"Memory: {mem_bar} {mem_percent:.1f}%\n"
                          f"Services: {healthy_services}/{total_services} operational ({service_health_pct:.0f}%)",
            "color": color,
            "timestamp": datetime.now().isoformat(),
            "fields": []
        }
        
        # Add thumbnail for visual appeal
        if self.bot_instance and self.bot_instance.user and self.bot_instance.user.avatar:
            embed["thumbnail"] = {
                "url": str(self.bot_instance.user.avatar.url)
            }
        
        # Network Statistics
        if bot_stats:
            embed["fields"].append({
                "name": "📊 Network Statistics",
                "value": f"**Servers:** {bot_stats.get('guilds', 0)}\n"
                        f"**Users:** {bot_stats.get('users', 0):,}\n"
                        f"**Latency:** {bot_stats.get('latency', 0)}ms",
                "inline": True
            })
            
            # Activity Metrics
            embed["fields"].append({
                "name": "📈 Activity Metrics",
                "value": f"**Messages Processed:** {bot_stats.get('messages_seen', 0):,}\n"
                        f"**Responses Generated:** {bot_stats.get('responses_generated', 0):,}\n"
                        f"**Active Prisoners:** {bot_stats.get('prisoners', 0)}",
                "inline": True
            })
        
        # System Resources
        if perf:
            memory_mb = perf.get('memory_mb', 0)
            embed["fields"].append({
                "name": "💻 System Resources",
                "value": f"**CPU Load:** {cpu_percent:.1f}%\n"
                        f"**RAM Usage:** {mem_percent:.1f}%\n"
                        f"**Memory:** {memory_mb:.0f} MB",
                "inline": True
            })
        
        # Service Health Details (if any issues)
        if services and healthy_services < total_services:
            unhealthy = [name for name, info in services.items() if not info.get("healthy", True)]
            embed["fields"].append({
                "name": "⚠️ Service Issues",
                "value": "\n".join([f"❌ {name}" for name in unhealthy[:5]]),
                "inline": False
            })
        
        # Quick Stats Bar
        embed["fields"].append({
            "name": "📊 Quick Stats",
            "value": f"```\n"
                    f"Uptime    : {health_data.get('uptime', 'N/A')}\n"
                    f"Health    : {status_text.split()[1]}\n"
                    f"Next Check: {self.check_interval // 3600}h\n"
                    f"```",
            "inline": False
        })
        
        # Professional footer
        embed["footer"] = {
            "text": f"AzabBot v1.5.0 • Health Monitor • Report #{self.consecutive_failures + 1}",
            "icon_url": "https://cdn.discordapp.com/emojis/1058387875436941402.webp?size=96&quality=lossless"  # Health icon
        }
        
        return embed
    
    def _create_progress_bar(self, percentage: float, length: int = 10) -> str:
        """Create a visual progress bar using emojis."""
        filled = int((percentage / 100) * length)
        
        # Color based on percentage
        if percentage < 50:
            fill_char = "🟩"
        elif percentage < 75:
            fill_char = "🟨"
        else:
            fill_char = "🟥"
        
        empty_char = "⬜"
        
        bar = fill_char * filled + empty_char * (length - filled)
        return bar
        
    async def _send_webhook(self, embed: Dict[str, Any]) -> bool:
        """Send embed via Discord webhooks to all configured destinations."""
        if not self.webhooks:
            self.logger.log_error("No webhooks configured")
            return False
            
        payload = {
            "username": "AzabBot Health Monitor",
            "avatar_url": "https://github.com/trippixn963/AzabBot/raw/main/images/PFP.gif",
            "embeds": [embed]
        }
        
        success_count = 0
        total_webhooks = len(self.webhooks)
        
        # Send to all configured webhooks
        for webhook_config in self.webhooks:
            webhook_url = webhook_config["url"]
            thread_id = webhook_config.get("thread_id", "")
            webhook_name = webhook_config.get("name", "Unknown")
            
            # Add thread_id parameter for forum channel if configured
            if thread_id:
                webhook_url = f"{webhook_url}?thread_id={thread_id}"
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        webhook_url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        if response.status in (200, 204):
                            self.logger.log_info(f"Health webhook sent successfully to {webhook_name}")
                            success_count += 1
                        else:
                            response_text = await response.text()
                            self.logger.log_error(
                                f"Webhook {webhook_name} failed with status {response.status}: {response_text[:200]}"
                            )
                        
            except aiohttp.ClientError as e:
                self.logger.log_error(f"Webhook {webhook_name} connection error: {e}")
            except Exception as e:
                self.logger.log_error(f"Unexpected error for {webhook_name}: {type(e).__name__}: {e}")
        
        # Return true if at least one webhook succeeded
        if success_count > 0:
            self.logger.log_info(f"Health report sent to {success_count}/{total_webhooks} webhooks")
            return True
        else:
            self.logger.log_error(f"Failed to send health report to any webhook (0/{total_webhooks})")
            return False
            
    async def perform_health_check(self) -> Dict[str, Any]:
        """Perform health check for this service."""
        return {
            "healthy": len(self.webhooks) > 0,
            "webhooks_configured": len(self.webhooks),
            "webhook_names": [w.get("name", "Unknown") for w in self.webhooks],
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "consecutive_failures": self.consecutive_failures,
            "task_running": self.health_task and not self.health_task.done()
        }
    
    async def health_check(self) -> HealthCheckResult:
        """Required health check method from BaseService."""
        from src.services.base_service import HealthCheckResult, ServiceStatus
        
        if not self.webhooks:
            return HealthCheckResult(
                status=ServiceStatus.DEGRADED,
                message="No webhooks configured",
                details={"configured": 0}
            )
            
        return HealthCheckResult(
            status=ServiceStatus.HEALTHY,
            message=f"Webhook health service operational with {len(self.webhooks)} webhook(s)",
            details=await self.perform_health_check()
        )
    
    async def start(self) -> None:
        """Start the service."""
        await self.start_health_checks()
        
    async def stop(self) -> None:
        """Stop the service."""
        await self.stop_health_checks()