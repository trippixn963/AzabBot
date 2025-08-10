"""
Logging utilities to reduce code duplication.
Provides common logging patterns and helpers.
"""

from typing import Any, Dict, Optional
from functools import wraps
import time
import asyncio

from src.core.logger import get_logger

logger = get_logger()


def log_service_init(service_name: str):
    """Log service initialization start."""
    logger.log_info(f"🔧 {service_name}: Starting service initialization")


def log_service_ready(service_name: str, details: Optional[Dict] = None):
    """Log service ready status."""
    logger.log_info(f"✅ {service_name}: Service initialized successfully")
    if details:
        # Log details as part of the message since context param may not be available
        details_str = ", ".join([f"{k}={v}" for k, v in details.items()])
        logger.log_info(f"{service_name} ready: {details_str}")


def log_service_error(service_name: str, error: Exception):
    """Log service error."""
    logger.log_error(f"❌ {service_name}: Service initialization failed", exception=error)


def log_database_operation(
    operation: str,
    table: str,
    success: bool,
    details: Optional[Dict] = None
):
    """
    Log database operation result.
    
    Args:
        operation: Operation type (INSERT, UPDATE, DELETE, etc.)
        table: Table name
        success: Whether operation succeeded
        details: Additional context
    """
    context = {
        "operation": operation,
        "table": table,
        "success": success,
        **(details or {})
    }
    
    if success:
        logger.log_debug(f"Database {operation} on {table}", context=context)
    else:
        logger.log_warning(f"Database {operation} failed on {table}", context=context)


def log_discord_event(
    event_type: str,
    user: Optional[str] = None,
    channel: Optional[str] = None,
    details: Optional[Dict] = None
):
    """
    Log Discord event with standard format.
    
    Args:
        event_type: Type of Discord event
        user: User involved
        channel: Channel involved
        details: Additional context
    """
    context = {"event": event_type}
    
    if user:
        context["user"] = user
    if channel:
        context["channel"] = channel
    if details:
        context.update(details)
    
    logger.log_debug(f"Discord event: {event_type}", context=context)


def log_api_call(
    service: str,
    endpoint: str,
    success: bool,
    response_time: Optional[float] = None,
    details: Optional[Dict] = None
):
    """
    Log API call with standard format.
    
    Args:
        service: API service name
        endpoint: API endpoint
        success: Whether call succeeded
        response_time: Response time in seconds
        details: Additional context
    """
    context = {
        "service": service,
        "endpoint": endpoint,
        "success": success
    }
    
    if response_time:
        context["response_time_ms"] = f"{response_time * 1000:.2f}"
    if details:
        context.update(details)
    
    if success:
        logger.log_debug(f"API call to {service}", context=context)
    else:
        logger.log_warning(f"API call failed to {service}", context=context)


def with_performance_logging(func_name: Optional[str] = None):
    """
    Decorator to log function performance.
    
    Args:
        func_name: Optional custom function name for logging
    """
    def decorator(func):
        name = func_name or func.__name__
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                elapsed = time.time() - start_time
                
                if elapsed > 1.0:  # Log slow operations
                    logger.log_debug(
                        f"Slow operation: {name}",
                        context={
                            "duration_seconds": f"{elapsed:.2f}",
                            "function": name
                        }
                    )
                
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                logger.log_error(
                    f"Operation failed: {name}",
                    exception=e,
                    context={
                        "duration_seconds": f"{elapsed:.2f}",
                        "function": name
                    }
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                
                if elapsed > 1.0:  # Log slow operations
                    logger.log_debug(
                        f"Slow operation: {name}",
                        context={
                            "duration_seconds": f"{elapsed:.2f}",
                            "function": name
                        }
                    )
                
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                logger.log_error(
                    f"Operation failed: {name}",
                    exception=e,
                    context={
                        "duration_seconds": f"{elapsed:.2f}",
                        "function": name
                    }
                )
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


def log_batch_operation(
    operation: str,
    total_items: int,
    processed: int,
    failed: int = 0,
    details: Optional[Dict] = None
):
    """
    Log batch operation progress.
    
    Args:
        operation: Operation name
        total_items: Total items to process
        processed: Items processed
        failed: Items that failed
        details: Additional context
    """
    success_rate = (processed - failed) / processed * 100 if processed > 0 else 0
    
    context = {
        "operation": operation,
        "total": total_items,
        "processed": processed,
        "failed": failed,
        "success_rate": f"{success_rate:.1f}%",
        **(details or {})
    }
    
    if failed > 0:
        logger.log_warning(f"Batch operation completed with failures: {operation}", context=context)
    else:
        logger.log_info(f"Batch operation completed: {operation}", context=context)


def log_state_change(
    component: str,
    old_state: Any,
    new_state: Any,
    reason: Optional[str] = None
):
    """
    Log state change in component.
    
    Args:
        component: Component name
        old_state: Previous state
        new_state: New state
        reason: Reason for change
    """
    context = {
        "component": component,
        "old_state": str(old_state),
        "new_state": str(new_state)
    }
    
    if reason:
        context["reason"] = reason
    
    logger.log_info(f"State change: {component}", context=context)


class LogContext:
    """Context manager for grouped logging."""
    
    def __init__(self, operation: str, **context):
        self.operation = operation
        self.context = context
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        logger.log_debug(
            f"Starting: {self.operation}",
            context=self.context
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.time() - self.start_time
        
        if exc_type:
            logger.log_error(
                f"Failed: {self.operation}",
                exception=exc_val,
                context={
                    **self.context,
                    "duration_seconds": f"{elapsed:.2f}",
                    "error_type": exc_type.__name__
                }
            )
        else:
            logger.log_debug(
                f"Completed: {self.operation}",
                context={
                    **self.context,
                    "duration_seconds": f"{elapsed:.2f}"
                }
            )
    
    async def __aenter__(self):
        return self.__enter__()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return self.__exit__(exc_type, exc_val, exc_tb)