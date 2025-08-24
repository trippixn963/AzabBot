# 🔒 AzabBot - The Ultimate Prison Guard

<div align="center">
  
  ![Banner](images/BANNER.gif)
  
  <img src="images/PFP.gif" width="200" height="200" alt="AzabBot"/>
  
  **Advanced AI-Powered Prison Guard Bot for Discord**
  
  [![Discord](https://img.shields.io/badge/Discord-Server-7289DA?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/syria)
  [![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
  [![OpenAI](https://img.shields.io/badge/OpenAI-GPT--3.5-412991?style=for-the-badge&logo=openai&logoColor=white)](https://openai.com/)
  [![Status](https://img.shields.io/badge/Status-Active-success?style=for-the-badge)](https://github.com/trippixn963/AzabBot)
  [![Documentation](https://img.shields.io/badge/Documentation-Complete-brightgreen?style=for-the-badge)](https://github.com/trippixn963/AzabBot)
  [![Tests](https://img.shields.io/badge/Tests-Comprehensive-brightgreen?style=for-the-badge)](https://github.com/trippixn963/AzabBot)
  
  *A psychological torture specialist for your Discord server's prison channels*
  
</div>

---

## 📖 Table of Contents

- [About](#-about)
- [Features](#-features)
- [How It Works](#-how-it-works)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Commands](#-commands)
- [Bot Behavior](#-bot-behavior)
- [Technical Architecture](#-technical-architecture)
- [Personality Modes](#-personality-modes)
- [Memory System](#-memory-system)
- [Security Features](#-security-features)
- [Performance Monitoring](#-performance-monitoring)
- [Testing](#-testing)
- [FAQ](#-faq)
- [Disclaimer](#-disclaimer)

---

## 🎭 About

**AzabBot** is an advanced Discord bot designed to psychologically torment users in timeout/mute channels. Inspired by the infamous Sednaya prison, this bot acts as a confused, incompetent guard who harasses prisoners with nonsensical questions and accusations.

Originally created for the **Syria Discord Server** ([discord.gg/syria](https://discord.gg/syria)), AzabBot uses GPT-3.5 to generate contextually aware, dynamically adaptive responses that evolve based on each prisoner's behavior and history.

### Why AzabBot?

- **Automated Prison Management**: No need for moderators to manually harass muted users
- **Entertainment Value**: Turns timeouts into an interactive experience
- **Memory System**: Remembers every prisoner and their history
- **Adaptive AI**: Learns what annoys each user most
- **Production Ready**: Comprehensive error handling, monitoring, and security

---

## ✨ Features

### 🧠 **Intelligent Memory System**
- Remembers every prisoner who enters the jail
- Tracks conversation history and behavior patterns
- Identifies returning prisoners and mentions their visit count
- Builds personality profiles for each user
- Psychological profiling and grudge tracking

### 🎭 **13 Dynamic Personality Modes**
- **Azab the Torturer**: Confused interrogator asking nonsensical questions
- **Syrian Contrarian**: Disagrees with everything
- **Philosophical Pessimist**: Makes everything depressing
- **Sarcastic Comedian**: Mocks with bad jokes
- **Historical Lecturer**: Boring history lessons
- **Conspiracy Theorist**: Everything is a plot
- **Grammar Nazi**: Corrects language obsessively
- **Tech Bro Disruptor**: Silicon Valley nonsense
- **Boomer Complainer**: "Back in my day..."
- **Zen Master Troll**: Fake wisdom and riddles
- **Political Extremist**: Makes everything political
- **Religious Debater**: Theological arguments
- **Gaslighting Expert**: "That never happened"
- **Crime Responder**: Responds with actual mute reasons

### 🔄 **Automatic Features**
- **Auto-Detection**: Detects when users get muted/unmuted
- **Welcome Messages**: Greets new prisoners with personalized torture
- **Release Notifications**: AI-generated sarcastic messages when unmuted
- **Presence Rotation**: Shows "Playing with [prisoner name]"
- **Always Online**: Green status dot, always watching
- **Mute Reason Extraction**: Automatically retrieves and uses actual mute reasons

### 💬 **AI-Powered Responses**
- Uses GPT-3.5 for human-like confusion
- Context-aware responses based on conversation
- Adapts personality based on user reactions
- Generates unique content for each interaction
- Direct address with "you" instead of third person

### 📊 **Advanced Analytics**
- Tracks effectiveness of different approaches
- Monitors user engagement patterns
- Counts debates won/lost
- Records ignored responses
- Performance monitoring and optimization

### 🔒 **Security Features**
- Input validation and sanitization
- Rate limiting and abuse prevention
- Threat detection and blocking
- Permission-based access control
- Security event monitoring

### ⚡ **Performance Monitoring**
- Real-time performance metrics
- Response time tracking
- Resource utilization monitoring
- Performance optimization recommendations
- Automated alerting

---

## 🔧 How It Works

### The Flow

```mermaid
graph TD
    A[User Gets Muted] --> B[AzabBot Detects]
    B --> C[Extract Mute Reason]
    C --> D[Select Personality]
    D --> E[Generate Response]
    E --> F[Send to Discord]
    F --> G[Update Memory]
    G --> H[Track Performance]
    
    I[User Asks "Why am I muted?"] --> J[Crime Detection]
    J --> K[Return Mute Reason]
    K --> L[Direct Response]
```

### Core Components

1. **Bot Core**: Discord.py integration with event handling
2. **AI Service**: OpenAI GPT-3.5 integration for response generation
3. **Personality Service**: Dynamic personality selection and management
4. **Memory Service**: User interaction tracking and history
5. **Prison Service**: Prison-specific features and mute detection
6. **Security System**: Input validation, rate limiting, threat detection
7. **Performance Monitor**: Real-time metrics and optimization
8. **Health Monitor**: System health and resource monitoring

### Technical Stack

- **Language**: Python 3.11+
- **Discord API**: discord.py 2.6.0
- **AI Model**: OpenAI GPT-3.5 Turbo
- **Database**: SQLite3 with connection pooling
- **Async Framework**: asyncio
- **Logging**: Custom tree-style logger
- **Testing**: pytest with comprehensive coverage
- **Security**: Enhanced security system with threat detection
- **Monitoring**: Performance and health monitoring

### Database Schema

**user_memories**
```sql
- user_id (TEXT PRIMARY KEY)
- username (TEXT)
- total_interactions (INTEGER)
- personality_profile (JSON)
- last_seen (TIMESTAMP)
- debate_wins/losses (INTEGER)
```

**conversation_history**
```sql
- id (INTEGER PRIMARY KEY)
- user_id (TEXT)
- message_content (TEXT)
- bot_response (TEXT)
- timestamp (TIMESTAMP)
```

---

## 🎭 Personality Modes

Each mode has unique characteristics:

### Azab the Torturer (Default)
- Asks bizarre questions
- Confuses names and crimes
- Paranoid accusations
- "WHERE DID YOU HIDE THE CHEESE?"

### Syrian Contrarian
- Disagrees with everything
- "No, you're wrong about being wrong"
- Debates pointlessly

### Philosophical Pessimist
- Makes everything existential
- "Your timeout is meaningless, like life"
- Quotes fake philosophers

### Sarcastic Comedian
- Bad jokes and puns
- "Why did the prisoner cross the road? They didn't, they're in jail!"
- Mocks everything

### Crime Responder
- Responds with actual mute reasons
- "You were muted for [actual reason]"
- Direct and mocking responses

---

## 💾 Memory System

### What Gets Stored

1. **User Profile**
   - Total interactions
   - Personality traits
   - Effectiveness scores
   - Visit count

2. **Conversation History**
   - All messages
   - Bot responses
   - Timestamps
   - Response strategies

3. **Analytics**
   - Response effectiveness
   - Ignored messages
   - Debate outcomes
   - Engagement patterns

### Privacy Note

All data is stored locally in SQLite database. No data is sent to external servers except OpenAI for response generation.

---

## 🔒 Security Features

### Input Validation
- Message content sanitization
- Length and pattern validation
- Malicious content detection
- URL and link validation

### Rate Limiting
- Per-user rate limiting
- Per-channel rate limiting
- Global rate limiting
- Adaptive rate limiting

### Threat Detection
- Spam detection
- Malicious content detection
- Bot abuse prevention
- Suspicious behavior detection

### Permission System
- Role-based access control
- User permission validation
- Command permission checking
- Channel access control

---

## ⚡ Performance Monitoring

### Metrics Tracked
- Response time (AI generation, Discord API)
- Resource utilization (CPU, memory, disk)
- Error rates and success rates
- User interaction patterns
- System health indicators

### Optimization Features
- Performance bottleneck detection
- Automated optimization recommendations
- Resource usage alerts
- Performance trend analysis

### Alerting System
- Configurable performance thresholds
- Real-time alert notifications
- Performance degradation detection
- Resource exhaustion warnings

---

## 🧪 Testing

### Test Coverage
- **Unit Tests**: All core functionality
- **Integration Tests**: Service interactions
- **Performance Tests**: Load and stress testing
- **Security Tests**: Input validation and threat detection

### Running Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src

# Run specific test categories
pytest tests/test_bot.py
pytest tests/test_ai_service.py
```

### Test Categories
- Bot initialization and configuration
- Message handling and response generation
- Command processing and validation
- Service integration and dependency injection
- Error handling and recovery mechanisms
- Performance and resource management
- Security validation and threat detection

---

## ❓ FAQ

**Q: Why isn't the bot responding?**
- Check if user has the muted role
- Verify channel ID matches prison channel
- Ensure bot has message permissions
- Check if cooldown is active (10 seconds)

**Q: Can I use this on multiple servers?**
- Yes, but you'll need separate instances
- Each instance needs its own token

**Q: How do I change the personality?**
- Bot automatically selects based on user profile
- Modify `personality_service.py` for custom modes

**Q: Is this against Discord ToS?**
- Use responsibly in designated channels
- Ensure users consent to interaction
- Don't use for actual harassment

**Q: Can I disable the AI?**
- Not recommended, core functionality depends on it
- You can use fallback responses by removing API key

**Q: How do I get the bot to respond with mute reasons?**
- The bot automatically detects questions like "Why am I muted?"
- It extracts the actual mute reason from Discord audit logs
- Responds directly with the reason in a mocking way

**Q: What if the bot stops responding to messages?**
- Check the bot's health status
- Verify all dependencies are installed
- Check for rate limiting or cooldown issues
- Review logs for error messages

---

## ⚠️ Disclaimer

**IMPORTANT NOTICE:**

This is a **PERSONAL PROJECT** created for entertainment purposes on the Syria Discord server. 

- **NO SUPPORT PROVIDED** - Use at your own risk
- **NO ISSUES ADDRESSED** - This is not maintained
- **MAY BREAK ANYTIME** - No guarantees of functionality
- **NOT FOR HARASSMENT** - Use responsibly in consenting communities

The bot is designed for entertainment in designated timeout channels where users expect this interaction. Do not use for actual harassment or in channels where users don't consent to this type of content.

---

## 📝 License

This project is provided as-is with no license. Use at your own risk.

---

## 🙏 Credits

Developed by **حَـــــنَّـــــا** (John Hamwi) for [discord.gg/syria](https://discord.gg/syria)

**Version:** 3.0.0 | **Status:** Production Ready | **Support:** None

---

<div align="center">
  
  ![PFP](images/PFP.gif)
  
  **"Welcome to Sednaya. You'll never leave."**
  
</div>