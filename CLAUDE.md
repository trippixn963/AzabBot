# Claude Development Guidelines for AzabBot

## Git Commit Rules
- **NEVER** include "Generated with [Claude Code]" or any AI attribution in commit messages
- Keep commit messages clean, professional, and focused on the changes made
- No Co-Authored-By lines referencing Claude or AI tools
- Write commits as if a human developer wrote them

## Project-Specific Context
- Bot should start in INACTIVE state by default
- Developer ID: 1249397157702795396
- Moderator IDs: 982740720093896704
- All embed footers should include: "AzabBot v{__version__} • Developed by حَـــــنَّـــــا"
- When bot is activated, it should process recent prisoner messages immediately
- Always verify users are still muted before responding to their messages

## Code Style
- No unnecessary comments unless requested
- Follow existing patterns in the codebase
- Use existing libraries and utilities
- Never assume a library is available without checking

## Testing Commands
- Lint: `ruff check .`
- Type check: `mypy .`
- Format: `black .`

## VPS Deployment
- Server: root@159.89.90.90
- Location: /root/AzabBot
- Service: systemctl restart azabbot
- Deploy: `ssh root@159.89.90.90 "cd /root/AzabBot && git pull && systemctl restart azabbot"`