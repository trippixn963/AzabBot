"""
Circuit Breaker pattern implementation for external service calls.
Prevents cascading failures and provides graceful degradation.
"""

import asyncio
import time
from enum import Enum
from typing import Any, Callable, Optional
from functools import wraps
from dataclasses import dataclass, field
from collections import deque

from src.core.logger import get_logger

logger = get_logger()


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failure threshold exceeded, blocking calls
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5  # Failures before opening
    success_threshold: int = 2  # Successes in half-open before closing
    timeout: float = 60.0  # Seconds before trying half-open
    window_size: int = 10  # Rolling window for failure rate
    failure_rate_threshold: float = 0.5  # Failure rate to open circuit


@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker monitoring."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    last_failure_time: Optional[float] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    state_changes: list = field(default_factory=list)
    recent_calls: deque = field(default_factory=lambda: deque(maxlen=100))


class CircuitBreaker:
    """Circuit breaker implementation."""
    
    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        fallback_function: Optional[Callable] = None
    ):
        """
        Initialize circuit breaker.
        
        Args:
            name: Name for this circuit breaker
            config: Configuration settings
            fallback_function: Function to call when circuit is open
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.fallback_function = fallback_function
        
        self.state = CircuitState.CLOSED
        self.stats = CircuitBreakerStats()
        self._last_open_time: Optional[float] = None
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function through circuit breaker.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result or fallback result
        """
        async with self._lock:
            # Check if we should transition states
            await self._check_state_transition()
            
            if self.state == CircuitState.OPEN:
                return await self._handle_open_circuit(func, *args, **kwargs)
            
            try:
                # Execute the function
                result = await self._execute_function(func, *args, **kwargs)
                await self._record_success()
                return result
                
            except Exception as e:
                await self._record_failure(e)
                
                # Re-raise or return fallback
                if self.fallback_function:
                    return await self._execute_fallback(*args, **kwargs)
                raise
    
    async def _execute_function(self, func: Callable, *args, **kwargs) -> Any:
        """Execute the actual function."""
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)
    
    async def _execute_fallback(self, *args, **kwargs) -> Any:
        """Execute fallback function."""
        if not self.fallback_function:
            return None
            
        if asyncio.iscoroutinefunction(self.fallback_function):
            return await self.fallback_function(*args, **kwargs)
        return self.fallback_function(*args, **kwargs)
    
    async def _check_state_transition(self):
        """Check if circuit breaker should transition states."""
        current_time = time.time()
        
        if self.state == CircuitState.OPEN:
            # Check if timeout has passed
            if self._last_open_time and \
               (current_time - self._last_open_time) >= self.config.timeout:
                await self._transition_to_half_open()
        
        elif self.state == CircuitState.HALF_OPEN:
            # Half-open state is handled after execution
            pass
    
    async def _record_success(self):
        """Record successful call."""
        self.stats.total_calls += 1
        self.stats.successful_calls += 1
        self.stats.consecutive_successes += 1
        self.stats.consecutive_failures = 0
        self.stats.recent_calls.append((time.time(), True))
        
        if self.state == CircuitState.HALF_OPEN:
            if self.stats.consecutive_successes >= self.config.success_threshold:
                await self._transition_to_closed()
    
    async def _record_failure(self, error: Exception):
        """Record failed call."""
        current_time = time.time()
        self.stats.total_calls += 1
        self.stats.failed_calls += 1
        self.stats.consecutive_failures += 1
        self.stats.consecutive_successes = 0
        self.stats.last_failure_time = current_time
        self.stats.recent_calls.append((current_time, False))
        
        logger.log_warning(
            f"Circuit breaker {self.name} recorded failure",
            context={
                "error": str(error),
                "consecutive_failures": self.stats.consecutive_failures,
                "state": self.state.value
            }
        )
        
        # Check if we should open the circuit
        if self.state == CircuitState.CLOSED:
            if self._should_open_circuit():
                await self._transition_to_open()
        
        elif self.state == CircuitState.HALF_OPEN:
            # Single failure in half-open reopens circuit
            await self._transition_to_open()
    
    def _should_open_circuit(self) -> bool:
        """Check if circuit should open based on failure rate."""
        # Check consecutive failures
        if self.stats.consecutive_failures >= self.config.failure_threshold:
            return True
        
        # Check failure rate in window
        if len(self.stats.recent_calls) >= self.config.window_size:
            recent_window = list(self.stats.recent_calls)[-self.config.window_size:]
            failure_count = sum(1 for _, success in recent_window if not success)
            failure_rate = failure_count / len(recent_window)
            
            if failure_rate >= self.config.failure_rate_threshold:
                return True
        
        return False
    
    async def _transition_to_open(self):
        """Transition to open state."""
        self.state = CircuitState.OPEN
        self._last_open_time = time.time()
        self.stats.state_changes.append((time.time(), "OPEN"))
        
        logger.log_warning(
            f"Circuit breaker {self.name} opened",
            context={
                "failures": self.stats.consecutive_failures,
                "total_calls": self.stats.total_calls
            }
        )
    
    async def _transition_to_half_open(self):
        """Transition to half-open state."""
        self.state = CircuitState.HALF_OPEN
        self.stats.consecutive_failures = 0
        self.stats.consecutive_successes = 0
        self.stats.state_changes.append((time.time(), "HALF_OPEN"))
        
        logger.log_info(f"Circuit breaker {self.name} half-open for testing")
    
    async def _transition_to_closed(self):
        """Transition to closed state."""
        self.state = CircuitState.CLOSED
        self.stats.consecutive_failures = 0
        self.stats.state_changes.append((time.time(), "CLOSED"))
        
        logger.log_info(f"Circuit breaker {self.name} closed (recovered)")
    
    async def _handle_open_circuit(self, func: Callable, *args, **kwargs) -> Any:
        """Handle call when circuit is open."""
        logger.log_debug(
            f"Circuit breaker {self.name} blocked call (open)",
            context={"function": func.__name__}
        )
        
        if self.fallback_function:
            return await self._execute_fallback(*args, **kwargs)
        
        raise CircuitBreakerOpen(
            f"Circuit breaker {self.name} is open",
            circuit_name=self.name,
            last_failure_time=self.stats.last_failure_time
        )
    
    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        success_rate = (
            self.stats.successful_calls / self.stats.total_calls
            if self.stats.total_calls > 0 else 0
        )
        
        return {
            "name": self.name,
            "state": self.state.value,
            "total_calls": self.stats.total_calls,
            "successful_calls": self.stats.successful_calls,
            "failed_calls": self.stats.failed_calls,
            "success_rate": f"{success_rate:.2%}",
            "consecutive_failures": self.stats.consecutive_failures,
            "consecutive_successes": self.stats.consecutive_successes,
            "last_failure_time": self.stats.last_failure_time
        }
    
    def reset(self):
        """Reset circuit breaker to initial state."""
        self.state = CircuitState.CLOSED
        self.stats = CircuitBreakerStats()
        self._last_open_time = None
        logger.log_info(f"Circuit breaker {self.name} reset")


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is open."""
    
    def __init__(self, message: str, circuit_name: str, last_failure_time: Optional[float]):
        super().__init__(message)
        self.circuit_name = circuit_name
        self.last_failure_time = last_failure_time


# Global registry of circuit breakers
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    config: Optional[CircuitBreakerConfig] = None,
    fallback_function: Optional[Callable] = None
) -> CircuitBreaker:
    """
    Get or create a circuit breaker.
    
    Args:
        name: Circuit breaker name
        config: Configuration
        fallback_function: Fallback function
        
    Returns:
        Circuit breaker instance
    """
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name, config, fallback_function)
    return _circuit_breakers[name]


def circuit_breaker(
    name: Optional[str] = None,
    config: Optional[CircuitBreakerConfig] = None,
    fallback_function: Optional[Callable] = None
):
    """
    Decorator to apply circuit breaker pattern.
    
    Args:
        name: Circuit breaker name (defaults to function name)
        config: Circuit breaker configuration
        fallback_function: Function to call when circuit is open
    """
    def decorator(func: Callable) -> Callable:
        cb_name = name or f"{func.__module__}.{func.__name__}"
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            cb = get_circuit_breaker(cb_name, config, fallback_function)
            return await cb.call(func, *args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # For sync functions, we need to run in event loop
            cb = get_circuit_breaker(cb_name, config, fallback_function)
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(cb.call(func, *args, **kwargs))
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


def get_all_circuit_breaker_stats() -> list[dict]:
    """Get statistics for all circuit breakers."""
    return [cb.get_stats() for cb in _circuit_breakers.values()]