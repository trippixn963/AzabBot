#!/usr/bin/env python3
"""
Azab Discord Bot - Version Update Script
========================================

Simple script to update the bot version in the version.py file.
Supports semantic versioning with automatic build increment.

Usage:
    python update_version.py [major|minor|patch] [build]

Examples:
    python update_version.py patch          # 1.0.0 -> 1.0.1
    python update_version.py minor          # 1.0.1 -> 1.1.0
    python update_version.py major          # 1.1.0 -> 2.0.0
    python update_version.py patch dev      # 1.0.0 -> 1.0.1-dev
    python update_version.py minor beta     # 1.0.0 -> 1.1.0-beta

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


def update_version(version_type: str, build: Optional[str] = None) -> bool:
    """
    Update the version in version.py file.
    
    Args:
        version_type: Type of version bump (major, minor, patch)
        build: Optional build identifier
    """
    version_file: Path = Path("src/utils/version.py")
    
    if not version_file.exists():
        print("❌ Error: version.py file not found!")
        return False
    
    # Read current file
    with open(version_file, 'r', encoding='utf-8') as f:
        content: str = f.read()
    
    # Extract current version numbers
    major_match: Optional[re.Match[str]] = re.search(r'MAJOR = (\d+)', content)
    minor_match: Optional[re.Match[str]] = re.search(r'MINOR = (\d+)', content)
    patch_match: Optional[re.Match[str]] = re.search(r'PATCH = (\d+)', content)
    build_match: Optional[re.Match[str]] = re.search(r'BUILD = "([^"]*)"', content)
    
    if not all([major_match, minor_match, patch_match]):
        print("❌ Error: Could not parse current version!")
        return False
    
    current_major: int = int(major_match.group(1))
    current_minor: int = int(minor_match.group(1))
    current_patch: int = int(patch_match.group(1))
    current_build: Optional[str] = build_match.group(1) if build_match else None
    
    # Calculate new version
    new_major: int
    new_minor: int
    new_patch: int
    if version_type == "major":
        new_major = current_major + 1
        new_minor = 0
        new_patch = 0
    elif version_type == "minor":
        new_major = current_major
        new_minor = current_minor + 1
        new_patch = 0
    elif version_type == "patch":
        new_major = current_major
        new_minor = current_minor
        new_patch = current_patch + 1
    else:
        print(f"❌ Error: Invalid version type '{version_type}'. Use major, minor, or patch.")
        return False
    
    # Update version numbers in content
    content = re.sub(r'MAJOR = \d+', f'MAJOR = {new_major}', content)
    content = re.sub(r'MINOR = \d+', f'MINOR = {new_minor}', content)
    content = re.sub(r'PATCH = \d+', f'PATCH = {new_patch}', content)
    
    # Update build if provided
    if build is not None:
        content = re.sub(r'BUILD = "[^"]*"', f'BUILD = "{build}"', content)
    
    # Update release date
    today: str = datetime.now().strftime("%Y-%m-%d")
    content = re.sub(r'RELEASE_DATE = "[^"]*"', f'RELEASE_DATE = "{today}"', content)
    
    # Write updated content
    with open(version_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    # Display results
    new_version: str = f"{new_major}.{new_minor}.{new_patch}"
    if build:
        new_version += f"-{build}"
    
    print(f"✅ Version updated successfully!")
    print(f"   Old: {current_major}.{current_minor}.{current_patch}" + (f"-{current_build}" if current_build else ""))
    print(f"   New: {new_version}")
    print(f"   Date: {today}")
    
    return True


def main() -> None:
    """Main function to handle command line arguments."""
    if len(sys.argv) < 2:
        print("Usage: python update_version.py [major|minor|patch] [build]")
        print("\nExamples:")
        print("  python update_version.py patch          # 1.0.0 -> 1.0.1")
        print("  python update_version.py minor          # 1.0.1 -> 1.1.0")
        print("  python update_version.py major          # 1.1.0 -> 2.0.0")
        print("  python update_version.py patch dev      # 1.0.0 -> 1.0.1-dev")
        print("  python update_version.py minor beta     # 1.0.0 -> 1.1.0-beta")
        return
    
    version_type: str = sys.argv[1].lower()
    build: Optional[str] = sys.argv[2] if len(sys.argv) > 2 else None
    
    if version_type not in ["major", "minor", "patch"]:
        print(f"❌ Error: Invalid version type '{version_type}'. Use major, minor, or patch.")
        return
    
    success: bool = update_version(version_type, build)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
