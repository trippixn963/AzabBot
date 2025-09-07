#!/bin/bash

echo "🚀 Deploying AzabBot to VPS..."
echo ""

# SSH into VPS and update
ssh root@167.172.139.171 << 'EOF'
    echo "📦 Pulling latest changes from GitHub..."
    cd /root/AzabBot
    git pull
    
    echo ""
    echo "🔄 Restarting bot with PM2..."
    pm2 restart azab
    
    echo ""
    echo "📊 Bot status:"
    pm2 status azab
    
    echo ""
    echo "✅ Deployment complete!"
EOF