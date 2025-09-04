# 🚀 Azab Discord Bot - Deployment Guide

<div align="center">

**Simple deployment guide for the Azab Discord Bot**

*Built specifically for discord.gg/syria*

</div>

---

## 📋 Prerequisites

- Python 3.11 or higher
- Discord Bot Token
- OpenAI API Key (optional but recommended)
- Server/VPS with internet access

## 🐳 Docker Deployment (Recommended)

### 1. Create Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 azab && chown -R azab:azab /app
USER azab

# Expose port (if needed for health checks)
EXPOSE 8080

# Run the bot
CMD ["python", "main.py"]
```

### 2. Create docker-compose.yml

```yaml
version: '3.8'

services:
  azab-bot:
    build: .
    container_name: azab-discord-bot
    restart: unless-stopped
    environment:
      - DISCORD_TOKEN=${DISCORD_TOKEN}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - DEVELOPER_ID=${DEVELOPER_ID}
      - LOGS_CHANNEL_ID=${LOGS_CHANNEL_ID}
      - PRISON_CHANNEL_ID=${PRISON_CHANNEL_ID}
      - MUTED_ROLE_ID=${MUTED_ROLE_ID}
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    networks:
      - azab-network

networks:
  azab-network:
    driver: bridge
```

### 3. Deploy with Docker

```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## 🖥️ VPS Deployment

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

# Copy environment file
cp env.example .env
# Edit .env with your configuration
nano .env
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
# Reload systemd
sudo systemctl daemon-reload

# Enable and start service
sudo systemctl enable azab-bot
sudo systemctl start azab-bot

# Check status
sudo systemctl status azab-bot

# View logs
sudo journalctl -u azab-bot -f
```

## ☁️ Cloud Deployment

### Heroku

1. **Create Procfile**:
```
worker: python main.py
```

2. **Deploy**:
```bash
heroku create your-bot-name
heroku config:set DISCORD_TOKEN=your_token
heroku config:set OPENAI_API_KEY=your_key
git push heroku main
```

### Railway

1. **Connect GitHub repository**
2. **Set environment variables**
3. **Deploy automatically**

### DigitalOcean App Platform

1. **Create new app**
2. **Connect GitHub repository**
3. **Configure environment variables**
4. **Deploy**

## 🔧 Configuration

### Environment Variables

Copy `env.example` to `.env` and configure:

```bash
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
   - Create new application
   - Go to "Bot" section
   - Create bot and copy token

2. **Set Bot Permissions**:
   - Enable "Message Content Intent"
   - Enable "Server Members Intent"
   - Add bot to server with appropriate permissions

3. **Configure Channels**:
   - Create logs channel for moderation embeds
   - Create prison channel for ragebaiting
   - Create muted role for user detection

## 📊 Monitoring

### Health Checks

The bot includes built-in health monitoring:

```python
# Check bot status
curl http://localhost:8080/health

# View logs
tail -f logs/azab_$(date +%Y-%m-%d).log
```

### Log Monitoring

```bash
# Monitor logs in real-time
tail -f logs/azab_*.log

# Check for errors
grep "ERROR" logs/azab_*.log

# Monitor specific run ID
grep "RUN:abc123" logs/azab_*.log
```

## 🔄 Updates

### Manual Update

```bash
# Stop bot
sudo systemctl stop azab-bot

# Backup data
cp -r data data_backup_$(date +%Y%m%d)

# Pull updates
git pull origin main

# Update dependencies
source venv/bin/activate
pip install -r requirements.txt

# Start bot
sudo systemctl start azab-bot
```

### Automated Updates

Create update script:

```bash
#!/bin/bash
# update_bot.sh

cd /home/azab/AzabBot
sudo systemctl stop azab-bot
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl start azab-bot
```

## 🛡️ Security

### Firewall

```bash
# Allow only necessary ports
sudo ufw allow ssh
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
```

### SSL/TLS

Use reverse proxy with SSL:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 🚨 Troubleshooting

### Common Issues

1. **Bot not responding**:
   - Check Discord token
   - Verify channel IDs
   - Check bot permissions

2. **AI not working**:
   - Verify OpenAI API key
   - Check API quota
   - Review error logs

3. **Database errors**:
   - Check file permissions
   - Verify disk space
   - Review database logs

### Log Analysis

```bash
# Check recent errors
grep "ERROR" logs/azab_*.log | tail -20

# Monitor specific user
grep "user_id" logs/azab_*.log

# Check performance
grep "Response time" logs/azab_*.log
```

---

<div align="center">

**⭐ Star this repository if you find it useful!**

[Report Issues](https://github.com/trippixn963/AzabBot/issues) • [Discord Server](https://discord.gg/syria)

</div>
