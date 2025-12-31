# AzabBot

<div align="center">

![AzabBot Banner](images/BANNER.gif)

![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)
![Discord.py](https://img.shields.io/badge/Discord.py-2.3.2+-5865F2?style=flat-square&logo=discord&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o--mini-412991?style=flat-square&logo=openai&logoColor=white)
![License](https://img.shields.io/badge/License-Source%20Available-red?style=flat-square)

**AI-Powered Moderation Bot for Discord**

*Built for [discord.gg/syria](https://discord.gg/syria)*

[![Join Server](https://img.shields.io/badge/Join%20Server-discord.gg/syria-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/syria)
[![Dashboard](https://img.shields.io/badge/Dashboard-trippixn.com/azab-E6B84A?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCI+PHBhdGggZD0iTTMgOWwzLTMgMyAzIi8+PHBhdGggZD0iTTYgNnYxMiIvPjxwYXRoIGQ9Ik0xNSAyMWwzLTMgMy0zIi8+PHBhdGggZD0iTTE4IDE4VjYiLz48L3N2Zz4=&logoColor=white)](https://trippixn.com/azab)

</div>

---

## Overview

AzabBot is a comprehensive moderation bot featuring AI-powered prison interactions, a full ticketing system, appeal handling, and extensive server logging. When users get muted, the bot welcomes them to "prison" and responds to their messages with contextual AI-generated responses.

**Live Stats Dashboard**: [trippixn.com/azab](https://trippixn.com/azab)

> **Note**: This bot was custom-built for **discord.gg/syria** and is provided as-is for educational purposes. **No support will be provided.**

---

## Features

| Feature | Description |
|---------|-------------|
| **Prison System** | AI-powered responses to muted users with conversation context |
| **Ticketing System** | Forum-based tickets with categories, claiming, and priority levels |
| **Appeal System** | DM-based appeals for bans and mutes with staff review |
| **Server Logging** | Comprehensive logging for joins, leaves, edits, deletes, and mod actions |
| **Case Management** | Full moderation history with case linking and notes |
| **Anti-Spam** | Automated spam detection and action |
| **Anti-Nuke** | Protection against mass deletions and permission changes |
| **Alt Detection** | Identifies potential alternate accounts |
| **Modmail** | Private communication channel with users |
| **Snipe Commands** | View recently deleted and edited messages |

---

## Commands

| Command | Description |
|---------|-------------|
| `/ban <user> [reason]` | Ban a user from the server |
| `/unban <user>` | Unban a user from the server |
| `/tempban <user> <duration>` | Temporarily ban a user |
| `/mute <user> [reason]` | Mute a user (sends to prison) |
| `/unmute <user>` | Unmute a user |
| `/tempmute <user> <duration>` | Temporarily mute a user |
| `/warn <user> <reason>` | Issue a warning to a user |
| `/purge <amount>` | Bulk delete messages |
| `/lockdown` | Lock/unlock a channel |
| `/history <user>` | View moderation history for a user |
| `/snipe [number]` | View recently deleted messages |
| `/editsnipe [number]` | View recently edited messages |
| `/clearsnipe` | Clear snipe caches |

---

## Tech Stack

- **Python 3.13+** - Async runtime
- **Discord.py 2.3+** - Discord API wrapper
- **OpenAI GPT-4o-mini** - AI responses
- **SQLite** - State persistence with WAL mode
- **aiohttp** - Async HTTP client

---

## Architecture

```
AzabBot/
├── src/
│   ├── core/           # Bot initialization, config, database, logging
│   ├── services/       # AI, tickets, appeals, logging, protection systems
│   ├── handlers/       # Event handlers (prison, presence, messages)
│   ├── commands/       # Slash commands (ban, mute, warn, purge, etc.)
│   ├── events/         # Discord event listeners
│   └── utils/          # Helpers, views, validators
├── data/               # SQLite database, backups
└── images/             # Bot assets
```

---

## Database Schema

| Table | Description |
|-------|-------------|
| `cases` | Moderation case records (bans, mutes, warns) |
| `case_notes` | Staff notes attached to cases |
| `case_links` | Links between related cases |
| `tickets` | Support ticket records |
| `appeals` | User appeals for moderation actions |
| `member_activity` | Join/leave tracking |
| `mute_history` | Mute records with expiry tracking |
| `server_logs` | Forum thread IDs for log categories |

---

## License

**Source Available** - See [LICENSE](LICENSE) for details.

This code is provided for **educational and viewing purposes only**. You may not run, redistribute, or create derivative works from this code.

---

<div align="center">

<img src="images/PFP.gif" alt="AzabBot" width="100">

**AzabBot**

*Built with care for [discord.gg/syria](https://discord.gg/syria)*

</div>
