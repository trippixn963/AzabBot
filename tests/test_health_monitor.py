"""Tests for health monitoring module."""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from src.monitoring.health_monitor import (
    HealthMonitor,
    HealthStatus,
    ComponentHealth,
    SystemMetrics
)


class TestHealthMonitor:
    """Test cases for HealthMonitor class."""

    @pytest.mark.asyncio
    async def test_health_monitor_initialization(self):
        """Test HealthMonitor initialization."""
        monitor = HealthMonitor()
        
        assert monitor.check_interval == 60
        assert monitor._running is False
        assert isinstance(monitor._health_status, dict)
        assert isinstance(monitor._metrics_history, list)

    @pytest.mark.asyncio
    async def test_start_stop_monitoring(self):
        """Test starting and stopping health monitoring."""
        monitor = HealthMonitor()
        monitor.check_interval = 0.1  # Fast checks for testing
        
        # Start monitoring
        task = asyncio.create_task(monitor.start_monitoring())
        await asyncio.sleep(0.05)  # Let it start
        
        assert monitor._running is True
        
        # Stop monitoring
        await monitor.stop()
        
        assert monitor._running is False
        
        # Ensure task completes
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except asyncio.TimeoutError:
            task.cancel()

    @pytest.mark.asyncio
    async def test_check_system_health(self):
        """Test system health checking."""
        monitor = HealthMonitor()
        
        health = await monitor.check_health()
        
        assert isinstance(health, HealthStatus)
        assert health.timestamp is not None
        assert isinstance(health.components, dict)
        assert isinstance(health.system_metrics, SystemMetrics)
        
        # Check system metrics
        assert 0 <= health.system_metrics.cpu_percent <= 100
        assert 0 <= health.system_metrics.memory_percent <= 100
        assert health.system_metrics.disk_usage_percent >= 0

    @pytest.mark.asyncio
    async def test_check_discord_health(self):
        """Test Discord connection health check."""
        monitor = HealthMonitor()
        
        # Mock discord client
        with patch('src.monitoring.health_monitor.get_container') as mock_container:
            mock_bot = MagicMock()
            mock_bot.is_ready.return_value = True
            mock_bot.latency = 0.05  # 50ms
            
            mock_container.return_value.get.return_value = mock_bot
            
            component_health = await monitor._check_discord_health()
            
            assert component_health.name == "discord"
            assert component_health.status == "healthy"
            assert component_health.latency_ms == 50
            assert "Connected" in component_health.details

    @pytest.mark.asyncio
    async def test_check_discord_unhealthy(self):
        """Test Discord health check when disconnected."""
        monitor = HealthMonitor()
        
        with patch('src.monitoring.health_monitor.get_container') as mock_container:
            mock_bot = MagicMock()
            mock_bot.is_ready.return_value = False
            
            mock_container.return_value.get.return_value = mock_bot
            
            component_health = await monitor._check_discord_health()
            
            assert component_health.status == "unhealthy"
            assert component_health.error is not None

    @pytest.mark.asyncio
    async def test_check_database_health(self):
        """Test database health check."""
        monitor = HealthMonitor()
        
        with patch('src.monitoring.health_monitor.get_container') as mock_container:
            mock_db = AsyncMock()
            mock_db.is_healthy.return_value = True
            mock_db.get_database_metrics.return_value = {
                "total_prisoners": 10,
                "active_sessions": 2
            }
            
            mock_container.return_value.get.return_value = mock_db
            
            component_health = await monitor._check_database_health()
            
            assert component_health.name == "database"
            assert component_health.status == "healthy"
            assert component_health.details["total_prisoners"] == 10

    @pytest.mark.asyncio
    async def test_check_ai_service_health(self):
        """Test AI service health check."""
        monitor = HealthMonitor()
        
        with patch('src.monitoring.health_monitor.get_container') as mock_container:
            mock_ai = MagicMock()
            mock_ai.is_healthy.return_value = True
            mock_ai.get_metrics.return_value = {
                "total_requests": 100,
                "successful_requests": 95,
                "cache_size": 5
            }
            
            mock_container.return_value.get.return_value = mock_ai
            
            component_health = await monitor._check_ai_health()
            
            assert component_health.name == "ai_service"
            assert component_health.status == "healthy"
            assert component_health.details["success_rate"] == 95.0

    @pytest.mark.asyncio
    async def test_get_health_summary(self):
        """Test getting health summary."""
        monitor = HealthMonitor()
        
        # Perform a health check
        await monitor.check_health()
        
        summary = monitor.get_health_summary()
        
        assert "overall_status" in summary
        assert "components" in summary
        assert "system_metrics" in summary
        assert "last_check" in summary
        assert isinstance(summary["checks_performed"], int)

    @pytest.mark.asyncio
    async def test_is_healthy(self):
        """Test overall health status."""
        monitor = HealthMonitor()
        
        # Initially unhealthy (no checks)
        assert not monitor.is_healthy()
        
        # Perform check
        await monitor.check_health()
        
        # Should have a status now
        assert isinstance(monitor.is_healthy(), bool)

    @pytest.mark.asyncio
    async def test_health_history_limit(self):
        """Test health history is limited."""
        monitor = HealthMonitor()
        monitor._max_history = 5
        
        # Add more than max history
        for i in range(10):
            await monitor.check_health()
            await asyncio.sleep(0.01)
        
        assert len(monitor._metrics_history) <= 5

    @pytest.mark.asyncio
    async def test_component_error_handling(self):
        """Test error handling in component checks."""
        monitor = HealthMonitor()
        
        with patch('src.monitoring.health_monitor.get_container') as mock_container:
            # Make database check raise exception
            mock_container.return_value.get.side_effect = Exception("DB Error")
            
            component_health = await monitor._check_database_health()
            
            assert component_health.status == "unhealthy"
            assert "DB Error" in component_health.error
            assert component_health.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_system_metrics_collection(self):
        """Test system metrics collection."""
        monitor = HealthMonitor()
        
        metrics = await monitor._get_system_metrics()
        
        assert isinstance(metrics, SystemMetrics)
        assert 0 <= metrics.cpu_percent <= 100
        assert 0 <= metrics.memory_percent <= 100
        assert metrics.memory_mb >= 0
        assert metrics.disk_usage_percent >= 0
        assert metrics.process_count >= 1

    @pytest.mark.asyncio
    async def test_health_check_performance(self):
        """Test health check performance."""
        monitor = HealthMonitor()
        
        # Mock all dependencies for speed
        with patch('src.monitoring.health_monitor.get_container') as mock_container:
            mock_container.return_value.get.return_value = MagicMock(
                is_healthy=MagicMock(return_value=True),
                is_ready=MagicMock(return_value=True),
                latency=0.05,
                get_metrics=MagicMock(return_value={}),
                get_database_metrics=AsyncMock(return_value={})
            )
            
            # Health check should be fast
            import time
            start = time.time()
            await monitor.check_health()
            duration = time.time() - start
            
            assert duration < 1.0  # Should complete within 1 second

    def test_health_status_degraded_calculation(self):
        """Test degraded status calculation."""
        monitor = HealthMonitor()
        
        # All healthy
        monitor._health_status = {
            "discord": ComponentHealth("discord", "healthy"),
            "database": ComponentHealth("database", "healthy"),
            "ai_service": ComponentHealth("ai_service", "healthy")
        }
        assert not monitor._is_degraded()
        
        # One unhealthy
        monitor._health_status["database"] = ComponentHealth("database", "unhealthy")
        assert monitor._is_degraded()
        
        # One degraded
        monitor._health_status["database"] = ComponentHealth("database", "degraded")
        assert monitor._is_degraded()