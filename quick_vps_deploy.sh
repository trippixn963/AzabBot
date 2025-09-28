#!/bin/bash
# Quick VPS deployment script
# Run this locally to deploy to VPS

echo "🚀 Deploying Azab v2.4.0 to VPS..."
echo "=================================="
echo

# CONFIGURE THESE
VPS_USER="root"  # VPS username
VPS_HOST="5.161.220.19"  # VPS IP address
BOT_PATH="/root/AzabBot"  # Bot path on VPS

echo "📦 Pushing to GitHub..."
git push origin main

echo
echo "🔄 Connecting to VPS and updating..."
ssh $VPS_USER@$VPS_HOST << 'EOF'
cd /root/AzabBot  # Update this path
echo "📥 Pulling latest changes..."
git pull
echo "🔧 Running deployment script..."
if [ -f "deploy_ai_update.sh" ]; then
    chmod +x deploy_ai_update.sh
    ./deploy_ai_update.sh
else
    echo "⚠️  Deployment script not found, restarting service manually..."
    sudo systemctl restart azab
fi
echo "✅ Deployment complete!"
sudo systemctl status azab --no-pager | head -10
EOF

echo
echo "✨ VPS deployment finished!"
echo "🧪 Test by asking Azab: 'How do you work?'"