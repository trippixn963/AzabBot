# Changelog

## [1.5.0] - 2025-08-10

### 🎉 Major Features Added

#### 🧠 Conversation Memory System
- **Persistent User Memory**: Bot now remembers every user it interacts with
- **Personality Profiling**: Tracks user behavior patterns (aggression, humor, debate skills)
- **Conversation History**: Stores all messages for context-aware responses
- **Returning Prisoner Detection**: Recognizes when users return to jail and mentions their visit count
- **SQLite Database**: All memories persist across bot restarts

#### 🎭 Advanced Personality Modes (13 Unique Personalities)
- **Dynamic Personality Selection**: Bot adapts its personality based on user profile
- **Effectiveness Tracking**: Learns which approaches work best with each user
- **Personality Modes Include**:
  - Azab the Torturer (confused interrogator)
  - Syrian Contrarian (debates everything)
  - Philosophical Pessimist
  - Sarcastic Comedian
  - Historical Lecturer
  - Conspiracy Theorist
  - Grammar Nazi
  - Tech Bro Disruptor
  - Boomer Complainer
  - Zen Master Troll
  - Political Extremist
  - Religious Debater
  - Gaslighting Expert

#### 🚨 Auto-Detection Features
- **New Prisoner Detection**: Automatically welcomes new muted users
- **Returning Prisoner Recognition**: Special messages for repeat offenders with visit count
- **Role-Based Triggering**: Only responds to users with specific muted role
- **Prison Channel Isolation**: Only operates in designated prison channel

#### 🎮 Dynamic Rich Presence
- **Default Status**: "Watching ⛓ Sednaya"
- **Active Status**: "Playing with [prisoner name]"
- **Rotation System**: Cycles through all current prisoners every 10 seconds
- **Auto-Update**: Updates when prisoners join/leave jail

#### 🔧 Bot Improvements
- **Always Online**: Bot no longer needs activation - always ready
- **Message Batching**: Collects messages for 2 seconds before responding for better context
- **Smart Cooldowns**: 10-second cooldown to prevent spam
- **Multi-Message Context**: Reads all messages in a batch for coherent responses

### 🐛 Bug Fixes
- Fixed third-person speech issues - bot now uses "I" and "you" properly
- Fixed slash command timeout errors with deferred responses
- Fixed duplicate PRISON_CHANNEL_IDS configuration issue
- Fixed rate limiting preventing continuous responses
- Removed message batching conflicts
- Fixed configuration loading for prison channel IDs

### 🛡️ Error Handling & Logging
- **Comprehensive Error Handling**: Try-catch blocks on all critical operations
- **Full Traceback Logging**: Complete stack traces for debugging
- **Contextual Logging**: All errors include user IDs, channel IDs, and relevant context
- **Debug Mode**: Extensive DEBUG logging for troubleshooting
- **Graceful Fallbacks**: AI service falls back to predefined responses on failure
- **Timeout Protection**: 30-second timeout on OpenAI API calls

### 📊 Technical Improvements
- **Service-Oriented Architecture**: Clean separation of concerns
- **Dependency Injection**: Proper service management
- **Health Monitoring**: Service health checks (with minor issues to fix)
- **Database Persistence**: SQLite for reliable data storage
- **Memory Optimization**: Efficient caching and cleanup
- **Tree-Style Logging**: Beautiful, readable log output

### ⚙️ Configuration Changes
- Bot is now always active by default
- Simplified role and channel configuration
- Better environment variable handling
- Removed activation/deactivation commands (bot is always on)

### 📝 Known Issues
- Health check metrics parameter error (doesn't affect functionality)
- Some services report unhealthy in monitoring (bot still works fine)

### 🔄 Migration Notes
- Bot will automatically create memory database on first run
- Existing configurations will continue to work
- Slash commands have been updated (activate/deactivate now just show status)

---

## [1.0.0] - 2025-08-09
- Initial release
- Basic bot functionality
- Prison channel harassment mode
- Developer commands
- Basic logging system