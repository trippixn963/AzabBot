#!/bin/bash
# AzabBot Log Sync Daemon
# Continuously syncs logs from VPS to local machine

# Configuration
REMOTE_HOST="root@159.89.90.90"
REMOTE_PATH="/root/AzabBot/logs/"
LOCAL_PATH="/Users/johnhamwi/Developer/AzabBot/logs/"
SYNC_INTERVAL=30  # Sync every 30 seconds
LOG_FILE="/Users/johnhamwi/Developer/AzabBot/logs/sync_daemon.log"

# Create local logs directory if it doesn't exist
mkdir -p "$LOCAL_PATH"

# Function to log messages
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Function to perform sync
sync_logs() {
    # Use rsync with the following options:
    # -avz: archive mode, verbose, compress
    # --delete: delete files that don't exist on sender
    # --exclude: exclude certain files/patterns
    rsync -avz \
        --delete \
        --exclude "sync_daemon.log" \
        --exclude ".DS_Store" \
        "$REMOTE_HOST:$REMOTE_PATH" \
        "$LOCAL_PATH" 2>&1 | while read line; do
            # Only log actual file transfers, not verbose output
            if [[ $line == *"log"* ]] || [[ $line == *"error"* ]]; then
                log_message "SYNC: $line"
            fi
        done
    
    return ${PIPESTATUS[0]}
}

# Main daemon loop
log_message "Starting AzabBot log sync daemon"
log_message "Syncing from $REMOTE_HOST:$REMOTE_PATH to $LOCAL_PATH"
log_message "Sync interval: ${SYNC_INTERVAL} seconds"

# Initial sync
log_message "Performing initial sync..."
if sync_logs; then
    log_message "Initial sync completed successfully"
else
    log_message "Initial sync failed with error code $?"
fi

# Continuous sync loop
while true; do
    sleep $SYNC_INTERVAL
    
    # Check if remote host is reachable
    if ssh -o ConnectTimeout=5 -o BatchMode=yes "$REMOTE_HOST" exit 2>/dev/null; then
        if sync_logs; then
            # Success - no need to log every successful sync
            :
        else
            log_message "Sync failed with error code $?"
        fi
    else
        log_message "Cannot reach remote host $REMOTE_HOST"
    fi
done