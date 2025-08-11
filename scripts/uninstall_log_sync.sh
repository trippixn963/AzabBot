#!/bin/bash
# Uninstallation script for AzabBot log sync daemon

echo "🗑️  AzabBot Log Sync Daemon Uninstallation"
echo "=========================================="

LAUNCHD_PATH="$HOME/Library/LaunchAgents"
PLIST_NAME="com.azabbot.logsync.plist"

# Check if service is installed
if launchctl list | grep -q "com.azabbot.logsync"; then
    echo "📋 Stopping service..."
    launchctl unload "$LAUNCHD_PATH/$PLIST_NAME" 2>/dev/null
    launchctl remove com.azabbot.logsync 2>/dev/null
    echo "✅ Service stopped"
else
    echo "ℹ️  Service not currently running"
fi

# Remove plist file
if [ -f "$LAUNCHD_PATH/$PLIST_NAME" ]; then
    echo "🗑️  Removing LaunchAgent plist..."
    rm "$LAUNCHD_PATH/$PLIST_NAME"
    echo "✅ Plist removed"
else
    echo "ℹ️  Plist file not found"
fi

echo ""
echo "✅ Uninstallation complete!"
echo ""
echo "ℹ️  Note: Log files have been preserved in:"
echo "   /Users/johnhamwi/Developer/AzabBot/logs/"