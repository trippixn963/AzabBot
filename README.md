# SaydnayaBot 🔥

A sophisticated Discord bot implementing Azab, a psychological torturer character for prison/mute channels. Built with modern Python architecture and AI-powered responses.

> ⚠️ **Important**: This bot is designed for entertainment purposes in designated timeout/mute channels only. Please use responsibly and ensure all participants consent to this type of interaction.

## Features ✨

- **Automated Operation**: Fully autonomous - just activate and let it work
- **AI-Powered Responses**: Human-like confusion using GPT-3.5
- **Memory System**: Remembers all prisoners and conversations
- **Smart Detection**: Auto-detects prison channels by keywords
- **Developer Control**: Only you can control with `/activate` and `/deactivate`
- **Professional Architecture**: Clean, maintainable, production-ready code

## Quick Start 🚀

### Prerequisites

- Python 3.10+
- Discord Bot Token
- OpenAI API Key

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/saydnayabot.git
cd saydnayabot
```

2. Install Poetry (if not already installed):
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

3. Install dependencies:
```bash
poetry install
# or for production only (no dev dependencies)
poetry install --only main
```

4. Copy and configure `.env`:
```bash
cp .env.example .env
# Edit .env with your tokens
```

5. Run the bot:
```bash
poetry run python main.py
```

## Configuration 🔧

Create a `.env` file in the root directory:

```env
# Discord Configuration
DISCORD_TOKEN=your_discord_bot_token_here

# Developer Configuration (only this ID can control the bot)
DEVELOPER_ID=your_discord_user_id_here

# OpenAI Configuration
OPENAI_API_KEY=sk-your-openai-api-key-here

# Prison Channel Configuration (optional)
PRISON_CHANNEL_IDS=channel_id1,channel_id2
```

## Commands 📝

Only the developer can use these commands:

- `/activate` - Start Azab's psychological operations
- `/deactivate` - Give prisoners temporary relief

## How It Works 🧠

1. **Channel Detection**: Automatically detects prison channels by keywords (prison, jail, timeout, mute, etc.)
2. **Azab Personality**: Asks prisoners why they're muted, then confuses them with unrelated topics
3. **Memory System**: Stores all conversations and builds psychological profiles
4. **Rate Limiting**: 1-minute cooldown per prisoner to prevent spam

## Project Structure 📁

```
saydnayabot/
├── src/
│   ├── bot/           # Main bot implementation
│   ├── core/          # Core utilities (logging, DI, etc.)
│   ├── services/      # Business logic services
│   ├── config/        # Configuration management
│   └── utils/         # Utility functions
├── data/              # Database files (auto-created)
├── logs/              # Log files (auto-managed)
├── docs/              # Documentation
├── main.py            # Entry point
├── pyproject.toml     # Project configuration
└── .env               # Environment variables
```

## Development 🛠️

### Code Style

This project uses:
- `black` for code formatting
- `isort` for import sorting
- `flake8` for linting
- `ruff` for fast Python linting

Setup pre-commit hooks:
```bash
poetry run pre-commit install
```

Run all checks:
```bash
poetry run pre-commit run --all-files
```

### Testing

```bash
poetry run pytest
```

### Running without Poetry

If you prefer not to use Poetry:
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install from requirements
pip install discord.py python-dotenv aiofiles openai aiohttp pytz psutil aiosqlite

# Run
python main.py
```

## Features in Detail 📋

### Azab's Personality
- Asks about mute reasons casually
- Immediately ignores answers and talks about random topics
- Creates genuine confusion through topic jumping
- References past conversations incorrectly

### Database System
- SQLite for reliable local storage
- Tracks prisoner profiles
- Stores conversation history
- Generates reports (internal use)

### Log Management
- Automatic deletion after 7 days
- Compression after 1 day
- Error logs kept for 30 days
- Runs cleanup every 6 hours

### Instance Management
- Auto-terminates existing instances on startup
- Prevents conflicts and duplicates
- Clean shutdown handling

## License 📄

MIT License - See LICENSE file for details

## Support 💬

For issues or questions:
- Open an issue on GitHub
- Contact the developer

## Acknowledgments 🙏

Built with:
- discord.py - Discord API wrapper
- OpenAI API - AI response generation
- Python - Because it's awesome

---

**Note**: This bot is for entertainment purposes in designated channels only. Use responsibly.