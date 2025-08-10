"""
Input validation utilities for AzabBot.
Provides comprehensive validation for all user inputs.
"""

import re
from typing import Any, List, Optional, Union
from datetime import datetime
from functools import wraps

from src.utils.error_handler import AzabBotError, ErrorCategory, ErrorSeverity
from src.core.logger import get_logger

logger = get_logger()


class ValidationError(AzabBotError):
    """Validation error with details."""
    
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Any = None
    ):
        super().__init__(
            message,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.LOW,
            context={"field": field, "value": str(value)[:100]}
        )
        self.field = field
        self.value = value


class Validator:
    """Base validator class."""
    
    def validate(self, value: Any, field_name: str = "value") -> Any:
        """Validate value and return cleaned value."""
        raise NotImplementedError
    
    def __call__(self, value: Any, field_name: str = "value") -> Any:
        """Allow validator to be called directly."""
        return self.validate(value, field_name)


class StringValidator(Validator):
    """String validation."""
    
    def __init__(
        self,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        pattern: Optional[str] = None,
        allowed_chars: Optional[str] = None,
        strip: bool = True,
        lowercase: bool = False,
        uppercase: bool = False
    ):
        self.min_length = min_length
        self.max_length = max_length
        self.pattern = re.compile(pattern) if pattern else None
        self.allowed_chars = set(allowed_chars) if allowed_chars else None
        self.strip = strip
        self.lowercase = lowercase
        self.uppercase = uppercase
    
    def validate(self, value: Any, field_name: str = "value") -> str:
        """Validate string value."""
        if value is None:
            raise ValidationError(f"{field_name} cannot be None", field_name, value)
        
        # Convert to string
        str_value = str(value)
        
        # Strip whitespace
        if self.strip:
            str_value = str_value.strip()
        
        # Check length
        if self.min_length is not None and len(str_value) < self.min_length:
            raise ValidationError(
                f"{field_name} must be at least {self.min_length} characters",
                field_name, value
            )
        
        if self.max_length is not None and len(str_value) > self.max_length:
            raise ValidationError(
                f"{field_name} must be at most {self.max_length} characters",
                field_name, value
            )
        
        # Check pattern
        if self.pattern and not self.pattern.match(str_value):
            raise ValidationError(
                f"{field_name} does not match required pattern",
                field_name, value
            )
        
        # Check allowed characters
        if self.allowed_chars:
            invalid_chars = set(str_value) - self.allowed_chars
            if invalid_chars:
                raise ValidationError(
                    f"{field_name} contains invalid characters: {invalid_chars}",
                    field_name, value
                )
        
        # Apply transformations
        if self.lowercase:
            str_value = str_value.lower()
        elif self.uppercase:
            str_value = str_value.upper()
        
        return str_value


class IntegerValidator(Validator):
    """Integer validation."""
    
    def __init__(
        self,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
        allowed_values: Optional[List[int]] = None
    ):
        self.min_value = min_value
        self.max_value = max_value
        self.allowed_values = set(allowed_values) if allowed_values else None
    
    def validate(self, value: Any, field_name: str = "value") -> int:
        """Validate integer value."""
        try:
            int_value = int(value)
        except (ValueError, TypeError):
            raise ValidationError(
                f"{field_name} must be an integer",
                field_name, value
            )
        
        # Check range
        if self.min_value is not None and int_value < self.min_value:
            raise ValidationError(
                f"{field_name} must be at least {self.min_value}",
                field_name, value
            )
        
        if self.max_value is not None and int_value > self.max_value:
            raise ValidationError(
                f"{field_name} must be at most {self.max_value}",
                field_name, value
            )
        
        # Check allowed values
        if self.allowed_values and int_value not in self.allowed_values:
            raise ValidationError(
                f"{field_name} must be one of {self.allowed_values}",
                field_name, value
            )
        
        return int_value


class FloatValidator(Validator):
    """Float validation."""
    
    def __init__(
        self,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        precision: Optional[int] = None
    ):
        self.min_value = min_value
        self.max_value = max_value
        self.precision = precision
    
    def validate(self, value: Any, field_name: str = "value") -> float:
        """Validate float value."""
        try:
            float_value = float(value)
        except (ValueError, TypeError):
            raise ValidationError(
                f"{field_name} must be a number",
                field_name, value
            )
        
        # Check range
        if self.min_value is not None and float_value < self.min_value:
            raise ValidationError(
                f"{field_name} must be at least {self.min_value}",
                field_name, value
            )
        
        if self.max_value is not None and float_value > self.max_value:
            raise ValidationError(
                f"{field_name} must be at most {self.max_value}",
                field_name, value
            )
        
        # Apply precision
        if self.precision is not None:
            float_value = round(float_value, self.precision)
        
        return float_value


class BooleanValidator(Validator):
    """Boolean validation."""
    
    def validate(self, value: Any, field_name: str = "value") -> bool:
        """Validate boolean value."""
        if isinstance(value, bool):
            return value
        
        if isinstance(value, str):
            str_value = value.lower().strip()
            if str_value in ("true", "yes", "1", "on"):
                return True
            elif str_value in ("false", "no", "0", "off"):
                return False
        
        raise ValidationError(
            f"{field_name} must be a boolean",
            field_name, value
        )


class ListValidator(Validator):
    """List validation."""
    
    def __init__(
        self,
        min_items: Optional[int] = None,
        max_items: Optional[int] = None,
        item_validator: Optional[Validator] = None,
        unique: bool = False
    ):
        self.min_items = min_items
        self.max_items = max_items
        self.item_validator = item_validator
        self.unique = unique
    
    def validate(self, value: Any, field_name: str = "value") -> list:
        """Validate list value."""
        if not isinstance(value, (list, tuple)):
            raise ValidationError(
                f"{field_name} must be a list",
                field_name, value
            )
        
        list_value = list(value)
        
        # Check size
        if self.min_items is not None and len(list_value) < self.min_items:
            raise ValidationError(
                f"{field_name} must have at least {self.min_items} items",
                field_name, value
            )
        
        if self.max_items is not None and len(list_value) > self.max_items:
            raise ValidationError(
                f"{field_name} must have at most {self.max_items} items",
                field_name, value
            )
        
        # Validate items
        if self.item_validator:
            validated_items = []
            for i, item in enumerate(list_value):
                validated_item = self.item_validator.validate(
                    item, f"{field_name}[{i}]"
                )
                validated_items.append(validated_item)
            list_value = validated_items
        
        # Check uniqueness
        if self.unique and len(list_value) != len(set(map(str, list_value))):
            raise ValidationError(
                f"{field_name} must contain unique items",
                field_name, value
            )
        
        return list_value


class DictValidator(Validator):
    """Dictionary validation."""
    
    def __init__(
        self,
        required_keys: Optional[List[str]] = None,
        optional_keys: Optional[List[str]] = None,
        key_validators: Optional[dict[str, Validator]] = None
    ):
        self.required_keys = set(required_keys) if required_keys else set()
        self.optional_keys = set(optional_keys) if optional_keys else set()
        self.key_validators = key_validators or {}
    
    def validate(self, value: Any, field_name: str = "value") -> dict:
        """Validate dictionary value."""
        if not isinstance(value, dict):
            raise ValidationError(
                f"{field_name} must be a dictionary",
                field_name, value
            )
        
        # Check required keys
        missing_keys = self.required_keys - set(value.keys())
        if missing_keys:
            raise ValidationError(
                f"{field_name} missing required keys: {missing_keys}",
                field_name, value
            )
        
        # Check for unknown keys
        allowed_keys = self.required_keys | self.optional_keys
        if allowed_keys:
            unknown_keys = set(value.keys()) - allowed_keys
            if unknown_keys:
                raise ValidationError(
                    f"{field_name} contains unknown keys: {unknown_keys}",
                    field_name, value
                )
        
        # Validate individual keys
        validated_dict = {}
        for key, val in value.items():
            if key in self.key_validators:
                validated_val = self.key_validators[key].validate(
                    val, f"{field_name}.{key}"
                )
                validated_dict[key] = validated_val
            else:
                validated_dict[key] = val
        
        return validated_dict


# Specialized validators

class DiscordIDValidator(StringValidator):
    """Discord ID validation."""
    
    def __init__(self):
        super().__init__(
            pattern=r"^\d{17,19}$",
            strip=True
        )
    
    def validate(self, value: Any, field_name: str = "discord_id") -> str:
        """Validate Discord ID."""
        return super().validate(value, field_name)


class UsernameValidator(StringValidator):
    """Username validation."""
    
    def __init__(self):
        super().__init__(
            min_length=1,
            max_length=32,
            pattern=r"^[a-zA-Z0-9_\-\.]+$",
            strip=True
        )
    
    def validate(self, value: Any, field_name: str = "username") -> str:
        """Validate username."""
        return super().validate(value, field_name)


class MessageContentValidator(StringValidator):
    """Message content validation."""
    
    def __init__(self, max_length: int = 2000):
        super().__init__(
            min_length=1,
            max_length=max_length,
            strip=True
        )
    
    def validate(self, value: Any, field_name: str = "message") -> str:
        """Validate message content."""
        str_value = super().validate(value, field_name)
        
        # Remove dangerous patterns
        dangerous_patterns = [
            r"@everyone",
            r"@here",
            r"<@&\d+>",  # Role mentions
            r"```[\s\S]*?```",  # Code blocks
        ]
        
        for pattern in dangerous_patterns:
            str_value = re.sub(pattern, "[REMOVED]", str_value)
        
        return str_value


class SQLSafeValidator(StringValidator):
    """SQL injection prevention validator."""
    
    def __init__(self, max_length: int = 255):
        super().__init__(
            max_length=max_length,
            strip=True
        )
    
    def validate(self, value: Any, field_name: str = "value") -> str:
        """Validate SQL-safe string."""
        str_value = super().validate(value, field_name)
        
        # Check for SQL injection patterns
        sql_patterns = [
            r";\s*DROP",
            r";\s*DELETE",
            r";\s*UPDATE",
            r";\s*INSERT",
            r"--",
            r"\/\*.*?\*\/",
            r"UNION\s+SELECT",
            r"OR\s+1\s*=\s*1",
        ]
        
        for pattern in sql_patterns:
            if re.search(pattern, str_value, re.IGNORECASE):
                raise ValidationError(
                    f"{field_name} contains potentially dangerous SQL",
                    field_name, value
                )
        
        # Escape quotes
        str_value = str_value.replace("'", "''")
        
        return str_value


def validate_input(**validators):
    """
    Decorator for input validation.
    
    Args:
        **validators: Mapping of parameter names to validators
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Get function signature
            import inspect
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            
            # Validate each parameter
            for param_name, validator in validators.items():
                if param_name in bound.arguments:
                    try:
                        validated_value = validator.validate(
                            bound.arguments[param_name],
                            param_name
                        )
                        bound.arguments[param_name] = validated_value
                    except ValidationError as e:
                        logger.log_warning(
                            f"Validation failed for {func.__name__}",
                            context={
                                "parameter": param_name,
                                "error": str(e)
                            }
                        )
                        raise
            
            # Call function with validated arguments
            return await func(*bound.args, **bound.kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Similar validation for sync functions
            import inspect
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            
            for param_name, validator in validators.items():
                if param_name in bound.arguments:
                    try:
                        validated_value = validator.validate(
                            bound.arguments[param_name],
                            param_name
                        )
                        bound.arguments[param_name] = validated_value
                    except ValidationError as e:
                        logger.log_warning(
                            f"Validation failed for {func.__name__}",
                            context={
                                "parameter": param_name,
                                "error": str(e)
                            }
                        )
                        raise
            
            return func(*bound.args, **bound.kwargs)
        
        import asyncio
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator