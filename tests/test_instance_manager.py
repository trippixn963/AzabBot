"""
Test module for instance manager functionality.

This module tests the instance management system, including singleton patterns,
resource management, lifecycle management, and cleanup operations.
"""

import pytest
import threading
import time
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

from src.core.instance_manager import (
    InstanceManager,
    Singleton,
    ResourceManager,
    LifecycleManager,
    InstanceRegistry,
    InstanceMetadata,
    InstanceState,
    InstanceError,
    ResourceError,
    LifecycleError,
)


class TestSingleton:
    """Test cases for Singleton decorator."""

    def test_singleton_creation(self):
        """Test singleton instance creation."""
        @Singleton
        class TestClass:
            def __init__(self):
                self.value = 42

        # Create first instance
        instance1 = TestClass()
        assert instance1.value == 42

        # Create second instance - should be the same
        instance2 = TestClass()
        assert instance2.value == 42
        assert instance1 is instance2

    def test_singleton_with_arguments(self):
        """Test singleton with constructor arguments."""
        @Singleton
        class TestClass:
            def __init__(self, value=0):
                self.value = value

        # First call with default
        instance1 = TestClass()
        assert instance1.value == 0

        # Second call with argument - should ignore argument
        instance2 = TestClass(100)
        assert instance2.value == 0
        assert instance1 is instance2

    def test_singleton_reset(self):
        """Test singleton reset functionality."""
        @Singleton
        class TestClass:
            def __init__(self):
                self.value = 42

        instance1 = TestClass()
        assert instance1.value == 42

        # Reset singleton
        TestClass._reset()
        
        # Create new instance
        instance2 = TestClass()
        assert instance2.value == 42
        assert instance1 is not instance2

    def test_multiple_singleton_classes(self):
        """Test multiple singleton classes don't interfere."""
        @Singleton
        class ClassA:
            def __init__(self):
                self.name = "A"

        @Singleton
        class ClassB:
            def __init__(self):
                self.name = "B"

        a1 = ClassA()
        b1 = ClassB()
        
        a2 = ClassA()
        b2 = ClassB()
        
        assert a1 is a2
        assert b1 is b2
        assert a1 is not b1


class TestInstanceMetadata:
    """Test cases for InstanceMetadata."""

    def test_metadata_creation(self):
        """Test metadata creation and properties."""
        metadata = InstanceMetadata(
            instance_id="test-123",
            class_name="TestClass",
            created_at=1234567890.0,
            state=InstanceState.ACTIVE
        )
        
        assert metadata.instance_id == "test-123"
        assert metadata.class_name == "TestClass"
        assert metadata.created_at == 1234567890.0
        assert metadata.state == InstanceState.ACTIVE

    def test_metadata_defaults(self):
        """Test metadata with default values."""
        metadata = InstanceMetadata("test-123", "TestClass")
        
        assert metadata.instance_id == "test-123"
        assert metadata.class_name == "TestClass"
        assert metadata.created_at > 0
        assert metadata.state == InstanceState.CREATED

    def test_metadata_str_representation(self):
        """Test metadata string representation."""
        metadata = InstanceMetadata("test-123", "TestClass")
        str_repr = str(metadata)
        
        assert "test-123" in str_repr
        assert "TestClass" in str_repr


class TestInstanceRegistry:
    """Test cases for InstanceRegistry."""

    def test_registry_initialization(self):
        """Test registry initialization."""
        registry = InstanceRegistry()
        
        assert registry._instances == {}
        assert registry._metadata == {}

    def test_register_instance(self):
        """Test instance registration."""
        registry = InstanceRegistry()
        instance = Mock()
        
        registry.register("test-123", instance, "TestClass")
        
        assert "test-123" in registry._instances
        assert registry._instances["test-123"] is instance
        assert "test-123" in registry._metadata

    def test_get_instance(self):
        """Test getting registered instance."""
        registry = InstanceRegistry()
        instance = Mock()
        
        registry.register("test-123", instance, "TestClass")
        retrieved = registry.get("test-123")
        
        assert retrieved is instance

    def test_get_nonexistent_instance(self):
        """Test getting non-existent instance."""
        registry = InstanceRegistry()
        
        with pytest.raises(InstanceError):
            registry.get("nonexistent")

    def test_unregister_instance(self):
        """Test instance unregistration."""
        registry = InstanceRegistry()
        instance = Mock()
        
        registry.register("test-123", instance, "TestClass")
        registry.unregister("test-123")
        
        assert "test-123" not in registry._instances
        assert "test-123" not in registry._metadata

    def test_list_instances(self):
        """Test listing all instances."""
        registry = InstanceRegistry()
        
        registry.register("test-1", Mock(), "TestClass1")
        registry.register("test-2", Mock(), "TestClass2")
        
        instances = registry.list_instances()
        
        assert len(instances) == 2
        assert "test-1" in instances
        assert "test-2" in instances

    def test_get_metadata(self):
        """Test getting instance metadata."""
        registry = InstanceRegistry()
        
        registry.register("test-123", Mock(), "TestClass")
        metadata = registry.get_metadata("test-123")
        
        assert metadata.instance_id == "test-123"
        assert metadata.class_name == "TestClass"

    def test_update_metadata(self):
        """Test updating instance metadata."""
        registry = InstanceRegistry()
        
        registry.register("test-123", Mock(), "TestClass")
        registry.update_metadata("test-123", state=InstanceState.INACTIVE)
        
        metadata = registry.get_metadata("test-123")
        assert metadata.state == InstanceState.INACTIVE

    def test_clear_registry(self):
        """Test clearing entire registry."""
        registry = InstanceRegistry()
        
        registry.register("test-1", Mock(), "TestClass1")
        registry.register("test-2", Mock(), "TestClass2")
        
        registry.clear()
        
        assert len(registry._instances) == 0
        assert len(registry._metadata) == 0


class TestResourceManager:
    """Test cases for ResourceManager."""

    def test_resource_manager_initialization(self):
        """Test resource manager initialization."""
        manager = ResourceManager()
        
        assert manager._resources == {}
        assert manager._resource_limits == {}

    def test_register_resource(self):
        """Test resource registration."""
        manager = ResourceManager()
        resource = Mock()
        
        manager.register_resource("test-resource", resource, max_instances=5)
        
        assert "test-resource" in manager._resources
        assert manager._resources["test-resource"] == resource
        assert manager._resource_limits["test-resource"] == 5

    def test_get_resource(self):
        """Test getting registered resource."""
        manager = ResourceManager()
        resource = Mock()
        
        manager.register_resource("test-resource", resource)
        retrieved = manager.get_resource("test-resource")
        
        assert retrieved is resource

    def test_get_nonexistent_resource(self):
        """Test getting non-existent resource."""
        manager = ResourceManager()
        
        with pytest.raises(ResourceError):
            manager.get_resource("nonexistent")

    def test_check_resource_limit(self):
        """Test resource limit checking."""
        manager = ResourceManager()
        
        manager.register_resource("test-resource", Mock(), max_instances=2)
        
        # Should allow first two
        assert manager.check_resource_limit("test-resource")
        assert manager.check_resource_limit("test-resource")
        
        # Should deny third
        assert not manager.check_resource_limit("test-resource")

    def test_release_resource(self):
        """Test resource release."""
        manager = ResourceManager()
        
        manager.register_resource("test-resource", Mock(), max_instances=1)
        manager.check_resource_limit("test-resource")  # Use one
        manager.release_resource("test-resource")  # Release one
        
        # Should allow another
        assert manager.check_resource_limit("test-resource")

    def test_resource_cleanup(self):
        """Test resource cleanup."""
        manager = ResourceManager()
        resource = Mock()
        
        manager.register_resource("test-resource", resource)
        manager.cleanup()
        
        resource.cleanup.assert_called_once()

    def test_resource_health_check(self):
        """Test resource health checking."""
        manager = ResourceManager()
        resource = Mock()
        resource.is_healthy.return_value = True
        
        manager.register_resource("test-resource", resource)
        is_healthy = manager.check_resource_health("test-resource")
        
        assert is_healthy
        resource.is_healthy.assert_called_once()


class TestLifecycleManager:
    """Test cases for LifecycleManager."""

    def test_lifecycle_manager_initialization(self):
        """Test lifecycle manager initialization."""
        manager = LifecycleManager()
        
        assert manager._instances == {}
        assert manager._lifecycle_hooks == {}

    def test_register_lifecycle_hook(self):
        """Test lifecycle hook registration."""
        manager = LifecycleManager()
        hook = Mock()
        
        manager.register_lifecycle_hook("test-instance", "startup", hook)
        
        assert "test-instance" in manager._lifecycle_hooks
        assert "startup" in manager._lifecycle_hooks["test-instance"]

    def test_execute_lifecycle_hook(self):
        """Test lifecycle hook execution."""
        manager = LifecycleManager()
        hook = Mock()
        
        manager.register_lifecycle_hook("test-instance", "startup", hook)
        manager.execute_lifecycle_hook("test-instance", "startup")
        
        hook.assert_called_once()

    def test_execute_nonexistent_hook(self):
        """Test executing non-existent hook."""
        manager = LifecycleManager()
        
        # Should not raise exception for non-existent hooks
        manager.execute_lifecycle_hook("test-instance", "nonexistent")

    def test_instance_startup(self):
        """Test instance startup lifecycle."""
        manager = LifecycleManager()
        instance = Mock()
        
        manager.startup_instance("test-instance", instance)
        
        assert "test-instance" in manager._instances
        assert manager._instances["test-instance"] is instance

    def test_instance_shutdown(self):
        """Test instance shutdown lifecycle."""
        manager = LifecycleManager()
        instance = Mock()
        
        manager.startup_instance("test-instance", instance)
        manager.shutdown_instance("test-instance")
        
        assert "test-instance" not in manager._instances

    def test_lifecycle_events(self):
        """Test lifecycle event handling."""
        manager = LifecycleManager()
        events = []
        
        def event_handler(event_type, instance_id):
            events.append((event_type, instance_id))
        
        manager.register_lifecycle_hook("test-instance", "startup", event_handler)
        manager.register_lifecycle_hook("test-instance", "shutdown", event_handler)
        
        manager.startup_instance("test-instance", Mock())
        manager.shutdown_instance("test-instance")
        
        assert len(events) == 2
        assert events[0] == ("startup", "test-instance")
        assert events[1] == ("shutdown", "test-instance")


class TestInstanceManager:
    """Test cases for main InstanceManager class."""

    def test_instance_manager_initialization(self):
        """Test instance manager initialization."""
        manager = InstanceManager()
        
        assert manager.registry is not None
        assert manager.resource_manager is not None
        assert manager.lifecycle_manager is not None

    def test_create_instance(self):
        """Test instance creation."""
        manager = InstanceManager()
        
        class TestClass:
            def __init__(self, value):
                self.value = value
        
        instance = manager.create_instance("test-123", TestClass, value=42)
        
        assert instance.value == 42
        assert manager.registry.get("test-123") is instance

    def test_create_instance_with_resource_check(self):
        """Test instance creation with resource checking."""
        manager = InstanceManager()
        
        class TestClass:
            def __init__(self):
                pass
        
        # Register resource with limit
        manager.resource_manager.register_resource("TestClass", Mock(), max_instances=1)
        
        # Should create first instance
        instance1 = manager.create_instance("test-1", TestClass)
        assert instance1 is not None
        
        # Should fail to create second instance
        with pytest.raises(ResourceError):
            manager.create_instance("test-2", TestClass)

    def test_destroy_instance(self):
        """Test instance destruction."""
        manager = InstanceManager()
        
        class TestClass:
            def __init__(self):
                pass
        
        instance = manager.create_instance("test-123", TestClass)
        manager.destroy_instance("test-123")
        
        with pytest.raises(InstanceError):
            manager.registry.get("test-123")

    def test_get_instance(self):
        """Test getting instance."""
        manager = InstanceManager()
        
        class TestClass:
            def __init__(self):
                pass
        
        created_instance = manager.create_instance("test-123", TestClass)
        retrieved_instance = manager.get_instance("test-123")
        
        assert retrieved_instance is created_instance

    def test_list_instances(self):
        """Test listing all instances."""
        manager = InstanceManager()
        
        class TestClass:
            def __init__(self):
                pass
        
        manager.create_instance("test-1", TestClass)
        manager.create_instance("test-2", TestClass)
        
        instances = manager.list_instances()
        
        assert len(instances) == 2
        assert "test-1" in instances
        assert "test-2" in instances

    def test_instance_health_check(self):
        """Test instance health checking."""
        manager = InstanceManager()
        
        class TestClass:
            def __init__(self):
                pass
            
            def is_healthy(self):
                return True
        
        instance = manager.create_instance("test-123", TestClass)
        is_healthy = manager.check_instance_health("test-123")
        
        assert is_healthy

    def test_cleanup_all_instances(self):
        """Test cleaning up all instances."""
        manager = InstanceManager()
        
        class TestClass:
            def __init__(self):
                pass
        
        manager.create_instance("test-1", TestClass)
        manager.create_instance("test-2", TestClass)
        
        manager.cleanup_all()
        
        assert len(manager.list_instances()) == 0

    def test_instance_metadata_tracking(self):
        """Test instance metadata tracking."""
        manager = InstanceManager()
        
        class TestClass:
            def __init__(self):
                pass
        
        manager.create_instance("test-123", TestClass)
        metadata = manager.get_instance_metadata("test-123")
        
        assert metadata.instance_id == "test-123"
        assert metadata.class_name == "TestClass"
        assert metadata.state == InstanceState.ACTIVE

    def test_concurrent_instance_creation(self):
        """Test concurrent instance creation."""
        manager = InstanceManager()
        
        class TestClass:
            def __init__(self):
                pass
        
        def create_instance(instance_id):
            return manager.create_instance(instance_id, TestClass)
        
        # Create instances in parallel
        threads = []
        for i in range(5):
            thread = threading.Thread(target=create_instance, args=(f"test-{i}",))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        instances = manager.list_instances()
        assert len(instances) == 5

    def test_instance_error_handling(self):
        """Test instance error handling."""
        manager = InstanceManager()
        
        class TestClass:
            def __init__(self):
                raise Exception("Initialization failed")
        
        with pytest.raises(InstanceError):
            manager.create_instance("test-123", TestClass)

    def test_resource_cleanup_on_destroy(self):
        """Test resource cleanup when destroying instances."""
        manager = InstanceManager()
        
        class TestClass:
            def __init__(self):
                pass
        
        # Register resource
        resource = Mock()
        manager.resource_manager.register_resource("TestClass", resource, max_instances=1)
        
        # Create and destroy instance
        manager.create_instance("test-123", TestClass)
        manager.destroy_instance("test-123")
        
        # Resource should be released
        assert manager.resource_manager.check_resource_limit("TestClass")

    def test_lifecycle_hooks_execution(self):
        """Test lifecycle hooks execution."""
        manager = InstanceManager()
        events = []
        
        def startup_hook(instance_id):
            events.append(f"startup-{instance_id}")
        
        def shutdown_hook(instance_id):
            events.append(f"shutdown-{instance_id}")
        
        class TestClass:
            def __init__(self):
                pass
        
        # Register hooks
        manager.lifecycle_manager.register_lifecycle_hook("test-123", "startup", startup_hook)
        manager.lifecycle_manager.register_lifecycle_hook("test-123", "shutdown", shutdown_hook)
        
        # Create and destroy instance
        manager.create_instance("test-123", TestClass)
        manager.destroy_instance("test-123")
        
        assert "startup-test-123" in events
        assert "shutdown-test-123" in events

    def test_instance_state_transitions(self):
        """Test instance state transitions."""
        manager = InstanceManager()
        
        class TestClass:
            def __init__(self):
                pass
        
        # Create instance
        manager.create_instance("test-123", TestClass)
        metadata = manager.get_instance_metadata("test-123")
        assert metadata.state == InstanceState.ACTIVE
        
        # Mark as inactive
        manager.registry.update_metadata("test-123", state=InstanceState.INACTIVE)
        metadata = manager.get_instance_metadata("test-123")
        assert metadata.state == InstanceState.INACTIVE
        
        # Destroy instance
        manager.destroy_instance("test-123")
        with pytest.raises(InstanceError):
            manager.get_instance_metadata("test-123")

    def test_instance_manager_singleton(self):
        """Test that InstanceManager follows singleton pattern."""
        manager1 = InstanceManager()
        manager2 = InstanceManager()
        
        assert manager1 is manager2

    def test_instance_manager_reset(self):
        """Test InstanceManager reset functionality."""
        manager1 = InstanceManager()
        
        class TestClass:
            def __init__(self):
                pass
        
        manager1.create_instance("test-123", TestClass)
        
        # Reset singleton
        InstanceManager._reset()
        
        manager2 = InstanceManager()
        assert manager1 is not manager2
        assert len(manager2.list_instances()) == 0
