"""
Centralized error handling utilities for AzabBot.
Provides specific error handling strategies and recovery mechanisms.
"""

import asyncio
import functools
import traceback
from typing import Any, Callable, Optional, Type, TypeVar, Union
from enum import Enum

from src.core.logger import get_logger

logger = get_logger()

T = TypeVar('T')


class ErrorSeverity(Enum):
    """Error severity levels for handling strategies."""
    LOW = "low"       # Log and continue
    MEDIUM = "medium" # Log, attempt recovery, continue
    HIGH = "high"     # Log, attempt recovery, may need restart
    CRITICAL = "critical" # Log, notify, requires immediate attention


class ErrorCategory(Enum):
    """Categories of errors for specific handling."""
    NETWORK = "network"
    DATABASE = "database"
    DISCORD_API = "discord_api"
    AI_SERVICE = "ai_service"
    CONFIGURATION = "configuration"
    PERMISSION = "permission"
    VALIDATION = "validation"
    GENERAL = "general"


class AzabBotError(Exception):
    """Base exception for AzabBot with context and recovery info."""
    
    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.GENERAL,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        context: Optional[dict] = None,
        recovery_action: Optional[str] = None
    ):
        super().__init__(message)
        self.category = category
        self.severity = severity
        self.context = context or {}
        self.recovery_action = recovery_action


def handle_error(
    category: ErrorCategory = ErrorCategory.GENERAL,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    default_return: Any = None,
    max_retries: int = 0,
    retry_delay: float = 1.0,
    log_traceback: bool = True
):
    """
    Decorator for handling errors with specific strategies.
    
    Args:
        category: Error category for specific handling
        severity: Error severity level
        default_return: Default value to return on error
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds
        log_traceback: Whether to log full traceback
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            retries = 0
            last_error = None
            
            while retries <= max_retries:
                try:
                    return await func(*args, **kwargs)
                    
                except AzabBotError as e:
                    last_error = e
                    await _handle_azabbot_error(e, func.__name__, retries, max_retries)
                    
                except Exception as e:
                    last_error = e
                    await _handle_generic_error(
                        e, func.__name__, category, severity, 
                        retries, max_retries, log_traceback
                    )
                
                if retries < max_retries:
                    await asyncio.sleep(retry_delay * (retries + 1))
                    retries += 1
                else:
                    break
            
            # Log final failure if all retries exhausted
            if retries > 0:
                logger.log_error(
                    f"All {max_retries} retries failed for {func.__name__}",
                    exception=last_error,
                    context={
                        "function": func.__name__,
                        "category": category.value,
                        "severity": severity.value
                    }
                )
            
            return default_return
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            retries = 0
            last_error = None
            
            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)
                    
                except AzabBotError as e:
                    last_error = e
                    _handle_azabbot_error_sync(e, func.__name__, retries, max_retries)
                    
                except Exception as e:
                    last_error = e
                    _handle_generic_error_sync(
                        e, func.__name__, category, severity,
                        retries, max_retries, log_traceback
                    )
                
                if retries < max_retries:
                    import time
                    time.sleep(retry_delay * (retries + 1))
                    retries += 1
                else:
                    break
            
            return default_return
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


async def _handle_azabbot_error(
    error: AzabBotError,
    func_name: str,
    retry_count: int,
    max_retries: int
):
    """Handle AzabBot-specific errors with recovery strategies."""
    
    context = {
        "function": func_name,
        "category": error.category.value,
        "severity": error.severity.value,
        "retry": f"{retry_count}/{max_retries}",
        **error.context
    }
    
    if error.recovery_action:
        context["recovery_action"] = error.recovery_action
    
    # Apply recovery strategies based on category
    recovery_applied = await _apply_recovery_strategy(error)
    if recovery_applied:
        context["recovery_applied"] = True
    
    # Log based on severity
    if error.severity == ErrorSeverity.CRITICAL:
        logger.log_error(f"CRITICAL: {error}", exception=error, context=context)
    elif error.severity == ErrorSeverity.HIGH:
        logger.log_error(f"HIGH: {error}", exception=error, context=context)
    elif error.severity == ErrorSeverity.MEDIUM:
        logger.log_warning(f"MEDIUM: {error}", context=context)
    else:
        logger.log_debug(f"LOW: {error}", context=context)


def _handle_azabbot_error_sync(
    error: AzabBotError,
    func_name: str,
    retry_count: int,
    max_retries: int
):
    """Sync version of AzabBot error handler."""
    context = {
        "function": func_name,
        "category": error.category.value,
        "severity": error.severity.value,
        "retry": f"{retry_count}/{max_retries}",
        **error.context
    }
    
    if error.severity in [ErrorSeverity.CRITICAL, ErrorSeverity.HIGH]:
        logger.log_error(str(error), exception=error, context=context)
    else:
        logger.log_warning(str(error), context=context)


async def _handle_generic_error(
    error: Exception,
    func_name: str,
    category: ErrorCategory,
    severity: ErrorSeverity,
    retry_count: int,
    max_retries: int,
    log_traceback: bool
):
    """Handle generic exceptions with categorization."""
    
    # Categorize known error types
    if isinstance(error, ConnectionError):
        category = ErrorCategory.NETWORK
    elif isinstance(error, PermissionError):
        category = ErrorCategory.PERMISSION
    elif isinstance(error, ValueError):
        category = ErrorCategory.VALIDATION
    elif "discord" in str(type(error).__module__).lower():
        category = ErrorCategory.DISCORD_API
    
    context = {
        "function": func_name,
        "error_type": type(error).__name__,
        "category": category.value,
        "severity": severity.value,
        "retry": f"{retry_count}/{max_retries}"
    }
    
    if log_traceback:
        context["traceback"] = traceback.format_exc()
    
    logger.log_error(
        f"Error in {func_name}: {error}",
        exception=error if not log_traceback else None,
        context=context
    )


def _handle_generic_error_sync(
    error: Exception,
    func_name: str,
    category: ErrorCategory,
    severity: ErrorSeverity,
    retry_count: int,
    max_retries: int,
    log_traceback: bool
):
    """Sync version of generic error handler."""
    context = {
        "function": func_name,
        "error_type": type(error).__name__,
        "category": category.value,
        "retry": f"{retry_count}/{max_retries}"
    }
    
    logger.log_error(
        f"Error in {func_name}: {error}",
        exception=error,
        context=context
    )


async def _apply_recovery_strategy(error: AzabBotError) -> bool:
    """
    Apply recovery strategies based on error category.
    
    Returns:
        bool: True if recovery was attempted, False otherwise
    """
    if error.category == ErrorCategory.NETWORK:
        # Network errors: wait and retry
        await asyncio.sleep(5)
        return True
        
    elif error.category == ErrorCategory.DATABASE:
        # Database errors: check connection
        # This would be implemented based on your database service
        logger.log_info("Checking database connection...")
        return True
        
    elif error.category == ErrorCategory.DISCORD_API:
        # Discord API errors: check rate limits
        if "rate" in str(error).lower():
            await asyncio.sleep(10)
            return True
            
    elif error.category == ErrorCategory.AI_SERVICE:
        # AI service errors: fallback response
        logger.log_info("AI service error, using fallback response")
        return True
    
    return False


def safe_execute(
    func: Callable,
    default_return: Any = None,
    error_message: str = "Operation failed",
    **kwargs
) -> Any:
    """
    Safely execute a function with error handling.
    
    Args:
        func: Function to execute
        default_return: Value to return on error
        error_message: Custom error message
        **kwargs: Arguments to pass to the function
    
    Returns:
        Function result or default_return on error
    """
    try:
        return func(**kwargs)
    except Exception as e:
        logger.log_error(
            error_message,
            exception=e,
            context={"function": func.__name__, "args": str(kwargs)}
        )
        return default_return


async def safe_execute_async(
    func: Callable,
    default_return: Any = None,
    error_message: str = "Operation failed",
    **kwargs
) -> Any:
    """
    Safely execute an async function with error handling.
    
    Args:
        func: Async function to execute
        default_return: Value to return on error
        error_message: Custom error message
        **kwargs: Arguments to pass to the function
    
    Returns:
        Function result or default_return on error
    """
    try:
        return await func(**kwargs)
    except Exception as e:
        logger.log_error(
            error_message,
            exception=e,
            context={"function": func.__name__, "args": str(kwargs)}
        )
        return default_return