"""
Azab Discord Bot - Version Management
====================================

Centralized version management system for the Azab Discord bot.
Implements semantic versioning (MAJOR.MINOR.PATCH) with build metadata.

Version Format: MAJOR.MINOR.PATCH[-BUILD]
- MAJOR: Breaking changes or major feature additions
- MINOR: New features, backwards compatible
- PATCH: Bug fixes, backwards compatible
- BUILD: Optional build identifier (e.g., 'dev', 'beta', 'rc1')

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from datetime import datetime
from typing import Dict, Any, Optional


class Version:
    """
    Version management class for Azab Discord bot.
    
    Provides semantic versioning with build metadata and version history tracking.
    All version information is centralized here for consistency across the bot.
    """
    
    # Current version - Update this for each release
    MAJOR: int = 1
    MINOR: int = 0
    PATCH: int = 0
    BUILD: Optional[str] = None  # Set to None for stable releases
    
    # Version metadata
    CODENAME: str = "Syria"  # Release codename
    RELEASE_DATE: str = "2025-01-04"  # Update with each release
    
    # Bot information
    BOT_NAME: str = "Azab"
    DEVELOPER: str = "حَـــــنَّـــــا"
    SERVER: str = "discord.gg/syria"
    
    @classmethod
    def get_version_string(cls) -> str:
        """
        Get the complete version string.
        
        Returns:
            str: Version in format "MAJOR.MINOR.PATCH[-BUILD]"
        """
        version: str = f"{cls.MAJOR}.{cls.MINOR}.{cls.PATCH}"
        if cls.BUILD:
            version += f"-{cls.BUILD}"
        return version
    
    @classmethod
    def get_full_info(cls) -> Dict[str, Any]:
        """
        Get complete version and bot information.
        
        Returns:
            Dict[str, Any]: Complete version information dictionary
        """
        return {
            "version": cls.get_version_string(),
            "major": cls.MAJOR,
            "minor": cls.MINOR,
            "patch": cls.PATCH,
            "build": cls.BUILD,
            "codename": cls.CODENAME,
            "release_date": cls.RELEASE_DATE,
            "bot_name": cls.BOT_NAME,
            "developer": cls.DEVELOPER,
            "server": cls.SERVER,
            "build_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    
    @classmethod
    def get_display_string(cls) -> str:
        """
        Get formatted version string for display purposes.
        
        Returns:
            str: Formatted version string with codename
        """
        version: str = cls.get_version_string()
        return f"{cls.BOT_NAME} v{version} '{cls.CODENAME}'"
    
    @classmethod
    def get_short_info(cls) -> str:
        """
        Get short version info for logging.
        
        Returns:
            str: Short version string
        """
        return f"v{cls.get_version_string()}"
    
    @classmethod
    def is_development(cls) -> bool:
        """
        Check if this is a development build.
        
        Returns:
            bool: True if build contains 'dev', 'beta', or 'rc'
        """
        if not cls.BUILD:
            return False
        return any(keyword in cls.BUILD.lower() for keyword in ['dev', 'beta', 'rc'])
    
    @classmethod
    def is_stable(cls) -> bool:
        """
        Check if this is a stable release.
        
        Returns:
            bool: True if no build identifier or stable build
        """
        return not cls.BUILD or cls.BUILD.lower() in ['stable', 'release']
    
    @classmethod
    def get_release_type(cls) -> str:
        """
        Get the release type based on version and build.
        
        Returns:
            str: Release type ('stable', 'development', 'beta', 'release_candidate')
        """
        if cls.is_stable():
            return "stable"
        elif cls.is_development():
            if 'beta' in cls.BUILD.lower():
                return "beta"
            elif 'rc' in cls.BUILD.lower():
                return "release_candidate"
            else:
                return "development"
        else:
            return "custom"


# Version history for reference
VERSION_HISTORY = {
    "1.0.0": {
        "date": "2025-01-04",
        "codename": "Syria",
        "changes": [
            "Initial stable version",
            "Core bot functionality",
            "AI-powered responses",
            "Mute detection and handling",
            "Slash commands (/activate, /deactivate)",
            "Message logging and analytics",
            "Centralized version management system"
        ]
    }
}


def get_version_info() -> Dict[str, Any]:
    """
    Convenience function to get current version information.
    
    Returns:
        Dict[str, Any]: Current version information
    """
    return Version.get_full_info()


def get_version_string() -> str:
    """
    Convenience function to get version string.
    
    Returns:
        str: Current version string
    """
    return Version.get_version_string()
