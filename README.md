# 🔥 AzabBot - AI-Powered Discord Prison Bot

<div align="center">

![AzabBot Banner](images/BANNER.gif)

![Python](https://img.shields.io/badge/Python-3.12-blue.svg)
![Discord.py](https://img.shields.io/badge/Discord.py-2.3.2+-green.svg)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4-orange.svg)

**AI-powered psychological warfare against muted users**

*Built for discord.gg/syria*

[![Join Discord Server](https://img.shields.io/badge/Join%20Server-discord.gg/syria-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/syria)

</div>

---

## 🎯 What is AzabBot?

A Discord bot that ragebaits muted users using GPT-4. When someone gets muted, AzabBot welcomes them to prison and responds to their messages with contextual roasts based on their mute reason and conversation history.

**⚠️ Custom-built for discord.gg/syria • No support provided**

---

## ✨ Features

- 🧠 **GPT-4 Roasting** - Contextual AI responses with 10-message conversation history
- 🏰 **Prison System** - Automatic welcomes, daily cleanup, prisoner tracking
- 🔍 **Smart Detection** - Monitors role changes, timeouts, and moderation logs
- 🎭 **Dynamic Presence** - 14 rotating status messages showing bot activity
- 👨‍👩‍👦 **Family Mode** - Special responses for developer and family members
- 📊 **Analytics** - Tracks mutes, messages, prisoner history with SQLite
- 🔒 **Security** - Input validation, SQL injection prevention, instance locking
- 🎮 **Commands** - `/activate`, `/deactivate`, `/ignore`

---

## 🚀 Quick Start

```bash
# Clone and setup
git clone https://github.com/trippixn963/AzabBot.git
cd AzabBot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your tokens and IDs

# Run
python main.py
```

---

## ⚙️ Configuration

Essential environment variables in `.env`:

```env
# Discord
DISCORD_TOKEN=your_bot_token
DEVELOPER_ID=your_user_id

# OpenAI (optional but recommended)
OPENAI_API_KEY=your_api_key

# Channels & Roles
LOGS_CHANNEL_ID=moderation_logs_channel
PRISON_CHANNEL_ID=prison_channel
GENERAL_CHANNEL_ID=general_channel
MUTED_ROLE_ID=muted_role

# Settings (optional)
PRISON_CLEANUP_HOUR=0
TIMEZONE_OFFSET_HOURS=-5
```

**Discord Bot Setup:**
- Enable "Message Content Intent", "Server Members Intent", and "Reactions Intent"
- Invite bot with permissions: Send Messages, Manage Messages, View Channels

---

## 🎮 Usage

**Commands:**
- `/activate` - Enable ragebaiting mode
- `/deactivate` - Disable ragebaiting mode
- `/ignore <user>` - Ignore/unignore specific users

**What it does:**
1. Detects when users get muted
2. Sends welcome message to prison with mute reason
3. Responds to their messages with AI-powered roasts
4. Tracks prisoner history and statistics
5. Daily cleanup at midnight
6. Announces releases with time served

**Example:**
```
User (muted): "This is so unfair!"
AzabBot: "Imagine getting muted and still complaining 😂
         Welcome to prison, enjoy your stay! 🔒"
```

---

## 🏗️ Structure

```
AzabBot/
├── src/
│   ├── bot.py                    # Main bot
│   ├── commands/                 # Slash commands
│   ├── handlers/                 # Prison, mute, presence
│   ├── services/                 # AI, system knowledge
│   ├── core/                     # Database, logger
│   └── utils/                    # Helpers, validators
├── images/                       # Assets
├── main.py                       # Entry point
└── requirements.txt              # Dependencies
```

**Tech Stack:** discord.py, OpenAI GPT-4, SQLite, aiohttp

---

## ⚠️ Disclaimer

Educational purposes only. No support provided. Use at own risk.

---

## 👨‍💻 Author

<div align="center">

![Developer Avatar](images/AUTHOR.jpg)

**حَـــــنَّـــــا**

*Built with ❤️ for discord.gg/syria*

---

[Report Bug](https://github.com/trippixn963/AzabBot/issues) • [Request Feature](https://github.com/trippixn963/AzabBot/issues) • [Discord Server](https://discord.gg/syria)

</div>
