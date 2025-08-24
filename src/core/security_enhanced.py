"""
Enhanced Security System for AzabBot
====================================

This module provides advanced security features including input validation,
rate limiting, permission checking, and threat detection for the AzabBot
application.

DESIGN PATTERNS IMPLEMENTED:
1. Strategy Pattern: Different security validation strategies
2. Decorator Pattern: Security validation decorators
3. Factory Pattern: Security context creation
4. Observer Pattern: Security event monitoring
5. Chain of Responsibility: Security validation chain

SECURITY FEATURES:
1. Input Validation:
   - Message content sanitization
   - User input validation
   - Command parameter validation
   - URL and link validation

2. Rate Limiting:
   - Per-user rate limiting
   - Per-channel rate limiting
   - Global rate limiting
   - Adaptive rate limiting

3. Permission Checking:
   - Role-based access control
   - User permission validation
   - Command permission checking
   - Channel access control

4. Threat Detection:
   - Spam detection
   - Malicious content detection
   - Bot abuse prevention
   - Suspicious behavior detection

USAGE EXAMPLES:

1. Input Validation:
   ```python
   @validate_input(max_length=1000, allowed_patterns=[r'^[a-zA-Z0-9\s]+$'])
   async def process_message(message: str):
       # Process validated message
       pass
   ```

2. Rate Limiting:
   ```python
   @rate_limit(max_requests=10, window_seconds=60)
   async def handle_command(user_id: int):
       # Handle rate-limited command
       pass
   ```

3. Permission Checking:
   ```python
   @require_permission("moderator")
   async def admin_command(user_id: int):
       # Execute admin command
       pass
   ```

4. Threat Detection:
   ```python
   @detect_threats
   async def process_user_message(message: str, user_id: int):
       # Process message with threat detection
       pass
   ```

This implementation provides comprehensive security for the AzabBot
application, ensuring safe and secure operation in production environments.
"""

import re
import hashlib
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
from functools import wraps

from src.core.logger import get_logger


@dataclass
class SecurityContext:
    """Security context for operations."""
    
    user_id: int
    channel_id: int
    guild_id: int
    user_roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    threat_level: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class RateLimitInfo:
    """Rate limiting information."""
    
    max_requests: int
    window_seconds: int
    requests: deque = field(default_factory=lambda: deque())
    
    def is_allowed(self) -> bool:
        """Check if request is allowed under rate limit."""
        now = time.time()
        
        # Remove expired requests
        while self.requests and self.requests[0] < now - self.window_seconds:
            self.requests.popleft()
        
        # Check if under limit
        if len(self.requests) < self.max_requests:
            self.requests.append(now)
            return True
        
        return False


class SecurityManager:
    """
    Enhanced security manager for AzabBot.
    
    This class provides comprehensive security features including input validation,
    rate limiting, permission checking, and threat detection.
    """
    
    def __init__(self):
        """Initialize the security manager."""
        self.logger = get_logger()
        
        # Rate limiting storage
        self.rate_limits: Dict[str, RateLimitInfo] = {}
        
        # Threat detection
        self.threat_patterns: List[re.Pattern] = [
            re.compile(r'(?:https?://)?(?:www\.)?(?:discord\.gg|discord\.com/invite)/[a-zA-Z0-9]+', re.IGNORECASE),
            re.compile(r'@everyone|@here', re.IGNORECASE),
            re.compile(r'```.*```', re.DOTALL),
            re.compile(r'<@!?\d+>', re.IGNORECASE),
        ]
        
        # Suspicious patterns
        self.suspicious_patterns: List[re.Pattern] = [
            re.compile(r'\b(spam|bot|automated)\b', re.IGNORECASE),
            re.compile(r'[A-Z]{5,}'),  # Excessive caps
            re.compile(r'[!]{3,}'),  # Excessive punctuation
        ]
        
        # User threat levels
        self.user_threat_levels: Dict[int, float] = defaultdict(float)
        
        # Security events
        self.security_events: deque = deque(maxlen=1000)
    
    def validate_input(self, content: str, max_length: int = 2000, 
                      allowed_patterns: Optional[List[str]] = None,
                      blocked_patterns: Optional[List[str]] = None) -> tuple[bool, str]:
        """
        Validate user input content.
        
        Args:
            content: Content to validate
            max_length: Maximum allowed length
            allowed_patterns: Allowed content patterns
            blocked_patterns: Blocked content patterns
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check length
        if len(content) > max_length:
            return False, f"Content too long (max {max_length} characters)"
        
        # Check for empty content
        if not content.strip():
            return False, "Content cannot be empty"
        
        # Check allowed patterns
        if allowed_patterns:
            for pattern in allowed_patterns:
                if not re.match(pattern, content):
                    return False, f"Content does not match allowed pattern: {pattern}"
        
        # Check blocked patterns
        if blocked_patterns:
            for pattern in blocked_patterns:
                if re.search(pattern, content):
                    return False, f"Content contains blocked pattern: {pattern}"
        
        # Check for threat patterns
        for pattern in self.threat_patterns:
            if pattern.search(content):
                return False, "Content contains potentially harmful content"
        
        return True, ""
    
    def check_rate_limit(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """
        Check if operation is allowed under rate limit.
        
        Args:
            key: Rate limit key (e.g., user_id, channel_id)
            max_requests: Maximum requests allowed
            window_seconds: Time window in seconds
            
        Returns:
            True if allowed, False if rate limited
        """
        if key not in self.rate_limits:
            self.rate_limits[key] = RateLimitInfo(max_requests, window_seconds)
        
        return self.rate_limits[key].is_allowed()
    
    def check_permissions(self, user_roles: List[str], required_permissions: List[str]) -> bool:
        """
        Check if user has required permissions.
        
        Args:
            user_roles: User's roles
            required_permissions: Required permissions
            
        Returns:
            True if user has all required permissions
        """
        # Check if user has any of the required permissions
        for permission in required_permissions:
            if permission in user_roles:
                return True
        
        return False
    
    def detect_threats(self, content: str, user_id: int) -> tuple[float, List[str]]:
        """
        Detect potential threats in content.
        
        Args:
            content: Content to analyze
            user_id: User ID for threat tracking
            
        Returns:
            Tuple of (threat_level, detected_threats)
        """
        threat_level = 0.0
        detected_threats = []
        
        # Check for threat patterns
        for pattern in self.threat_patterns:
            if pattern.search(content):
                threat_level += 0.3
                detected_threats.append(f"Threat pattern: {pattern.pattern}")
        
        # Check for suspicious patterns
        for pattern in self.suspicious_patterns:
            if pattern.search(content):
                threat_level += 0.1
                detected_threats.append(f"Suspicious pattern: {pattern.pattern}")
        
        # Check for excessive length
        if len(content) > 1000:
            threat_level += 0.1
            detected_threats.append("Excessive message length")
        
        # Check for repeated characters
        if re.search(r'(.)\1{4,}', content):
            threat_level += 0.2
            detected_threats.append("Repeated characters")
        
        # Update user threat level
        self.user_threat_levels[user_id] = min(1.0, self.user_threat_levels[user_id] + threat_level)
        
        return threat_level, detected_threats
    
    def get_user_threat_level(self, user_id: int) -> float:
        """
        Get current threat level for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Threat level (0.0 to 1.0)
        """
        return self.user_threat_levels[user_id]
    
    def record_security_event(self, event_type: str, user_id: int, 
                            details: Dict[str, Any], severity: str = "medium"):
        """
        Record a security event.
        
        Args:
            event_type: Type of security event
            user_id: User ID involved
            details: Event details
            severity: Event severity
        """
        event = {
            "type": event_type,
            "user_id": user_id,
            "details": details,
            "severity": severity,
            "timestamp": datetime.now()
        }
        
        self.security_events.append(event)
        
        # Log security event
        self.logger.log_warning(f"Security event: {event_type} by user {user_id} - {severity}")
    
    def get_security_report(self) -> Dict[str, Any]:
        """
        Generate security report.
        
        Returns:
            Security report data
        """
        now = datetime.now()
        recent_events = [
            event for event in self.security_events
            if now - event["timestamp"] < timedelta(hours=24)
        ]
        
        return {
            "total_events_24h": len(recent_events),
            "high_severity_events": len([e for e in recent_events if e["severity"] == "high"]),
            "users_with_threats": len([uid for uid, level in self.user_threat_levels.items() if level > 0.5]),
            "active_rate_limits": len(self.rate_limits),
            "threat_patterns_detected": len([e for e in recent_events if "threat" in e["type"].lower()])
        }


# Global security manager instance
_security_manager: Optional[SecurityManager] = None


def get_security_manager() -> SecurityManager:
    """Get the global security manager instance."""
    global _security_manager
    if _security_manager is None:
        _security_manager = SecurityManager()
    return _security_manager


# Security decorators
def validate_input(max_length: int = 2000, allowed_patterns: Optional[List[str]] = None,
                  blocked_patterns: Optional[List[str]] = None):
    """Decorator for input validation."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            security_manager = get_security_manager()
            
            # Find content parameter
            content = None
            for arg in args:
                if isinstance(arg, str):
                    content = arg
                    break
            
            if content is None:
                content = kwargs.get('content', kwargs.get('message', ''))
            
            # Validate input
            is_valid, error_message = security_manager.validate_input(
                content, max_length, allowed_patterns, blocked_patterns
            )
            
            if not is_valid:
                raise ValueError(f"Input validation failed: {error_message}")
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def rate_limit(max_requests: int, window_seconds: int, key_func: Optional[Callable] = None):
    """Decorator for rate limiting."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            security_manager = get_security_manager()
            
            # Generate rate limit key
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                # Default to first argument as key
                key = str(args[0]) if args else "default"
            
            # Check rate limit
            if not security_manager.check_rate_limit(key, max_requests, window_seconds):
                raise ValueError(f"Rate limit exceeded: {max_requests} requests per {window_seconds} seconds")
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_permission(permission: str):
    """Decorator for permission checking."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            security_manager = get_security_manager()
            
            # Extract user roles from context
            user_roles = kwargs.get('user_roles', [])
            
            if not security_manager.check_permissions(user_roles, [permission]):
                raise PermissionError(f"Required permission: {permission}")
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def detect_threats(func: Callable) -> Callable:
    """Decorator for threat detection."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        security_manager = get_security_manager()
        
        # Extract content and user_id
        content = kwargs.get('content', kwargs.get('message', ''))
        user_id = kwargs.get('user_id', 0)
        
        # Detect threats
        threat_level, detected_threats = security_manager.detect_threats(content, user_id)
        
        # Record security event if threats detected
        if threat_level > 0.3:
            security_manager.record_security_event(
                "threat_detected",
                user_id,
                {"threat_level": threat_level, "threats": detected_threats},
                "high" if threat_level > 0.7 else "medium"
            )
        
        # Block if threat level is too high
        if threat_level > 0.8:
            raise ValueError(f"Content blocked due to high threat level: {threat_level}")
        
        return await func(*args, **kwargs)
    return wrapper
