<div align="center">

# AzabBot

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Discord.py](https://img.shields.io/badge/Discord.py-2.7+-5865F2?style=flat-square&logo=discord&logoColor=white)
![License](https://img.shields.io/badge/License-Educational-red?style=flat-square)

Moderation & prison system bot built for **[discord.gg/syria](https://discord.gg/syria)**

[![Join Server](https://img.shields.io/badge/Join_Server-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/syria)
[![Dashboard](https://img.shields.io/badge/Dashboard-E6B84A?style=for-the-badge&logo=safari&logoColor=white)](https://trippixn.com/azab)

</div>

---

## Features

### Prison System
- Welcome/release messages for muted users
- Mute history tracking per user
- Personalized embeds with offense count

### Ticketing
- Forum-based ticket system
- Categories: Support, Partnership, Suggestion
- Staff claim and resolution workflow

### Moderation
- Full case management with notes
- Ban, mute, warn, kick commands
- Tempban and tempmute with duration
- Moderation history lookup

### Protection
- Anti-spam detection
- Anti-nuke safeguards
- Alt account detection
- Comprehensive server logging

---

## Commands

| Command | Description |
|---------|-------------|
| `/ban <user> [reason]` | Ban a user |
| `/unban <user>` | Unban a user |
| `/tempban <user> <duration>` | Temporary ban |
| `/mute <user> [reason]` | Mute (send to prison) |
| `/unmute <user>` | Unmute a user |
| `/tempmute <user> <duration>` | Temporary mute |
| `/warn <user> <reason>` | Issue a warning |
| `/purge <amount>` | Bulk delete messages |
| `/lockdown` | Lock/unlock channel |
| `/history <user>` | View mod history |
| `/snipe [n]` | View deleted messages |
| `/editsnipe [n]` | View edited messages |

---

## Tech Stack

- **Runtime:** Python 3.12
- **Framework:** discord.py 2.7+
- **Database:** SQLite with WAL mode
- **HTTP:** aiohttp

---

## Notice

This is a **custom bot** built specifically for the Syria Discord server. It is open-sourced for **educational purposes only**.

- No support will be provided
- No guarantees of functionality
- Use at your own risk

See [LICENSE](LICENSE) for full terms.
