"""
AzabBot - Health Tracker Service
=================================

Tracks bot health metrics over time: latency, reconnections, rate limits.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional
from threading import Lock


@dataclass
class LatencyPoint:
    """Single latency measurement."""
    timestamp: float
    latency_ms: int


@dataclass
class HealthTracker:
    """Tracks bot health metrics over time."""

    # Latency history (last 60 points, ~1 hour at 1 min intervals)
    latency_history: deque = field(default_factory=lambda: deque(maxlen=60))

    # Reconnection tracking
    reconnect_count: int = 0
    last_reconnect: Optional[float] = None

    # Rate limit tracking
    rate_limit_hits: int = 0
    last_rate_limit: Optional[float] = None

    # Lock for thread safety
    _lock: Lock = field(default_factory=Lock)

    def record_latency(self, latency_ms: int) -> None:
        """Record a latency measurement."""
        with self._lock:
            self.latency_history.append(LatencyPoint(
                timestamp=time.time(),
                latency_ms=latency_ms,
            ))

    def record_reconnect(self) -> None:
        """Record a reconnection event."""
        with self._lock:
            self.reconnect_count += 1
            self.last_reconnect = time.time()

    def record_rate_limit(self) -> None:
        """Record a rate limit hit."""
        with self._lock:
            self.rate_limit_hits += 1
            self.last_rate_limit = time.time()

    def get_latency_history(self) -> List[dict]:
        """Get latency history as list of dicts."""
        with self._lock:
            return [
                {"timestamp": p.timestamp, "latency_ms": p.latency_ms}
                for p in self.latency_history
            ]

    def get_health_summary(self) -> dict:
        """Get health summary."""
        with self._lock:
            # Calculate average latency from last 10 points
            recent = list(self.latency_history)[-10:] if self.latency_history else []
            avg_latency = sum(p.latency_ms for p in recent) / len(recent) if recent else 0

            return {
                "reconnect_count": self.reconnect_count,
                "last_reconnect": self.last_reconnect,
                "rate_limit_hits": self.rate_limit_hits,
                "last_rate_limit": self.last_rate_limit,
                "avg_latency_ms": round(avg_latency, 1),
                "latency_points": len(self.latency_history),
            }


# Singleton instance
_health_tracker: Optional[HealthTracker] = None


def get_health_tracker() -> HealthTracker:
    """Get or create the health tracker singleton."""
    global _health_tracker
    if _health_tracker is None:
        _health_tracker = HealthTracker()
    return _health_tracker


__all__ = ["HealthTracker", "LatencyPoint", "get_health_tracker"]
