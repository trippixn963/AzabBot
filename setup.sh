#!/bin/bash
# =============================================================================
# SaydnayaBot Setup Script
# =============================================================================
# Quick setup script for deploying SaydnayaBot
# =============================================================================

echo "🚀 Setting up SaydnayaBot..."

# Check if Python 3.10+ is installed
python_version=$(python3 --version 2>&1 | awk '{print $2}')
required_version="3.10"

if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo "❌ Python 3.10+ is required. Current version: $python_version"
    exit 1
fi

echo "✅ Python version: $python_version"

# Check if Poetry is installed
if ! command -v poetry &> /dev/null; then
    echo "📦 Installing Poetry..."
    curl -sSL https://install.python-poetry.org | python3 -
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "✅ Poetry is installed"

# Install dependencies
echo "📦 Installing dependencies..."
poetry install --only main

# Copy .env file if it doesn't exist
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo "📋 Copying .env.example to .env..."
        cp .env.example .env
        echo "⚠️  Please edit .env with your Discord and OpenAI tokens!"
    else
        echo "❌ No .env.example file found!"
        exit 1
    fi
else
    echo "✅ .env file already exists"
fi

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p data logs

echo ""
echo "✅ Setup complete!"
echo ""
echo "To run the bot:"
echo "  poetry run python main.py"
echo ""
echo "Or activate the virtual environment:"
echo "  poetry shell"
echo "  python main.py"
echo ""