# =============================================================================
# SaydnayaBot - Base Service Module
# =============================================================================
# Abstract base classes and interfaces for all bot services. Provides
# standardized service lifecycle management, error handling, health checks,
# and dependency injection support.
#
# This module establishes the foundation for a professional service-oriented
# architecture with proper separation of concerns and maintainable code.
# =============================================================================

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TypeVar

from src.core.exceptions import (
    ServiceError,
    ServiceInitializationError,
)
from src.core.logger import get_logger


class ServiceStatus(Enum):
    """Service status enumeration."""

    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    SHUTTING_DOWN = "shutting_down"
    SHUTDOWN = "shutdown"


@dataclass
class HealthCheckResult:
    """Result of a service health check."""

    status: ServiceStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    response_time_ms: Optional[float] = None


@dataclass
class ServiceMetrics:
    """Service performance and operational metrics."""

    name: str
    status: ServiceStatus
    uptime_seconds: float = 0.0
    requests_total: int = 0
    requests_successful: int = 0
    requests_failed: int = 0
    last_error: Optional[str] = None
    last_error_timestamp: Optional[datetime] = None
    average_response_time_ms: float = 0.0
    memory_usage_mb: float = 0.0
    custom_metrics: Dict[str, Any] = field(default_factory=dict)


T = TypeVar("T", bound="BaseService")


class BaseService(ABC):
    """
    Abstract base class for all bot services.

    Provides standardized service lifecycle management, health monitoring,
    error handling, and metrics collection. All services should inherit
    from this class to ensure consistent behavior.

    Service Lifecycle:
    1. __init__ - Basic initialization
    2. initialize() - Async initialization with dependencies
    3. start() - Start service operations
    4. health_check() - Periodic health monitoring
    5. stop() - Graceful shutdown
    """

    def __init__(self, name: str, dependencies: Optional[List[str]] = None):
        """
        Initialize the base service.

        Args:
            name: Service name for identification and logging
            dependencies: List of service names this service depends on
        """
        self.name = name
        self.dependencies = dependencies or []
        self.status = ServiceStatus.UNINITIALIZED
        self.logger = get_logger()

        # Metrics and monitoring
        self.metrics = ServiceMetrics(name=name, status=self.status)
        self._start_time: Optional[datetime] = None
        self._health_check_interval = 60.0  # seconds
        self._health_check_task: Optional[asyncio.Task] = None

        # Error tracking
        self._recent_errors: List[Dict[str, Any]] = []
        self._max_recent_errors = 10

        # Configuration
        self._config: Dict[str, Any] = {}

        self.logger.log_initialization_step(
            self.name, "success", "Base service initialized"
        )

    @abstractmethod
    async def initialize(self, config: Dict[str, Any], **kwargs) -> None:
        """
        Initialize the service with configuration and dependencies.

        This method should be implemented by subclasses to perform async
        initialization such as connecting to external services, loading
        resources, or setting up internal state.

        Args:
            config: Service configuration dictionary
            **kwargs: Additional initialization parameters

        Raises:
            ServiceInitializationError: If initialization fails
        """
        pass

    @abstractmethod
    async def start(self) -> None:
        """
        Start the service operations.

        This method should be implemented by subclasses to begin active
        service operations. Should only be called after successful initialization.

        Raises:
            ServiceError: If service cannot be started
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """
        Stop the service operations gracefully.

        This method should be implemented by subclasses to perform cleanup
        and shutdown operations. Should handle partial shutdown gracefully.
        """
        pass

    @abstractmethod
    async def health_check(self) -> HealthCheckResult:
        """
        Perform a health check on the service.

        This method should be implemented by subclasses to check service
        health and return detailed status information.

        Returns:
            HealthCheckResult with current service status
        """
        pass

    async def initialize_base(self, config: Dict[str, Any], **kwargs) -> None:
        """
        Perform base initialization common to all services.

        Args:
            config: Service configuration
            **kwargs: Additional parameters
        """
        try:
            self.status = ServiceStatus.INITIALIZING
            self._config = config.copy()
            self._start_time = datetime.utcnow()

            self.logger.log_initialization_step(
                self.name, "in_progress", "Starting service initialization"
            )

            # Call subclass initialization
            await self.initialize(config, **kwargs)

            # Start health check monitoring if not in test mode
            if not config.get("test_mode", False):
                await self._start_health_monitoring()

            self.status = ServiceStatus.HEALTHY
            self.metrics.status = self.status

            self.logger.log_initialization_step(
                self.name, "success", "Service initialized successfully"
            )

        except Exception as e:
            self.status = ServiceStatus.UNHEALTHY
            self.metrics.status = self.status
            self._record_error("initialization_failed", str(e))

            self.logger.log_error(
                f"Service {self.name} initialization failed",
                exception=e,
                context={"service": self.name},
            )

            raise ServiceInitializationError(self.name, str(e)) from e

    async def start_base(self) -> None:
        """Perform base start operations common to all services."""
        try:
            if self.status != ServiceStatus.HEALTHY:
                raise ServiceError(
                    self.name,
                    "Cannot start service - not in healthy state",
                    error_code="INVALID_STATE",
                )

            self.logger.log_info(f"Starting service: {self.name}")

            await self.start()

            self.logger.log_info(f"Service started successfully: {self.name}")

        except Exception as e:
            self.status = ServiceStatus.UNHEALTHY
            self.metrics.status = self.status
            self._record_error("start_failed", str(e))

            self.logger.log_error(
                f"Service {self.name} start failed",
                exception=e,
                context={"service": self.name},
            )

            raise ServiceError(self.name, f"Failed to start: {str(e)}") from e

    async def stop_base(self) -> None:
        """Perform base stop operations common to all services."""
        try:
            self.status = ServiceStatus.SHUTTING_DOWN
            self.metrics.status = self.status

            self.logger.log_info(f"Stopping service: {self.name}")

            # Stop health monitoring
            if self._health_check_task and not self._health_check_task.done():
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass

            # Call subclass stop
            await self.stop()

            self.status = ServiceStatus.SHUTDOWN
            self.metrics.status = self.status

            self.logger.log_info(f"Service stopped: {self.name}")

        except Exception as e:
            self.status = ServiceStatus.UNHEALTHY
            self.metrics.status = self.status

            self.logger.log_error(
                f"Error stopping service {self.name}",
                exception=e,
                context={"service": self.name},
            )

            raise ServiceError(self.name, f"Failed to stop cleanly: {str(e)}") from e

    async def get_health_status(self) -> HealthCheckResult:
        """
        Get current health status of the service.

        Returns:
            Current health check result
        """
        try:
            start_time = datetime.utcnow()
            result = await self.health_check()
            end_time = datetime.utcnow()

            result.response_time_ms = (end_time - start_time).total_seconds() * 1000
            result.timestamp = end_time

            return result

        except Exception as e:
            self.logger.log_error(
                f"Health check failed for service {self.name}", exception=e
            )

            return HealthCheckResult(
                status=ServiceStatus.UNHEALTHY,
                message=f"Health check failed: {str(e)}",
                details={"error": str(e)},
            )

    def get_metrics(self) -> ServiceMetrics:
        """
        Get current service metrics.

        Returns:
            Current ServiceMetrics object
        """
        if self._start_time:
            self.metrics.uptime_seconds = (
                datetime.utcnow() - self._start_time
            ).total_seconds()

        return self.metrics

    def record_request(self, success: bool, response_time_ms: Optional[float] = None):
        """
        Record a service request for metrics.

        Args:
            success: Whether the request was successful
            response_time_ms: Response time in milliseconds
        """
        self.metrics.requests_total += 1

        if success:
            self.metrics.requests_successful += 1
        else:
            self.metrics.requests_failed += 1

        if response_time_ms is not None:
            # Update average response time (simple moving average)
            total_requests = self.metrics.requests_total
            current_avg = self.metrics.average_response_time_ms

            self.metrics.average_response_time_ms = (
                current_avg * (total_requests - 1) + response_time_ms
            ) / total_requests

    def _record_error(self, error_type: str, error_message: str):
        """Record an error for tracking and analysis."""
        error_record = {
            "type": error_type,
            "message": error_message,
            "timestamp": datetime.utcnow().isoformat(),
            "service": self.name,
        }

        self._recent_errors.append(error_record)

        # Keep only recent errors
        if len(self._recent_errors) > self._max_recent_errors:
            self._recent_errors = self._recent_errors[-self._max_recent_errors :]

        # Update metrics
        self.metrics.last_error = error_message
        self.metrics.last_error_timestamp = datetime.utcnow()

    async def _start_health_monitoring(self):
        """Start periodic health check monitoring."""

        async def health_monitor():
            while self.status not in [
                ServiceStatus.SHUTDOWN,
                ServiceStatus.SHUTTING_DOWN,
            ]:
                try:
                    await asyncio.sleep(self._health_check_interval)

                    if self.status in [
                        ServiceStatus.SHUTDOWN,
                        ServiceStatus.SHUTTING_DOWN,
                    ]:
                        break

                    health_result = await self.get_health_status()

                    # Update status based on health check
                    if health_result.status != self.status:
                        old_status = self.status
                        self.status = health_result.status
                        self.metrics.status = self.status

                        self.logger.log_system_event(
                            "service_status_change",
                            f"Service {self.name} status changed",
                            {
                                "old_status": old_status.value,
                                "new_status": self.status.value,
                                "health_message": health_result.message,
                            },
                        )

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.log_error(
                        f"Health monitoring error for service {self.name}", exception=e
                    )

        self._health_check_task = asyncio.create_task(health_monitor())

    def get_recent_errors(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent errors from this service.

        Args:
            limit: Maximum number of errors to return

        Returns:
            List of recent error records
        """
        return self._recent_errors[-limit:] if self._recent_errors else []

    def is_healthy(self) -> bool:
        """Check if service is in a healthy state."""
        return self.status in [ServiceStatus.HEALTHY, ServiceStatus.DEGRADED]

    def is_available(self) -> bool:
        """Check if service is available for requests."""
        return self.status in [ServiceStatus.HEALTHY, ServiceStatus.DEGRADED]

    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value for this service.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value
        """
        return self._config.get(key, default)

    def __str__(self) -> str:
        """String representation of the service."""
        return f"{self.name}({self.status.value})"

    def __repr__(self) -> str:
        """Detailed string representation of the service."""
        return (
            f"{self.__class__.__name__}("
            f"name='{self.name}', "
            f"status='{self.status.value}', "
            f"dependencies={self.dependencies}"
            f")"
        )
