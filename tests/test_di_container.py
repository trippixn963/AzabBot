"""Tests for dependency injection container."""

import pytest

from src.core.di_container import (
    CircularDependencyError,
    DIContainer,
    ServiceNotFoundError,
    _global_container,
    get_container,
    setup_dependencies,
)
from src.services.base_service import BaseService, ServiceStatus

# Test service classes


class TestServiceA(BaseService):
    """Test service A."""

    async def _initialize(self) -> None:
        self.initialized = True

    async def _shutdown(self) -> None:
        self.shutdown = True

    async def health_check(self) -> bool:
        return True


class TestServiceB(BaseService):
    """Test service B that depends on A."""

    def __init__(self, service_a: TestServiceA):
        super().__init__()
        self.service_a = service_a

    async def _initialize(self) -> None:
        self.initialized = True

    async def _shutdown(self) -> None:
        self.shutdown = True

    async def health_check(self) -> bool:
        return True


class TestServiceC(BaseService):
    """Test service C that depends on B."""

    def __init__(self, service_b: TestServiceB):
        super().__init__()
        self.service_b = service_b

    async def _initialize(self) -> None:
        self.initialized = True

    async def _shutdown(self) -> None:
        self.shutdown = True

    async def health_check(self) -> bool:
        return True


class TestDIContainer:
    """Test cases for DIContainer class."""

    def test_container_initialization(self):
        """Test container initialization."""
        container = DIContainer()
        assert len(container._services) == 0
        assert len(container._factories) == 0
        assert len(container._singletons) == 0

    def test_register_singleton(self):
        """Test singleton registration."""
        container = DIContainer()
        service = TestServiceA()

        container.register_singleton("service_a", service)

        # Should return same instance
        retrieved1 = container.get("service_a")
        retrieved2 = container.get("service_a")

        assert retrieved1 is service
        assert retrieved2 is service
        assert retrieved1 is retrieved2

    def test_register_factory(self):
        """Test factory registration."""
        container = DIContainer()

        def factory():
            return TestServiceA()

        container.register_factory("service_a", factory)

        # Should create new instances
        retrieved1 = container.get("service_a")
        retrieved2 = container.get("service_a")

        assert isinstance(retrieved1, TestServiceA)
        assert isinstance(retrieved2, TestServiceA)
        assert retrieved1 is not retrieved2

    def test_register_factory_with_dependencies(self):
        """Test factory with dependency resolution."""
        container = DIContainer()

        # Register service A
        container.register_singleton("service_a", TestServiceA())

        # Register service B with dependency
        def factory_b(service_a=("service_a", TestServiceA)):
            return TestServiceB(service_a)

        container.register_factory("service_b", factory_b)

        # Get service B
        service_b = container.get("service_b")

        assert isinstance(service_b, TestServiceB)
        assert isinstance(service_b.service_a, TestServiceA)

    def test_service_not_found(self):
        """Test exception when service not found."""
        container = DIContainer()

        with pytest.raises(ServiceNotFoundError) as exc_info:
            container.get("non_existent")

        assert "non_existent" in str(exc_info.value)

    def test_circular_dependency_detection(self):
        """Test circular dependency detection."""
        container = DIContainer()

        # Create circular dependency A -> B -> A
        def factory_a(service_b=("service_b", TestServiceB)):
            return TestServiceA()

        def factory_b(service_a=("service_a", TestServiceA)):
            return TestServiceB(TestServiceA())  # Dummy for type

        container.register_factory("service_a", factory_a)
        container.register_factory("service_b", factory_b)

        with pytest.raises(CircularDependencyError):
            container.get("service_a")

    def test_override_service(self):
        """Test service override."""
        container = DIContainer()

        # Register original
        service1 = TestServiceA()
        container.register_singleton("service", service1)

        # Override
        service2 = TestServiceA()
        container.register_singleton("service", service2)

        # Should return new service
        retrieved = container.get("service")
        assert retrieved is service2
        assert retrieved is not service1

    def test_has_service(self):
        """Test checking if service exists."""
        container = DIContainer()

        assert not container.has("service_a")

        container.register_singleton("service_a", TestServiceA())

        assert container.has("service_a")

    def test_complex_dependency_chain(self):
        """Test complex dependency resolution."""
        container = DIContainer()

        # Register services with chain A -> B -> C
        container.register_singleton("service_a", TestServiceA())

        def factory_b(service_a=("service_a", TestServiceA)):
            return TestServiceB(service_a)

        def factory_c(service_b=("service_b", TestServiceB)):
            return TestServiceC(service_b)

        container.register_factory("service_b", factory_b)
        container.register_factory("service_c", factory_c)

        # Get service C
        service_c = container.get("service_c")

        assert isinstance(service_c, TestServiceC)
        assert isinstance(service_c.service_b, TestServiceB)
        assert isinstance(service_c.service_b.service_a, TestServiceA)

    @pytest.mark.asyncio
    async def test_initialize_all_services(self):
        """Test initializing all services."""
        container = DIContainer()

        # Register services
        service_a = TestServiceA()
        service_b = TestServiceB(service_a)

        container.register_singleton("service_a", service_a)
        container.register_singleton("service_b", service_b)

        # Initialize all
        await container.initialize_all()

        assert service_a.status == ServiceStatus.RUNNING
        assert service_b.status == ServiceStatus.RUNNING
        assert hasattr(service_a, "initialized") and service_a.initialized
        assert hasattr(service_b, "initialized") and service_b.initialized

    @pytest.mark.asyncio
    async def test_shutdown_all_services(self):
        """Test shutting down all services."""
        container = DIContainer()

        # Register and initialize services
        service_a = TestServiceA()
        service_b = TestServiceB(service_a)

        container.register_singleton("service_a", service_a)
        container.register_singleton("service_b", service_b)

        await container.initialize_all()

        # Shutdown all
        await container.shutdown_all()

        assert service_a.status == ServiceStatus.STOPPED
        assert service_b.status == ServiceStatus.STOPPED
        assert hasattr(service_a, "shutdown") and service_a.shutdown
        assert hasattr(service_b, "shutdown") and service_b.shutdown

    def test_factory_with_optional_dependencies(self):
        """Test factory with optional dependencies."""
        container = DIContainer()

        # Factory with optional dependency
        def factory(service_a=("service_a", TestServiceA, None)):
            if service_a:
                return TestServiceB(service_a)
            else:
                return TestServiceB(TestServiceA())  # Create default

        container.register_factory("service_b", factory)

        # Should work without service_a registered
        service_b = container.get("service_b")
        assert isinstance(service_b, TestServiceB)

    def test_get_all_services(self):
        """Test getting all services."""
        container = DIContainer()

        # Register multiple services
        container.register_singleton("service_a", TestServiceA())
        container.register_singleton("service_b", TestServiceB(TestServiceA()))

        all_services = container.get_all()

        assert len(all_services) == 2
        assert "service_a" in all_services
        assert "service_b" in all_services
        assert isinstance(all_services["service_a"], TestServiceA)
        assert isinstance(all_services["service_b"], TestServiceB)


class TestGlobalContainer:
    """Test cases for global container functions."""

    @pytest.mark.asyncio
    async def test_setup_dependencies(self):
        """Test setting up dependencies."""
        # Clear any existing container
        if hasattr(_global_container, "_services"):
            _global_container._services.clear()
            _global_container._factories.clear()
            _global_container._singletons.clear()

        await setup_dependencies()

        # Check core services are registered
        container = get_container()
        assert container.has("config")
        assert container.has("database")
        assert container.has("ai_service")
        assert container.has("report_service")
        assert container.has("security_manager")

    def test_get_container(self):
        """Test getting global container."""
        container1 = get_container()
        container2 = get_container()

        assert container1 is container2  # Same instance
        assert isinstance(container1, DIContainer)
