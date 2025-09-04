# Azab Discord Bot - Versioning System

This document describes the versioning system implemented for the Azab Discord bot.

## Overview

The bot uses **Semantic Versioning (SemVer)** with the format `MAJOR.MINOR.PATCH[-BUILD]`:

- **MAJOR**: Breaking changes or major feature additions
- **MINOR**: New features, backwards compatible  
- **PATCH**: Bug fixes, backwards compatible
- **BUILD**: Optional build identifier (e.g., 'dev', 'beta', 'rc1')

## Current Version

**Version**: 1.0.0  
**Codename**: Syria  
**Release Type**: Stable  
**Release Date**: 2025-01-04

## Version Management

### Version File Location

All version information is centralized in `src/utils/version.py`. This file contains:

- Current version numbers (MAJOR, MINOR, PATCH, BUILD)
- Release metadata (codename, release date)
- Bot information (name, developer, server)
- Version history and utility functions

### Updating Versions

#### Method 1: Using the Update Script (Recommended)

Use the provided `update_version.py` script for easy version updates:

```bash
# Patch version (bug fixes)
python update_version.py patch

# Minor version (new features)
python update_version.py minor

# Major version (breaking changes)
python update_version.py major

# With build identifier
python update_version.py patch dev
python update_version.py minor beta
python update_version.py major rc1
```

#### Method 2: Manual Update

Edit `src/utils/version.py` directly:

```python
# Current version - Update this for each release
MAJOR = 1
MINOR = 0
PATCH = 0
BUILD = None  # Set to None for stable releases

# Version metadata
CODENAME = "Syria"  # Release codename
RELEASE_DATE = "2025-01-04"  # Update with each release
```

## Version Information Access

### In Code

```python
from src.utils.version import Version

# Get version string
version = Version.get_version_string()  # "1.0.0"

# Get full version info
info = Version.get_full_info()
# Returns dict with all version metadata

# Check release type
is_dev = Version.is_development()  # False for stable releases
is_stable = Version.is_stable()    # True for stable releases
release_type = Version.get_release_type()  # "stable"
```

### In Logs

Version information is automatically displayed in:

- Bot startup logs with version and codename
- Bot ready status with version information
- All log entries include version context

## Version History

| Version | Codename | Date | Type | Changes |
|---------|----------|------|------|---------|
| 1.0.0 | Syria | 2025-01-04 | Stable | Initial stable version with core functionality |

## Release Types

Since you work directly on the main branch, you'll primarily use:

- **Stable**: Production-ready releases (BUILD = None)
- **Custom**: Optional build identifiers for special releases (BUILD = "hotfix", "patch", etc.)

## Integration Points

The version system is integrated throughout the bot:

1. **Startup Logging**: Version info displayed during bot initialization
2. **Bot Status**: Version included in bot ready status
3. **Logging**: Version information in log headers
4. **Error Handling**: Version context in error reports

## Best Practices

### Version Bumping Guidelines

- **PATCH**: Bug fixes, minor improvements, documentation updates
- **MINOR**: New features, new commands, enhanced functionality
- **MAJOR**: Breaking changes, major architecture changes, API changes

### Release Process

1. Update version using `update_version.py`
2. Update `VERSIONING.md` with new version entry
3. Test the bot thoroughly
4. Deploy to production
5. Update version history

### Build Identifiers

Since you work directly on main branch:
- Keep `BUILD = None` for normal stable releases
- Use `"hotfix"` for emergency fixes if needed
- Use `"patch"` for special patch releases if needed

## Development Workflow

Since you work directly on the main branch:

1. **Development**: Work directly on main branch
2. **Testing**: Test changes locally before pushing
3. **Release**: Update version and push to main
4. **Deploy**: Deploy from main branch to production

## Monitoring

The version system provides comprehensive monitoring:

- Version information in all log entries
- Bot status includes version
- Automatic version display on startup

This ensures you always know which version is running and can track changes over time.
