# 🚀 Azab Discord Bot - Deployment Guide

<div align="center">

**Simple deployment guide for the Azab Discord Bot**

*Built specifically for discord.gg/syria*

</div>

---

## 📋 Prerequisites

- **Python 3.11+** - Required for running the bot
- **Discord Bot Token** - From Discord Developer Portal
- **OpenAI API Key** - Optional but recommended for AI responses
- **VPS/Server** - For 24/7 operation

---

## 🖥️ VPS Deployment (Recommended)

### 1. Server Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and dependencies
sudo apt install python3.11 python3.11-venv python3-pip git -y

# Create user for bot
sudo useradd -m -s /bin/bash azab
sudo su - azab
```

### 2. Application Setup

```bash
# Clone repository
git clone https://github.com/trippixn963/AzabBot.git
cd AzabBot

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp env.example .env
nano .env  # Edit with your configuration
```

### 3. Systemd Service

Create `/etc/systemd/system/azab-bot.service`:

```ini
[Unit]
Description=Azab Discord Bot
After=network.target

[Service]
Type=simple
User=azab
WorkingDirectory=/home/azab/AzabBot
Environment=PATH=/home/azab/AzabBot/venv/bin
ExecStart=/home/azab/AzabBot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 4. Start Service

```bash
# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable azab-bot
sudo systemctl start azab-bot

# Check status
sudo systemctl status azab-bot

# View logs
sudo journalctl -u azab-bot -f
```

---

## ⚙️ Configuration

### Environment Variables

Create `.env` file with your configuration:

```env
# Required
DISCORD_TOKEN=your_bot_token
DEVELOPER_ID=your_user_id

# Optional but recommended
OPENAI_API_KEY=your_openai_key

# Channel configuration
LOGS_CHANNEL_ID=channel_id
PRISON_CHANNEL_ID=channel_id
MUTED_ROLE_ID=role_id
```

### Discord Bot Setup

1. **Create Discord Application**:
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Create new application → Bot section
   - Copy token to `.env` file

2. **Set Bot Permissions**:
   - Enable "Message Content Intent"
   - Enable "Server Members Intent"
   - Add bot to server with admin permissions

3. **Configure Channels**:
   - Create logs channel for moderation embeds
   - Create prison channel for ragebaiting
   - Create muted role for user detection

---

## 🔄 Updates

### Manual Update

```bash
# Stop bot
sudo systemctl stop azab-bot

# Pull updates
git pull origin main

# Update dependencies
source venv/bin/activate
pip install -r requirements.txt

# Start bot
sudo systemctl start azab-bot
```

### Automated Update Script

Create `update_bot.sh`:

```bash
#!/bin/bash
cd /home/azab/AzabBot
sudo systemctl stop azab-bot
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl start azab-bot
```

---

## 📊 Monitoring

### View Logs

```bash
# Real-time logs
sudo journalctl -u azab-bot -f

# Check for errors
sudo journalctl -u azab-bot | grep ERROR

# Bot status
sudo systemctl status azab-bot
```

### Log Files

```bash
# View daily log files
tail -f logs/$(date +%Y-%m-%d).log

# Check for errors
grep "ERROR" logs/*.log
```

---

## 🚨 Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Bot not responding | Check Discord token and permissions |
| AI not working | Verify OpenAI API key and quota |
| Database errors | Check file permissions and disk space |
| Service won't start | Check logs: `sudo journalctl -u azab-bot` |

### Quick Fixes

```bash
# Restart bot
sudo systemctl restart azab-bot

# Check configuration
cat .env

# Verify Python environment
source venv/bin/activate
python --version
pip list
```

---

## ⚠️ Important Notes

- **No Support**: This is a personal project with no support provided
- **Use at Own Risk**: Not responsible for any consequences
- **Server-Specific**: Built for discord.gg/syria, may not work elsewhere
- **Private Bot**: Designed for single server use only

---

<div align="center">

**⭐ Star this repository if you find it useful!**

[Report Issues](https://github.com/trippixn963/AzabBot/issues) • [Discord Server](https://discord.gg/syria)

</div>