# 🤖 SaydnayaBot - Simple Personal Setup

This bot is for personal/single server use only. No CI/CD needed!

## Quick Setup

1. **Install Python 3.11+**
2. **Install dependencies:**
   ```bash
   pip install poetry
   poetry install
   ```

3. **Configure your bot:**
   ```bash
   cp .env.example .env
   # Edit .env with your Discord token and OpenAI key
   ```

4. **Run the bot:**
   ```bash
   python main.py
   ```

That's it! The bot will run on your server.

## To Update the Bot

Just pull the latest changes and restart:
```bash
git pull
python main.py
```

## No Testing Needed

This is a personal bot, so:
- No CI/CD pipelines
- No automated tests
- No GitHub Actions
- Just run it and enjoy!

## Bot Management

- **Start:** `python main.py`
- **Stop:** `Ctrl+C`
- **Run in background:** `python main.py &`
- **Check if running:** `ps aux | grep main.py`