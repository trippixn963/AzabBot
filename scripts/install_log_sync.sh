#!/bin/bash
# Installation script for AzabBot log sync daemon

echo "🔧 AzabBot Log Sync Daemon Installation"
echo "========================================"

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "❌ This script is designed for macOS only"
    exit 1
fi

# Set up paths
SCRIPT_DIR="/Users/johnhamwi/Developer/AzabBot/scripts"
PLIST_FILE="$SCRIPT_DIR/com.azabbot.logsync.plist"
DAEMON_SCRIPT="$SCRIPT_DIR/sync_logs_daemon.sh"
LAUNCHD_PATH="$HOME/Library/LaunchAgents"

# Make scripts executable
echo "📝 Making scripts executable..."
chmod +x "$DAEMON_SCRIPT"
chmod +x "$SCRIPT_DIR/install_log_sync.sh"

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$LAUNCHD_PATH"

# Check if service is already installed
if launchctl list | grep -q "com.azabbot.logsync"; then
    echo "⚠️  Service already installed. Unloading existing service..."
    launchctl unload "$LAUNCHD_PATH/com.azabbot.logsync.plist" 2>/dev/null
    launchctl remove com.azabbot.logsync 2>/dev/null
fi

# Copy plist to LaunchAgents
echo "📋 Installing LaunchAgent..."
cp "$PLIST_FILE" "$LAUNCHD_PATH/"

# Load the service
echo "🚀 Loading service..."
launchctl load "$LAUNCHD_PATH/com.azabbot.logsync.plist"

# Check if service is running
sleep 2
if launchctl list | grep -q "com.azabbot.logsync"; then
    echo "✅ Service installed and running successfully!"
    echo ""
    echo "📊 Service Status:"
    launchctl list | grep com.azabbot.logsync
    echo ""
    echo "📁 Logs will be synced to: /Users/johnhamwi/Developer/AzabBot/logs/"
    echo "📝 Sync daemon log: /Users/johnhamwi/Developer/AzabBot/logs/sync_daemon.log"
    echo ""
    echo "🛠️  Useful commands:"
    echo "  • Check status:  launchctl list | grep com.azabbot.logsync"
    echo "  • View logs:     tail -f /Users/johnhamwi/Developer/AzabBot/logs/sync_daemon.log"
    echo "  • Stop service:  launchctl unload ~/Library/LaunchAgents/com.azabbot.logsync.plist"
    echo "  • Start service: launchctl load ~/Library/LaunchAgents/com.azabbot.logsync.plist"
    echo "  • Uninstall:     bash $SCRIPT_DIR/uninstall_log_sync.sh"
else
    echo "❌ Failed to start service. Check error logs:"
    echo "   cat /Users/johnhamwi/Developer/AzabBot/logs/sync_daemon_stderr.log"
fi