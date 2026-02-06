"""
AzabBot - Performance Metrics
=============================

Lightweight performance monitoring for bot operations.

DESIGN:
    Tracks timing metrics for various operations without significant overhead.
    Uses a rolling window to prevent unbounded memory growth.
    Thread-safe for Discord.py's async context.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Generator, List, Optional, Any
from functools import wraps

from src.core.config import NY_TZ
from src.core.logger import logger


# =============================================================================
# Constants
# =============================================================================

DEFAULT_WINDOW_SIZE = 100
"""Number of samples to keep per metric."""

SLOW_THRESHOLD_MS = 1000
"""Operations taking longer than this (ms) are logged as slow."""

LOG_SLOW_OPERATIONS = True
"""Whether to log slow operations when detected."""


# =============================================================================
# Metric Data Classes
# =============================================================================

@dataclass
class MetricSample:
    """Single metric sample."""
    value: float  # Duration in milliseconds
    timestamp: datetime = field(default_factory=lambda: datetime.now(NY_TZ))
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class MetricStats:
    """Aggregated statistics for a metric."""
    name: str
    count: int
    avg_ms: float
    min_ms: float
    max_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    slow_count: int  # Count of samples > SLOW_THRESHOLD_MS


# =============================================================================
# Metrics Collector
# =============================================================================

class MetricsCollector:
    """
    Collects and aggregates performance metrics.

    DESIGN:
        Uses a rolling window (deque) per metric to bound memory.
        All operations are O(1) for recording, O(n log n) for stats calculation.
        Thread-safe through Python's GIL.

    Attributes:
        metrics: Dictionary of metric name to sample deque.
        window_size: Maximum samples per metric.
    """

    def __init__(self, window_size: int = DEFAULT_WINDOW_SIZE) -> None:
        """
        Initialize the metrics collector.

        Args:
            window_size: Maximum samples to keep per metric.
        """
        self.metrics: Dict[str, deque] = {}
        self.window_size = window_size
        self._counters: Dict[str, int] = {}
        self._start_time = datetime.now(NY_TZ)

    def record(
        self,
        name: str,
        duration_ms: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record a metric sample.

        Args:
            name: Metric name (e.g., "db.query", "api.discord").
            duration_ms: Duration in milliseconds.
            metadata: Optional metadata dictionary.
        """
        if name not in self.metrics:
            self.metrics[name] = deque(maxlen=self.window_size)

        sample = MetricSample(value=duration_ms, metadata=metadata)
        self.metrics[name].append(sample)

        # Log slow operations
        if LOG_SLOW_OPERATIONS and duration_ms > SLOW_THRESHOLD_MS:
            logger.warning(f"Slow Operation Detected", [
                ("Metric", name),
                ("Duration", f"{duration_ms:.0f}ms"),
                ("Threshold", f"{SLOW_THRESHOLD_MS}ms"),
            ])

    def increment(self, name: str, amount: int = 1) -> None:
        """
        Increment a counter.

        Args:
            name: Counter name.
            amount: Amount to increment by.
        """
        self._counters[name] = self._counters.get(name, 0) + amount

    def get_counter(self, name: str) -> int:
        """Get counter value."""
        return self._counters.get(name, 0)

    def get_stats(self, name: str) -> Optional[MetricStats]:
        """
        Calculate statistics for a metric.

        Args:
            name: Metric name.

        Returns:
            MetricStats or None if no samples exist.
        """
        if name not in self.metrics or not self.metrics[name]:
            return None

        samples = list(self.metrics[name])
        values = sorted(s.value for s in samples)
        count = len(values)

        if count == 0:
            return None

        def percentile(data: List[float], p: float) -> float:
            """Calculate percentile value."""
            idx = int(len(data) * p / 100)
            return data[min(idx, len(data) - 1)]

        return MetricStats(
            name=name,
            count=count,
            avg_ms=sum(values) / count,
            min_ms=min(values),
            max_ms=max(values),
            p50_ms=percentile(values, 50),
            p95_ms=percentile(values, 95),
            p99_ms=percentile(values, 99),
            slow_count=sum(1 for v in values if v > SLOW_THRESHOLD_MS),
        )

    def get_all_stats(self) -> Dict[str, MetricStats]:
        """Get statistics for all metrics."""
        return {
            name: stats
            for name in self.metrics
            if (stats := self.get_stats(name)) is not None
        }

    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all metrics and counters.

        Returns:
            Dictionary with uptime, counters, and metric stats.
        """
        uptime = datetime.now(NY_TZ) - self._start_time
        return {
            "uptime_seconds": uptime.total_seconds(),
            "counters": dict(self._counters),
            "metrics": {
                name: {
                    "count": stats.count,
                    "avg_ms": round(stats.avg_ms, 2),
                    "p50_ms": round(stats.p50_ms, 2),
                    "p95_ms": round(stats.p95_ms, 2),
                    "max_ms": round(stats.max_ms, 2),
                    "slow_count": stats.slow_count,
                }
                for name, stats in self.get_all_stats().items()
            },
        }

    def clear(self) -> None:
        """Clear all metrics and counters."""
        self.metrics.clear()
        self._counters.clear()

    @contextmanager
    def timer(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> Generator[None, None, None]:
        """
        Context manager for timing operations.

        Args:
            name: Metric name.
            metadata: Optional metadata.

        Example:
            with metrics.timer("db.query"):
                result = db.execute(query)
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self.record(name, duration_ms, metadata)

    def timed(self, name: str) -> Callable:
        """
        Decorator for timing functions.

        Args:
            name: Metric name.

        Example:
            @metrics.timed("api.discord")
            async def call_api():
                ...
        """
        def decorator(func: Callable) -> Callable:
            if asyncio.iscoroutinefunction(func):
                @wraps(func)
                async def async_wrapper(*args, **kwargs):
                    start = time.perf_counter()
                    try:
                        return await func(*args, **kwargs)
                    finally:
                        duration_ms = (time.perf_counter() - start) * 1000
                        self.record(name, duration_ms)
                return async_wrapper
            else:
                @wraps(func)
                def sync_wrapper(*args, **kwargs):
                    start = time.perf_counter()
                    try:
                        return func(*args, **kwargs)
                    finally:
                        duration_ms = (time.perf_counter() - start) * 1000
                        self.record(name, duration_ms)
                return sync_wrapper
        return decorator


# =============================================================================
# Global Instance
# =============================================================================

metrics = MetricsCollector()
"""Global metrics collector instance."""


# =============================================================================
# Initialization
# =============================================================================

def init_metrics() -> None:
    """
    Initialize the metrics system and log startup.

    DESIGN:
        Called once at bot startup to log that metrics are ready.
        The global metrics instance is already created at module load.
    """
    logger.tree("Metrics System Initialized", [
        ("Window Size", str(metrics.window_size)),
        ("Slow Threshold", f"{SLOW_THRESHOLD_MS}ms"),
        ("Log Slow Ops", "Yes" if LOG_SLOW_OPERATIONS else "No"),
    ], emoji="📊")


# =============================================================================
# Convenience Functions
# =============================================================================

def record_metric(name: str, duration_ms: float, **metadata) -> None:
    """Record a metric to the global collector."""
    metrics.record(name, duration_ms, metadata if metadata else None)


def increment_counter(name: str, amount: int = 1) -> None:
    """Increment a counter in the global collector."""
    metrics.increment(name, amount)


def get_metrics_summary() -> Dict[str, Any]:
    """Get summary from the global collector."""
    return metrics.get_summary()


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    # Classes
    "MetricsCollector",
    "MetricSample",
    "MetricStats",
    # Global instance
    "metrics",
    # Initialization
    "init_metrics",
    # Convenience functions
    "record_metric",
    "increment_counter",
    "get_metrics_summary",
    # Constants
    "SLOW_THRESHOLD_MS",
    "LOG_SLOW_OPERATIONS",
]
