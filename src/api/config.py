"""
AzabBot - API Configuration
===========================

Centralized configuration for the FastAPI service.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from dataclasses import dataclass
from typing import Optional
import os


@dataclass(frozen=True)
class APIConfig:
    """API configuration settings."""

    # Server
    host: str = "0.0.0.0"
    port: int = 8081
    debug: bool = False

    # CORS
    cors_origins: list[str] = ("*",)
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ("*",)
    cors_allow_headers: list[str] = ("*",)

    # Rate Limiting
    rate_limit_requests: int = 60
    rate_limit_window: int = 60  # seconds
    rate_limit_burst: int = 10

    # JWT Auth
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

    # Pagination
    default_page_size: int = 50
    max_page_size: int = 100

    # WebSocket
    ws_heartbeat_interval: int = 30  # seconds
    ws_max_connections: int = 100

    # Cache
    cache_ttl: int = 300  # 5 minutes


def load_api_config() -> APIConfig:
    """Load API configuration from environment."""
    return APIConfig(
        host=os.getenv("AZAB_API_HOST", "0.0.0.0"),
        port=int(os.getenv("AZAB_API_PORT", "8081")),
        debug=os.getenv("AZAB_API_DEBUG", "false").lower() == "true",
        jwt_secret=os.getenv("AZAB_APPEAL_TOKEN_SECRET", ""),
        jwt_expiry_hours=int(os.getenv("AZAB_JWT_EXPIRY_HOURS", "24")),
    )


# Singleton instance
_config: Optional[APIConfig] = None


def get_api_config() -> APIConfig:
    """Get the API configuration singleton."""
    global _config
    if _config is None:
        _config = load_api_config()
    return _config


__all__ = ["APIConfig", "get_api_config", "load_api_config"]
