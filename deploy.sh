#!/bin/bash

echo "🚀 Deploying AzabBot to VPS..."
echo ""

# Update IP address to current VPS
VPS_IP="5.161.220.19"

# SSH into VPS and update
ssh root@$VPS_IP << 'EOF'
    echo "📦 Pulling latest changes from GitHub..."
    cd /root/AzabBot
    git pull
    
    echo ""
    echo "📦 Installing/updating dependencies..."
    source venv/bin/activate
    pip install -r requirements.txt
    
    echo ""
    echo "🔄 Restarting bot with systemd..."
    systemctl restart azabbot
    
    echo ""
    echo "📊 Bot status:"
    systemctl status azabbot --no-pager
    
    echo ""
    echo "✅ Deployment complete!"
EOF