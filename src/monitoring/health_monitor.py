# =============================================================================
# SaydnayaBot - Health Monitoring System
# =============================================================================
# Comprehensive health monitoring and alerting system for all bot services.
# Provides real-time health checks, performance monitoring, and automated
# recovery mechanisms.
#
# This module ensures system reliability through proactive monitoring and
# automated responses to service degradation or failures.
# =============================================================================

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

import psutil

from src.services.base_service import BaseService, HealthCheckResult, ServiceStatus


class AlertSeverity(Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class HealthAlert:
    """Health monitoring alert."""

    id: str
    timestamp: datetime
    severity: AlertSeverity
    service_name: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    resolved: bool = False
    resolution_time: Optional[datetime] = None


@dataclass
class SystemMetrics:
    """System performance metrics."""

    timestamp: datetime
    cpu_usage_percent: float
    memory_usage_mb: float
    memory_usage_percent: float
    disk_usage_percent: float
    network_bytes_sent: int
    network_bytes_recv: int
    active_connections: int
    uptime_seconds: float


class HealthMonitor(BaseService):
    """
    Comprehensive health monitoring system.

    Features:
    - Service health monitoring with configurable intervals
    - System resource monitoring (CPU, memory, disk, network)
    - Alert generation and management
    - Automated recovery actions
    - Performance trend analysis
    - Health status reporting and dashboards
    """

    def __init__(self, name: str = "HealthMonitor"):
        """Initialize the health monitor."""
        super().__init__(name)

        # Monitoring configuration
        self.check_interval = 30.0  # seconds
        self.system_metrics_interval = 60.0  # seconds

        # Services to monitor
        self.monitored_services: Dict[str, BaseService] = {}

        # Health check results history
        self.health_history: Dict[str, List[HealthCheckResult]] = {}
        self.max_history_length = 100

        # System metrics history
        self.system_metrics_history: List[SystemMetrics] = []
        self.max_metrics_history = 1440  # 24 hours at 1-minute intervals

        # Active alerts
        self.active_alerts: Dict[str, HealthAlert] = {}
        self.alert_history: List[HealthAlert] = []
        self.max_alert_history = 1000

        # Recovery actions
        self.recovery_actions: Dict[
            str, Callable[[str, HealthCheckResult], Awaitable[bool]]
        ] = {}

        # Monitoring tasks
        self.monitoring_task: Optional[asyncio.Task] = None
        self.metrics_task: Optional[asyncio.Task] = None

        # Performance tracking
        self.start_time = datetime.utcnow()
        self.last_system_check = datetime.utcnow()

        # Alert callbacks
        self.alert_callbacks: List[Callable[[HealthAlert], Awaitable[None]]] = []

    async def initialize(self, config: Dict[str, Any], **kwargs) -> None:
        """Initialize the health monitor."""
        self.check_interval = config.get("health_check_interval", 30.0)
        self.system_metrics_interval = config.get("metrics_interval", 60.0)

        # Initialize system metrics baseline
        await self._collect_system_metrics()

        self.logger.log_info("Health monitor initialized")

    async def start(self) -> None:
        """Start health monitoring."""
        # Start monitoring tasks
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        self.metrics_task = asyncio.create_task(self._metrics_collection_loop())

        self.logger.log_info("Health monitoring started")

    async def stop(self) -> None:
        """Stop health monitoring."""
        # Cancel monitoring tasks
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass

        if self.metrics_task:
            self.metrics_task.cancel()
            try:
                await self.metrics_task
            except asyncio.CancelledError:
                pass

        self.logger.log_info("Health monitoring stopped")

    async def health_check(self) -> HealthCheckResult:
        """Perform health check on the monitor itself."""
        try:
            # Check if monitoring is active
            is_monitoring_active = (
                self.monitoring_task and not self.monitoring_task.done()
            )

            is_metrics_active = self.metrics_task and not self.metrics_task.done()

            if not is_monitoring_active or not is_metrics_active:
                return HealthCheckResult(
                    status=ServiceStatus.DEGRADED,
                    message="Some monitoring tasks are not active",
                    details={
                        "monitoring_active": is_monitoring_active,
                        "metrics_active": is_metrics_active,
                    },
                )

            # Get current system load
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()

            # Check system health
            if cpu_percent > 90 or memory.percent > 95:
                return HealthCheckResult(
                    status=ServiceStatus.DEGRADED,
                    message="System resources under high load",
                    details={
                        "cpu_percent": cpu_percent,
                        "memory_percent": memory.percent,
                    },
                )

            return HealthCheckResult(
                status=ServiceStatus.HEALTHY,
                message="Health monitor operational",
                details={
                    "monitored_services": len(self.monitored_services),
                    "active_alerts": len(self.active_alerts),
                    "monitoring_active": is_monitoring_active,
                    "metrics_active": is_metrics_active,
                },
            )

        except Exception as e:
            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message=f"Health monitor check failed: {str(e)}",
                details={"error": str(e)},
            )

    def register_service(self, service: BaseService):
        """
        Register a service for monitoring.

        Args:
            service: Service to monitor
        """
        self.monitored_services[service.name] = service
        self.health_history[service.name] = []

        self.logger.log_info(f"Registered service for monitoring: {service.name}")

    def unregister_service(self, service_name: str):
        """
        Unregister a service from monitoring.

        Args:
            service_name: Name of service to unregister
        """
        if service_name in self.monitored_services:
            del self.monitored_services[service_name]
            self.health_history.pop(service_name, None)

            self.logger.log_info(
                f"Unregistered service from monitoring: {service_name}"
            )

    def register_recovery_action(
        self,
        service_name: str,
        action: Callable[[str, HealthCheckResult], Awaitable[bool]],
    ):
        """
        Register a recovery action for a service.

        Args:
            service_name: Name of the service
            action: Async callable that attempts recovery
        """
        self.recovery_actions[service_name] = action
        self.logger.log_info(f"Registered recovery action for: {service_name}")

    def register_alert_callback(
        self, callback: Callable[[HealthAlert], Awaitable[None]]
    ):
        """
        Register a callback for alert notifications.

        Args:
            callback: Async callable that handles alerts
        """
        self.alert_callbacks.append(callback)
        self.logger.log_info("Registered alert callback")

    async def _monitoring_loop(self):
        """Main monitoring loop."""
        while True:
            try:
                await asyncio.sleep(self.check_interval)
                await self._check_all_services()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.log_error("Error in monitoring loop", exception=e)
                await asyncio.sleep(self.check_interval)

    async def _metrics_collection_loop(self):
        """System metrics collection loop."""
        while True:
            try:
                await asyncio.sleep(self.system_metrics_interval)
                await self._collect_system_metrics()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.log_error("Error in metrics collection", exception=e)
                await asyncio.sleep(self.system_metrics_interval)

    async def _check_all_services(self):
        """Check health of all monitored services."""
        for service_name, service in self.monitored_services.items():
            try:
                health_result = await service.get_health_status()

                # Store health result
                self._store_health_result(service_name, health_result)

                # Check for status changes
                await self._analyze_health_change(service_name, health_result)

                # Attempt recovery if needed
                if health_result.status in [
                    ServiceStatus.UNHEALTHY,
                    ServiceStatus.DEGRADED,
                ]:
                    await self._attempt_recovery(service_name, health_result)

            except Exception as e:
                self.logger.log_error(
                    f"Error checking health of service {service_name}", exception=e
                )

                # Create error health result
                error_result = HealthCheckResult(
                    status=ServiceStatus.UNHEALTHY,
                    message=f"Health check failed: {str(e)}",
                    details={"error": str(e)},
                )

                self._store_health_result(service_name, error_result)
                await self._create_alert(
                    service_name,
                    AlertSeverity.CRITICAL,
                    f"Health check failed for {service_name}: {str(e)}",
                )

    async def _collect_system_metrics(self):
        """Collect system performance metrics."""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)

            # Memory usage
            memory = psutil.virtual_memory()
            memory_usage_mb = (memory.total - memory.available) / 1024 / 1024

            # Disk usage
            disk = psutil.disk_usage("/")
            disk_percent = (disk.used / disk.total) * 100

            # Network statistics
            network = psutil.net_io_counters()

            # System uptime
            uptime = time.time() - psutil.boot_time()

            # Active network connections
            connections = len(psutil.net_connections())

            metrics = SystemMetrics(
                timestamp=datetime.utcnow(),
                cpu_usage_percent=cpu_percent,
                memory_usage_mb=memory_usage_mb,
                memory_usage_percent=memory.percent,
                disk_usage_percent=disk_percent,
                network_bytes_sent=network.bytes_sent,
                network_bytes_recv=network.bytes_recv,
                active_connections=connections,
                uptime_seconds=uptime,
            )

            # Store metrics
            self.system_metrics_history.append(metrics)

            # Keep only recent metrics
            if len(self.system_metrics_history) > self.max_metrics_history:
                self.system_metrics_history = self.system_metrics_history[
                    -self.max_metrics_history :
                ]

            # Check for resource alerts
            await self._check_resource_alerts(metrics)

        except Exception as e:
            self.logger.log_error("Error collecting system metrics", exception=e)

    def _store_health_result(self, service_name: str, result: HealthCheckResult):
        """Store health check result in history."""
        if service_name not in self.health_history:
            self.health_history[service_name] = []

        self.health_history[service_name].append(result)

        # Keep only recent history
        if len(self.health_history[service_name]) > self.max_history_length:
            self.health_history[service_name] = self.health_history[service_name][
                -self.max_history_length :
            ]

    async def _analyze_health_change(
        self, service_name: str, current_result: HealthCheckResult
    ):
        """Analyze health status changes and generate alerts."""
        history = self.health_history.get(service_name, [])

        if len(history) < 2:
            return

        previous_result = history[-2]
        current_status = current_result.status
        previous_status = previous_result.status

        # Status changed
        if current_status != previous_status:
            severity = self._determine_alert_severity(previous_status, current_status)

            if severity:
                await self._create_alert(
                    service_name,
                    severity,
                    f"Service status changed from {previous_status.value} to {current_status.value}",
                    details=current_result.details,
                )

        # Check for persistent unhealthy status
        elif current_status == ServiceStatus.UNHEALTHY:
            unhealthy_count = 0
            for result in reversed(history[-5:]):  # Check last 5 results
                if result.status == ServiceStatus.UNHEALTHY:
                    unhealthy_count += 1
                else:
                    break

            if unhealthy_count >= 3:  # Unhealthy for 3+ consecutive checks
                await self._create_alert(
                    service_name,
                    AlertSeverity.CRITICAL,
                    f"Service has been unhealthy for {unhealthy_count} consecutive checks",
                    details={"consecutive_failures": unhealthy_count},
                )

    def _determine_alert_severity(
        self, previous_status: ServiceStatus, current_status: ServiceStatus
    ) -> Optional[AlertSeverity]:
        """Determine alert severity based on status transition."""
        # Status improvements (less severe or informational)
        if previous_status == ServiceStatus.UNHEALTHY and current_status in [
            ServiceStatus.HEALTHY,
            ServiceStatus.DEGRADED,
        ]:
            return AlertSeverity.INFO

        if (
            previous_status == ServiceStatus.DEGRADED
            and current_status == ServiceStatus.HEALTHY
        ):
            return AlertSeverity.INFO

        # Status degradations (more severe)
        if (
            previous_status == ServiceStatus.HEALTHY
            and current_status == ServiceStatus.DEGRADED
        ):
            return AlertSeverity.WARNING

        if (
            previous_status in [ServiceStatus.HEALTHY, ServiceStatus.DEGRADED]
            and current_status == ServiceStatus.UNHEALTHY
        ):
            return AlertSeverity.CRITICAL

        if current_status == ServiceStatus.SHUTDOWN:
            return AlertSeverity.WARNING

        return None

    async def _check_resource_alerts(self, metrics: SystemMetrics):
        """Check system resource usage and generate alerts if needed."""
        # CPU usage alerts
        if metrics.cpu_usage_percent > 90:
            await self._create_alert(
                "system",
                AlertSeverity.CRITICAL,
                f"High CPU usage: {metrics.cpu_usage_percent:.1f}%",
                details={"cpu_percent": metrics.cpu_usage_percent},
            )
        elif metrics.cpu_usage_percent > 75:
            await self._create_alert(
                "system",
                AlertSeverity.WARNING,
                f"Elevated CPU usage: {metrics.cpu_usage_percent:.1f}%",
                details={"cpu_percent": metrics.cpu_usage_percent},
            )

        # Memory usage alerts
        if metrics.memory_usage_percent > 95:
            await self._create_alert(
                "system",
                AlertSeverity.CRITICAL,
                f"High memory usage: {metrics.memory_usage_percent:.1f}%",
                details={
                    "memory_percent": metrics.memory_usage_percent,
                    "memory_mb": metrics.memory_usage_mb,
                },
            )
        elif metrics.memory_usage_percent > 85:
            await self._create_alert(
                "system",
                AlertSeverity.WARNING,
                f"Elevated memory usage: {metrics.memory_usage_percent:.1f}%",
                details={
                    "memory_percent": metrics.memory_usage_percent,
                    "memory_mb": metrics.memory_usage_mb,
                },
            )

        # Disk usage alerts
        if metrics.disk_usage_percent > 95:
            await self._create_alert(
                "system",
                AlertSeverity.CRITICAL,
                f"High disk usage: {metrics.disk_usage_percent:.1f}%",
                details={"disk_percent": metrics.disk_usage_percent},
            )
        elif metrics.disk_usage_percent > 85:
            await self._create_alert(
                "system",
                AlertSeverity.WARNING,
                f"Elevated disk usage: {metrics.disk_usage_percent:.1f}%",
                details={"disk_percent": metrics.disk_usage_percent},
            )

    async def _attempt_recovery(
        self, service_name: str, health_result: HealthCheckResult
    ):
        """Attempt automated recovery for a failing service."""
        if service_name not in self.recovery_actions:
            return

        try:
            recovery_action = self.recovery_actions[service_name]
            success = await recovery_action(service_name, health_result)

            if success:
                await self._create_alert(
                    service_name,
                    AlertSeverity.INFO,
                    f"Automated recovery successful for {service_name}",
                    details={"recovery_attempted": True, "recovery_successful": True},
                )
            else:
                await self._create_alert(
                    service_name,
                    AlertSeverity.WARNING,
                    f"Automated recovery failed for {service_name}",
                    details={"recovery_attempted": True, "recovery_successful": False},
                )

        except Exception as e:
            self.logger.log_error(
                f"Error during recovery attempt for {service_name}", exception=e
            )

            await self._create_alert(
                service_name,
                AlertSeverity.CRITICAL,
                f"Recovery action failed for {service_name}: {str(e)}",
                details={"recovery_error": str(e)},
            )

    async def _create_alert(
        self,
        service_name: str,
        severity: AlertSeverity,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Create and process a new alert."""
        alert_id = f"{service_name}_{int(time.time())}_{severity.value}"

        alert = HealthAlert(
            id=alert_id,
            timestamp=datetime.utcnow(),
            severity=severity,
            service_name=service_name,
            message=message,
            details=details or {},
        )

        # Store alert
        self.active_alerts[alert_id] = alert
        self.alert_history.append(alert)

        # Keep alert history manageable
        if len(self.alert_history) > self.max_alert_history:
            self.alert_history = self.alert_history[-self.max_alert_history :]

        # Log alert
        self.logger.log_system_event(
            "health_alert",
            f"{severity.value.upper()}: {message}",
            {
                "service": service_name,
                "severity": severity.value,
                "alert_id": alert_id,
                "details": details or {},
            },
        )

        # Notify callbacks
        for callback in self.alert_callbacks:
            try:
                await callback(alert)
            except Exception as e:
                self.logger.log_error("Error in alert callback", exception=e)

    def get_health_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive health summary.

        Returns:
            Health summary dictionary
        """
        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "services": {},
            "system_metrics": None,
            "active_alerts": len(self.active_alerts),
            "total_monitored_services": len(self.monitored_services),
        }

        # Service statuses
        unhealthy_count = 0
        degraded_count = 0

        for service_name, service in self.monitored_services.items():
            status = service.status
            summary["services"][service_name] = {
                "status": status.value,
                "is_healthy": service.is_healthy(),
                "uptime": service.get_metrics().uptime_seconds,
            }

            if status == ServiceStatus.UNHEALTHY:
                unhealthy_count += 1
            elif status == ServiceStatus.DEGRADED:
                degraded_count += 1

        # Determine overall status
        if unhealthy_count > 0:
            summary["overall_status"] = "unhealthy"
        elif degraded_count > 0:
            summary["overall_status"] = "degraded"

        # Current system metrics
        if self.system_metrics_history:
            latest_metrics = self.system_metrics_history[-1]
            summary["system_metrics"] = {
                "cpu_percent": latest_metrics.cpu_usage_percent,
                "memory_percent": latest_metrics.memory_usage_percent,
                "disk_percent": latest_metrics.disk_usage_percent,
                "uptime_hours": latest_metrics.uptime_seconds / 3600,
                "active_connections": latest_metrics.active_connections,
            }

        return summary

    def get_service_history(
        self, service_name: str, hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Get health history for a specific service.

        Args:
            service_name: Name of the service
            hours: Number of hours of history to return

        Returns:
            List of health check results
        """
        if service_name not in self.health_history:
            return []

        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        history = self.health_history[service_name]

        recent_history = [
            {
                "timestamp": result.timestamp.isoformat(),
                "status": result.status.value,
                "message": result.message,
                "response_time_ms": result.response_time_ms,
                "details": result.details,
            }
            for result in history
            if result.timestamp > cutoff_time
        ]

        return recent_history

    def get_active_alerts(
        self, severity: Optional[AlertSeverity] = None
    ) -> List[HealthAlert]:
        """
        Get active alerts, optionally filtered by severity.

        Args:
            severity: Filter by alert severity

        Returns:
            List of active alerts
        """
        alerts = list(self.active_alerts.values())

        if severity:
            alerts = [alert for alert in alerts if alert.severity == severity]

        return sorted(alerts, key=lambda a: a.timestamp, reverse=True)

    async def acknowledge_alert(self, alert_id: str) -> bool:
        """
        Acknowledge an alert.

        Args:
            alert_id: ID of the alert to acknowledge

        Returns:
            True if alert was acknowledged
        """
        if alert_id in self.active_alerts:
            self.active_alerts[alert_id].acknowledged = True
            self.logger.log_info(f"Alert acknowledged: {alert_id}")
            return True

        return False

    async def resolve_alert(self, alert_id: str) -> bool:
        """
        Mark an alert as resolved.

        Args:
            alert_id: ID of the alert to resolve

        Returns:
            True if alert was resolved
        """
        if alert_id in self.active_alerts:
            alert = self.active_alerts[alert_id]
            alert.resolved = True
            alert.resolution_time = datetime.utcnow()

            # Remove from active alerts
            del self.active_alerts[alert_id]

            self.logger.log_info(f"Alert resolved: {alert_id}")
            return True

        return False
