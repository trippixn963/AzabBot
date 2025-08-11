# AzabBot Log Synchronization System

This directory contains scripts for automatically syncing logs from the VPS to your local machine.

## 📋 Overview

The log sync system provides real-time synchronization of AzabBot logs from your VPS (159.89.90.90) to your local development machine. It runs as a background daemon and keeps logs synchronized 24/7.

## 🚀 Quick Start

### Install and Start the Sync Daemon

```bash
cd /Users/johnhamwi/Developer/AzabBot/scripts
bash install_log_sync.sh
```

This will:
- Install the sync daemon as a macOS LaunchAgent
- Start syncing logs every 30 seconds
- Create log directories if they don't exist
- Begin syncing immediately

## 📁 Files

### Shell Scripts
- **`sync_logs_daemon.sh`** - Main bash sync daemon using rsync
- **`install_log_sync.sh`** - Installation script for macOS
- **`uninstall_log_sync.sh`** - Uninstallation script
- **`com.azabbot.logsync.plist`** - macOS LaunchAgent configuration

### Python Alternative
- **`log_sync_daemon.py`** - Advanced Python sync daemon with:
  - Intelligent sync intervals (faster when files are changing)
  - Connection monitoring and auto-reconnect
  - Bandwidth limiting
  - Detailed statistics tracking
  - Progress reporting

## 🛠️ Usage

### Check Status
```bash
launchctl list | grep com.azabbot.logsync
```

### View Sync Logs
```bash
tail -f /Users/johnhamwi/Developer/AzabBot/logs/sync_daemon.log
```

### Stop Syncing
```bash
launchctl unload ~/Library/LaunchAgents/com.azabbot.logsync.plist
```

### Start Syncing
```bash
launchctl load ~/Library/LaunchAgents/com.azabbot.logsync.plist
```

### Uninstall
```bash
bash /Users/johnhamwi/Developer/AzabBot/scripts/uninstall_log_sync.sh
```

## 🐍 Using Python Daemon (Alternative)

The Python daemon offers more features:

### Run Manually
```bash
python3 /Users/johnhamwi/Developer/AzabBot/scripts/log_sync_daemon.py
```

### Features
- **Smart Sync Intervals**: Syncs every 10 seconds when files are changing, 30 seconds when idle
- **Bandwidth Limiting**: Configurable bandwidth limit (default: 1MB/s)
- **Statistics Tracking**: Tracks bytes transferred, files synced, success/failure rates
- **Connection Monitoring**: Automatic reconnection with exponential backoff
- **Progress Reporting**: Shows sync progress for large transfers

### Configuration
Edit the `CONFIG` dictionary in `log_sync_daemon.py`:

```python
CONFIG = {
    "remote_host": "root@159.89.90.90",
    "remote_path": "/root/AzabBot/logs/",
    "local_path": "/Users/johnhamwi/Developer/AzabBot/logs/",
    "sync_interval": 30,  # seconds
    "quick_sync_interval": 10,  # seconds (when files are changing)
    "bandwidth_limit": 1000,  # KB/s (0 for unlimited)
    "compression": True,
    "delete_missing": True,
}
```

## 📊 What Gets Synced

The daemon syncs the entire `/root/AzabBot/logs/` directory structure:

```
logs/
├── YYYY-MM-DD/           # Date folders
│   ├── HH-AM_PM/        # Hourly folders
│   │   ├── log.log      # All messages
│   │   ├── debug.log    # Debug messages
│   │   ├── error.log    # Error messages
│   │   └── logs.json    # Structured JSON logs
```

## 🔒 Security

- Uses SSH key authentication (ensure your SSH key is set up)
- Only syncs log files (excludes temp files, swap files, etc.)
- Read-only access to VPS logs
- No modification of remote files

## 🚨 Troubleshooting

### Sync Not Working
1. Check SSH connection: `ssh root@159.89.90.90 exit`
2. View error logs: `cat /Users/johnhamwi/Developer/AzabBot/logs/sync_daemon_stderr.log`
3. Check service status: `launchctl list | grep com.azabbot.logsync`

### Permission Issues
```bash
chmod 600 ~/.ssh/id_rsa
chmod 644 ~/.ssh/id_rsa.pub
```

### High CPU/Network Usage
- Increase sync interval in the script
- Enable bandwidth limiting in Python daemon
- Check for large log files that might be causing issues

## 📈 Statistics

When using the Python daemon, view statistics:

```bash
cat /Users/johnhamwi/Developer/AzabBot/logs/sync_stats.json
```

This shows:
- Total syncs completed
- Failed sync attempts
- Bytes transferred
- Files synced
- Daemon uptime

## 🔄 Manual Sync

For one-time manual sync:

```bash
rsync -avz --delete \
    root@159.89.90.90:/root/AzabBot/logs/ \
    /Users/johnhamwi/Developer/AzabBot/logs/
```

## 📝 Notes

- Logs are synced every 30 seconds by default
- The daemon automatically handles connection failures
- Local logs are kept in sync with VPS (files deleted on VPS are deleted locally)
- The sync is one-way: VPS → Local only
- Daemon starts automatically on system boot