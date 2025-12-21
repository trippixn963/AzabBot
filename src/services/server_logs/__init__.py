"""
Server Logs Service Package
===========================

Comprehensive server activity logging using a forum channel with categorized threads.

Structure:
    - categories.py: LogCategory enum and thread descriptions
    - service.py: Main LoggingService class

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from .service import LoggingService
from .categories import LogCategory, THREAD_DESCRIPTIONS

__all__ = [
    "LoggingService",
    "LogCategory",
    "THREAD_DESCRIPTIONS",
]
