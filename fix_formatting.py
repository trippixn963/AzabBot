#!/usr/bin/env python3
"""
Fix common formatting issues in Python files.
"""
import os
import re
from pathlib import Path


def fix_file(file_path):
    """Fix common formatting issues in a single file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # Remove trailing whitespace
    content = '\n'.join(line.rstrip() for line in content.split('\n'))
    
    # Fix blank lines with whitespace
    content = re.sub(r'^\s+$', '', content, flags=re.MULTILINE)
    
    # Ensure file ends with single newline
    content = content.rstrip() + '\n'
    
    # Fix common import issues
    if 'from pathlib import Path' in content and 'Path(' not in content and 'Path.' not in content:
        content = content.replace('from pathlib import Path', '')
    
    # Remove duplicate blank lines
    content = re.sub(r'\n\n\n+', '\n\n', content)
    
    # Clean up imports section
    lines = content.split('\n')
    import_section_end = 0
    for i, line in enumerate(lines):
        if line and not line.startswith(('import ', 'from ', '#', ' ', '\t')):
            import_section_end = i
            break
    
    # Remove unused imports (basic check)
    unused_imports = [
        ('from typing import Set', 'Set['),
        ('from discord.ext import commands', 'commands.'),
        ('from src.core.logger import log_startup', 'log_startup'),
        ('from src.core.security import create_security_context', 'create_security_context'),
        ('from src.core.security import check_interaction_security', 'check_interaction_security'),
        ('from src.core.exceptions import ServiceError', 'ServiceError'),
        ('from src.core.exceptions import SecurityError', 'SecurityError'),
        ('from src.core.exceptions import RateLimitExceededError', 'RateLimitExceededError'),
        ('from src.core.exceptions import SaydnayaBotException', 'SaydnayaBotException'),
    ]
    
    for import_stmt, usage in unused_imports:
        if import_stmt in content and usage not in content:
            lines = [line for line in lines if import_stmt not in line]
    
    content = '\n'.join(lines)
    
    if content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Fixed: {file_path}")
        return True
    return False


def main():
    """Fix all Python files in src directory."""
    src_dir = Path('src')
    fixed_count = 0
    
    for py_file in src_dir.rglob('*.py'):
        if '__pycache__' not in str(py_file):
            if fix_file(py_file):
                fixed_count += 1
    
    print(f"\nFixed {fixed_count} files")


if __name__ == '__main__':
    main()