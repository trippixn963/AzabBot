"""
AzabBot - Dependency Injection Container
============================================

This module provides a professional dependency injection system for managing
service registration, resolution, lifecycle management, and circular dependency
detection throughout the AzabBot application.

The DI container implements a comprehensive service management system that
handles service instantiation, dependency resolution, and service lifecycle
in a clean, testable, and maintainable way. It supports multiple service
lifetime modes and provides robust error handling and monitoring.

Key Features:
- Service registration with multiple lifetime modes (singleton, transient, scoped)
- Automatic dependency resolution with circular dependency detection
- Service lifecycle management (initialization, startup, shutdown)
- Factory function support for complex service creation
- Configuration injection and management
- Health monitoring integration
- Thread-safe service resolution
- Startup order calculation and dependency graph management

The container manages the entire service lifecycle from registration through
instantiation, initialization, and cleanup, ensuring proper resource management
and service coordination.
"""

import asyncio
import inspect
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Type, TypeVar

from src.core.exceptions import ServiceError, ServiceInitializationError
from src.core.logger import get_logger
from src.services.base_service import BaseService


class ServiceNotFoundError(ServiceError):
    """
    Raised when a requested service is not found in the container.
    
    This exception is thrown when attempting to resolve a service that
    has not been registered with the DI container.
    """

    pass


class CircularDependencyError(ServiceError):
    """
    Raised when a circular dependency is detected during service resolution.
    
    This exception is thrown when the dependency resolution process detects
    a circular reference between services, which would cause infinite recursion.
    """

    pass


class ServiceLifetime(Enum):
    """
    Service lifetime management modes for dependency injection.
    
    Defines how service instances are managed and reused throughout
    the application lifecycle.
    """

    SINGLETON = "singleton"  # One instance for the entire application
    TRANSIENT = "transient"  # New instance for each request
    SCOPED = "scoped"  # One instance per scope (e.g., per request)


@dataclass
class ServiceRegistration:
    """
    Service registration information for the DI container.
    
    Contains all the information needed to register and resolve a service,
    including its type, implementation, factory function, lifetime, and
    dependencies.
    
    Attributes:
        service_type: The service interface or base type
        implementation_type: The concrete implementation type
        factory: Optional factory function for complex instantiation
        lifetime: How the service instance should be managed
        dependencies: List of service names this service depends on
        config: Configuration data to pass to the service
    """

    service_type: Type
    implementation_type: Optional[Type] = None
    factory: Optional[Callable] = None
    lifetime: ServiceLifetime = ServiceLifetime.SINGLETON
    dependencies: List[str] = None
    config: Dict[str, Any] = None

    def __post_init__(self):
        """Initialize default values for optional fields."""
        if self.dependencies is None:
            self.dependencies = []
        if self.config is None:
            self.config = {}


T = TypeVar("T")


class DIContainer:
    """
    Dependency Injection Container for managing service dependencies.
    
    This class provides a comprehensive DI container that manages the complete
    lifecycle of services in the AzabBot application. It handles service
    registration, dependency resolution, lifecycle management, and cleanup.
    
    The container supports multiple service lifetime modes and provides robust
    error handling, circular dependency detection, and health monitoring
    integration. It ensures proper service coordination and resource management.
    
    Key Features:
    - Service registration with multiple lifetime modes
    - Automatic dependency resolution with circular dependency detection
    - Service lifecycle management (initialization, startup, shutdown)
    - Factory function support for complex service creation
    - Configuration injection and management
    - Health monitoring integration
    - Thread-safe service resolution
    - Startup order calculation and dependency graph management
    
    The container manages the entire service lifecycle from registration through
    instantiation, initialization, and cleanup.
    """

    def __init__(self):
        """
        Initialize the DI container with default configuration.
        
        Sets up the container with empty service registrations, instance
        storage, and dependency tracking structures.
        """
        self.logger = get_logger()

        # Service registrations and metadata
        self._services: Dict[str, ServiceRegistration] = {}

        # Active service instances (for singleton services)
        self._instances: Dict[str, Any] = {}

        # Service initialization status tracking
        self._initialized_services: Set[str] = set()

        # Dependency graph for circular dependency detection
        self._dependency_graph: Dict[str, Set[str]] = {}

        # Service startup order (topologically sorted)
        self._startup_order: List[str] = []

        # Lock for thread safety during service resolution
        self._lock = asyncio.Lock()

        # Container configuration
        self._container_config: Dict[str, Any] = {}

        self.logger.log_info("DI Container initialized", "🏗️")

    def register_service(
        self,
        service_name: str,
        service_type: Type[T],
        implementation_type: Optional[Type[T]] = None,
        lifetime: ServiceLifetime = ServiceLifetime.SINGLETON,
        dependencies: Optional[List[str]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register a service with the container.

        Args:
            service_name: Unique name for the service
            service_type: Service interface/base type
            implementation_type: Concrete implementation (defaults to service_type)
            lifetime: Service lifetime management mode
            dependencies: List of dependency service names
            config: Service-specific configuration
        """
        if service_name in self._services:
            self.logger.log_warning(
                f"Service '{service_name}' is already registered, overwriting",
                {"service_name": service_name},
            )

        registration = ServiceRegistration(
            service_type=service_type,
            implementation_type=implementation_type or service_type,
            lifetime=lifetime,
            dependencies=dependencies or [],
            config=config or {},
        )

        self._services[service_name] = registration

        # Update dependency graph
        self._dependency_graph[service_name] = set(registration.dependencies)

        self.logger.log_info(f"Registered service: {service_name}", "📋")

    def register_factory(
        self,
        service_name: str,
        factory: Callable[..., T],
        lifetime: ServiceLifetime = ServiceLifetime.SINGLETON,
        dependencies: Optional[List[str]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register a service using a factory function.

        Args:
            service_name: Unique name for the service
            factory: Factory function that creates the service
            lifetime: Service lifetime management mode
            dependencies: List of dependency service names
            config: Service-specific configuration
        """
        registration = ServiceRegistration(
            service_type=type(None),  # Will be determined at runtime
            factory=factory,
            lifetime=lifetime,
            dependencies=dependencies or [],
            config=config or {},
        )

        self._services[service_name] = registration
        self._dependency_graph[service_name] = set(registration.dependencies)

        self.logger.log_info(f"Registered factory service: {service_name}", "🏭")

    def register_instance(
        self, service_name: str, instance: T, dependencies: Optional[List[str]] = None
    ) -> None:
        """
        Register an existing instance as a singleton service.

        Args:
            service_name: Unique name for the service
            instance: Pre-created service instance
            dependencies: List of dependency service names (for ordering)
        """
        registration = ServiceRegistration(
            service_type=type(instance),
            lifetime=ServiceLifetime.SINGLETON,
            dependencies=dependencies or [],
        )

        self._services[service_name] = registration
        self._instances[service_name] = instance
        self._initialized_services.add(service_name)
        self._dependency_graph[service_name] = set(registration.dependencies)

        self.logger.log_info(f"Registered instance: {service_name}", "📦")

    async def resolve(self, service_name: str) -> Any:
        """
        Resolve a service by name.

        Args:
            service_name: Name of the service to resolve

        Returns:
            Service instance

        Raises:
            ServiceError: If service cannot be resolved
        """
        async with self._lock:
            return await self._resolve_internal(service_name, set())

    async def _resolve_internal(
        self, service_name: str, resolving_chain: Set[str]
    ) -> Any:
        """
        Internal service resolution with circular dependency detection.

        Args:
            service_name: Service to resolve
            resolving_chain: Current resolution chain (for circular detection)

        Returns:
            Resolved service instance
        """
        # Check for circular dependencies
        if service_name in resolving_chain:
            chain_str = " -> ".join(list(resolving_chain) + [service_name])
            raise ServiceError(
                "DIContainer",
                f"Circular dependency detected: {chain_str}",
                error_code="CIRCULAR_DEPENDENCY",
            )

        # Check if service is registered
        if service_name not in self._services:
            raise ServiceError(
                "DIContainer",
                f"Service '{service_name}' is not registered",
                error_code="SERVICE_NOT_REGISTERED",
            )

        registration = self._services[service_name]

        # For singleton services, return existing instance if available
        if (
            registration.lifetime == ServiceLifetime.SINGLETON
            and service_name in self._instances
        ):
            return self._instances[service_name]

        # Add to resolving chain
        resolving_chain.add(service_name)

        try:
            # Resolve dependencies first
            resolved_dependencies = {}
            for dep_name in registration.dependencies:
                resolved_dependencies[dep_name] = await self._resolve_internal(
                    dep_name, resolving_chain.copy()
                )

            # Create service instance
            instance = await self._create_service_instance(
                service_name, registration, resolved_dependencies
            )

            # Store singleton instances
            if registration.lifetime == ServiceLifetime.SINGLETON:
                self._instances[service_name] = instance

            return instance

        finally:
            resolving_chain.discard(service_name)

    async def _create_service_instance(
        self,
        service_name: str,
        registration: ServiceRegistration,
        dependencies: Dict[str, Any],
    ) -> Any:
        """
        Create a service instance using registration information.

        Args:
            service_name: Name of the service
            registration: Service registration
            dependencies: Resolved dependencies

        Returns:
            Created service instance
        """
        try:
            # Use factory if provided
            if registration.factory:
                instance = await self._create_from_factory(
                    service_name, registration, dependencies
                )
            else:
                # Create from class
                instance = await self._create_from_class(
                    service_name, registration, dependencies
                )

            # Initialize if it's a BaseService
            if isinstance(instance, BaseService):
                await self._initialize_base_service(
                    instance, registration, dependencies
                )

            self.logger.log_info(f"Created service instance: {service_name}", "✅")

            return instance

        except Exception as e:
            self.logger.log_error(
                f"Failed to create service instance: {service_name}",
                exception=e,
                context={"service_name": service_name},
            )
            raise ServiceInitializationError(service_name, str(e)) from e

    async def _create_from_factory(
        self,
        service_name: str,
        registration: ServiceRegistration,
        dependencies: Dict[str, Any],
    ) -> Any:
        """Create service instance from factory function."""
        factory = registration.factory

        # Inspect factory signature to provide appropriate arguments
        sig = inspect.signature(factory)
        factory_args = {}

        for param_name, _param in sig.parameters.items():
            if param_name in dependencies:
                factory_args[param_name] = dependencies[param_name]
            elif param_name == "config":
                factory_args[param_name] = registration.config
            elif param_name == "container":
                factory_args[param_name] = self

        # Call factory (handle both sync and async)
        if asyncio.iscoroutinefunction(factory):
            return await factory(**factory_args)
        else:
            return factory(**factory_args)

    async def _create_from_class(
        self,
        service_name: str,
        registration: ServiceRegistration,
        dependencies: Dict[str, Any],
    ) -> Any:
        """Create service instance from class constructor."""
        impl_type = registration.implementation_type

        # Inspect constructor to provide appropriate arguments
        sig = inspect.signature(impl_type.__init__)
        constructor_args = {}

        for param_name, _param in sig.parameters.items():
            if param_name == "self":
                continue
            elif param_name in dependencies:
                constructor_args[param_name] = dependencies[param_name]
            elif param_name == "config":
                constructor_args[param_name] = registration.config
            elif param_name == "name":
                constructor_args[param_name] = service_name

        return impl_type(**constructor_args)

    async def _initialize_base_service(
        self,
        service: BaseService,
        registration: ServiceRegistration,
        dependencies: Dict[str, Any],
    ) -> None:
        """Initialize a BaseService instance."""
        if service.name in self._initialized_services:
            return

        # Prepare initialization config
        init_config = registration.config.copy()
        init_config.update(self._container_config)

        # Add dependencies to config if needed
        init_config["dependencies"] = dependencies

        await service.initialize_base(init_config, **dependencies)
        self._initialized_services.add(service.name)

    async def initialize_all_services(self) -> None:
        """
        Initialize all registered services in dependency order.

        This method starts all singleton services and ensures they are
        properly initialized in the correct order.

        Raises:
            ServiceInitializationError: If any service fails to initialize
        """
        self.logger.log_info("Initializing all services", "🚀")

        try:
            # Calculate startup order
            await self._calculate_startup_order()

            # Initialize services in order
            for service_name in self._startup_order:
                registration = self._services[service_name]

                # Only initialize singleton services here
                if registration.lifetime == ServiceLifetime.SINGLETON:
                    try:
                        instance = await self.resolve(service_name)

                        # Start service if it's a BaseService
                        if isinstance(instance, BaseService):
                            await instance.start_base()

                        self.logger.log_initialization_step(
                            service_name, "success", "Service initialized and started"
                        )

                    except Exception as e:
                        self.logger.log_initialization_step(
                            service_name,
                            "error",
                            f"Service initialization failed: {str(e)}",
                        )
                        raise

            self.logger.log_info(
                f"Successfully initialized {len(self._startup_order)} services", "✅"
            )

        except Exception as e:
            self.logger.log_error("Service initialization failed", exception=e)
            raise

    async def _calculate_startup_order(self) -> None:
        """Calculate the correct startup order using topological sort."""
        # Topological sort to determine startup order
        visited = set()
        temp_visited = set()
        startup_order = []

        def visit(service_name: str):
            if service_name in temp_visited:
                # Circular dependency detected
                raise ServiceError(
                    "DIContainer",
                    f"Circular dependency detected involving service: {service_name}",
                    error_code="CIRCULAR_DEPENDENCY",
                )

            if service_name not in visited:
                temp_visited.add(service_name)

                # Visit dependencies first
                dependencies = self._dependency_graph.get(service_name, set())
                for dep in dependencies:
                    if dep in self._services:  # Only visit registered services
                        visit(dep)

                temp_visited.remove(service_name)
                visited.add(service_name)
                startup_order.append(service_name)

        # Visit all services
        for service_name in self._services:
            if service_name not in visited:
                visit(service_name)

        self._startup_order = startup_order

    async def shutdown_all_services(self) -> None:
        """
        Shutdown all services in reverse dependency order.

        This ensures that services are shut down cleanly without
        breaking dependencies.
        """
        self.logger.log_info("Shutting down all services", "🛑")

        # Shutdown in reverse order
        shutdown_order = list(reversed(self._startup_order))

        for service_name in shutdown_order:
            try:
                if service_name in self._instances:
                    instance = self._instances[service_name]

                    if isinstance(instance, BaseService):
                        await instance.stop_base()

                    self.logger.log_info(f"Shutdown service: {service_name}")

            except Exception as e:
                self.logger.log_error(
                    f"Error shutting down service {service_name}", exception=e
                )

        # Clear instances
        self._instances.clear()
        self._initialized_services.clear()

        self.logger.log_info("All services shut down", "✅")

    def get_service_health(self) -> Dict[str, Any]:
        """
        Get health status of all services.

        Returns:
            Dictionary with service health information
        """
        health_status = {
            "container_status": "healthy",
            "total_services": len(self._services),
            "initialized_services": len(self._initialized_services),
            "services": {},
        }

        for service_name, instance in self._instances.items():
            if isinstance(instance, BaseService):
                health_status["services"][service_name] = {
                    "status": instance.status.value,
                    "is_healthy": instance.is_healthy(),
                    "metrics": instance.get_metrics().__dict__,
                }
            else:
                health_status["services"][service_name] = {
                    "status": "unknown",
                    "is_healthy": True,
                    "type": type(instance).__name__,
                }

        return health_status

    def list_services(self) -> Dict[str, Dict[str, Any]]:
        """
        List all registered services with their configuration.

        Returns:
            Dictionary of service information
        """
        services_info = {}

        for service_name, registration in self._services.items():
            services_info[service_name] = {
                "service_type": registration.service_type.__name__,
                "implementation_type": (
                    registration.implementation_type.__name__
                    if registration.implementation_type
                    else None
                ),
                "lifetime": registration.lifetime.value,
                "dependencies": registration.dependencies,
                "is_factory": registration.factory is not None,
                "is_initialized": service_name in self._initialized_services,
                "has_instance": service_name in self._instances,
            }

        return services_info

    def set_container_config(self, config: Dict[str, Any]) -> None:
        """
        Set global container configuration.

        Args:
            config: Global configuration to apply to all services
        """
        self._container_config = config.copy()


# =============================================================================
# Global DI Container Instance
# =============================================================================

# Create global DI container instance
_global_container = DIContainer()


def get_container() -> DIContainer:
    """Get the global DI container instance."""
    return _global_container


def register_service(
    service_name: str,
    service_type: Type[T],
    implementation_type: Optional[Type[T]] = None,
    lifetime: ServiceLifetime = ServiceLifetime.SINGLETON,
    dependencies: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """Register a service with the global container."""
    return _global_container.register_service(
        service_name, service_type, implementation_type, lifetime, dependencies, config
    )


def register_factory(
    service_name: str,
    factory: Callable[..., T],
    lifetime: ServiceLifetime = ServiceLifetime.SINGLETON,
    dependencies: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """Register a factory service with the global container."""
    return _global_container.register_factory(
        service_name, factory, lifetime, dependencies, config
    )


async def resolve(service_name: str) -> Any:
    """Resolve a service from the global container."""
    return await _global_container.resolve(service_name)


async def initialize_all_services() -> None:
    """Initialize all services in the global container."""
    return await _global_container.initialize_all_services()
