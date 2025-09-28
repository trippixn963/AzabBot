#!/bin/bash
# Azab Bot - AI Self-Awareness Deployment Script
# Version 2.4.0
# ==============================================

echo "🧠 Deploying Azab AI Self-Awareness System v2.4.0"
echo "=================================================="
echo

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running on VPS or local
if [ -f "/etc/systemd/system/azab.service" ]; then
    echo -e "${GREEN}✓${NC} Detected VPS environment with systemd"
    DEPLOYMENT_ENV="vps"
else
    echo -e "${YELLOW}⚠${NC} Running in local/development environment"
    DEPLOYMENT_ENV="local"
fi

echo
echo "📋 Changes in v2.4.0:"
echo "  • Added complete self-awareness system"
echo "  • Created system_knowledge.py module"
echo "  • Enhanced AI service with technical knowledge"
echo "  • Improved family member responses"
echo "  • Added technical question detection"
echo

# Step 1: Check Python version
echo "1️⃣ Checking Python version..."
python_version=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
if [ "$python_version" == "3.12" ] || [ "$python_version" == "3.11" ] || [ "$python_version" == "3.10" ]; then
    echo -e "  ${GREEN}✓${NC} Python $python_version is supported"
else
    echo -e "  ${YELLOW}⚠${NC} Python $python_version detected (3.10+ recommended)"
fi

# Step 2: Check required files
echo
echo "2️⃣ Verifying new files..."
if [ -f "src/services/system_knowledge.py" ]; then
    echo -e "  ${GREEN}✓${NC} system_knowledge.py found"
else
    echo -e "  ${RED}✗${NC} system_knowledge.py missing!"
    exit 1
fi

# Step 3: Check dependencies
echo
echo "3️⃣ Checking dependencies..."
if python3 -c "import openai; print(openai.__version__)" 2>/dev/null | grep -q "0.28"; then
    echo -e "  ${GREEN}✓${NC} OpenAI 0.28.x installed"
else
    echo -e "  ${YELLOW}⚠${NC} OpenAI version mismatch - installing correct version..."
    pip3 install openai==0.28.1 --user 2>/dev/null || pip3 install openai==0.28.1
fi

# Step 4: Test imports
echo
echo "4️⃣ Testing imports..."
python3 -c "from src.services.system_knowledge import get_system_knowledge" 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "  ${GREEN}✓${NC} System knowledge module imports successfully"
else
    echo -e "  ${RED}✗${NC} Import error - check Python path"
    exit 1
fi

# Step 5: Backup current version (if on VPS)
if [ "$DEPLOYMENT_ENV" == "vps" ]; then
    echo
    echo "5️⃣ Creating backup..."
    backup_dir="backups/backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p $backup_dir
    cp -r src/ $backup_dir/
    echo -e "  ${GREEN}✓${NC} Backup created in $backup_dir"
fi

# Step 6: Deploy on VPS
if [ "$DEPLOYMENT_ENV" == "vps" ]; then
    echo
    echo "6️⃣ Restarting Azab service..."
    sudo systemctl restart azab
    sleep 3

    if systemctl is-active --quiet azab; then
        echo -e "  ${GREEN}✓${NC} Azab service restarted successfully"
        echo
        echo "📊 Service status:"
        sudo systemctl status azab --no-pager | head -10
    else
        echo -e "  ${RED}✗${NC} Service restart failed!"
        echo "  Run: sudo journalctl -u azab -n 50"
        exit 1
    fi
else
    echo
    echo "6️⃣ Local deployment - start bot manually:"
    echo "   python3 main.py"
fi

echo
echo "✨ Deployment complete!"
echo
echo "🧪 Test the new features:"
echo "  • Ask Azab: 'How do you work?'"
echo "  • Ask Azab: 'What are your features?'"
echo "  • Ask Azab: 'Explain your architecture'"
echo "  • Ask Azab: 'What version are you?'"
echo
echo "📝 Version 2.4.0 - AI Self-Awareness System"
echo "   Azab now knows everything about himself!"
echo