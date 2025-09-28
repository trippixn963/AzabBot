# Changelog

All notable changes to the Azab Discord Bot will be documented in this file.

## [2.4.0] - 2025-09-28

### 🧠 AI Self-Awareness System

#### Complete Technical Knowledge Integration
- **System Knowledge Module**: Added comprehensive knowledge base about bot's architecture and features
- **Self-Aware AI**: Azab can now explain how he works, his features, architecture, and capabilities
- **Technical Question Detection**: Automatically detects and responds to technical queries with accurate information
- **Enhanced Family Responses**: All family members (dad, uncle, brother) get intelligent technical responses

#### Knowledge Base Features
- **Architecture Details**: Full knowledge of Python 3.12, Discord.py 2.3.2, OpenAI integration
- **Feature Explanations**: Can explain prison system, family system, database queries in detail
- **Codebase Statistics**: Knows file structure, line counts, and organization
- **Configuration Awareness**: Understands all 30+ environment variables and settings
- **Capability Understanding**: Knows what he can and cannot do

### 🔧 Technical Improvements
- Created `system_knowledge.py` module with complete bot documentation
- Integrated `_check_technical_question()` method in AI service
- Enhanced system prompts with full technical knowledge
- Added technical context injection for accurate responses
- Improved conversation memory with technical awareness

---

## [2.3.0] - 2025-09-28

### 🎉 Major Features

#### Family System
- **Added Uncle Support**: Bot now recognizes and responds to Uncle Zaid (configurable via `UNCLE_ID`)
- **Added Brother Support**: Bot now recognizes and responds to Brother Ward (configurable via `BROTHER_ID`)
- **Family Privileges**: Family members bypass all restrictions and channel limitations
- **Unique Relationships**: Each family member gets personalized responses matching their relationship

#### Enhanced AI Intelligence
- **Conversational AI Overhaul**: Complete redesign of developer responses for natural, ChatGPT-like conversations
- **Context Awareness**: Bot maintains conversation history for better contextual responses
- **Dynamic Tone Matching**: AI adapts tone based on message context (casual/serious/technical)

#### Database Query Integration
- **Prison Statistics**: Bot can now query and report real-time prison statistics
- **User Lookup**: Ask "who is @username" to get detailed mute history
- **Top Prisoners**: Query most muted members with "who is the most jailed member"
- **Current Status**: Check who's currently in jail with real-time data
- **Advanced Queries**: Support for longest sentences, total time served, and more

### 🔧 Improvements

#### Error Handling
- **Graceful Error Recovery**: Added comprehensive try-catch blocks to all event handlers
- **No More Crashes**: Bot continues operating even when individual messages fail
- **Better Logging**: Enhanced error logging with specific error types

#### Configuration Management
- **Environment Variables**: Moved 30+ hardcoded values to .env configuration
- **Flexible Settings**: All timing, limits, and thresholds now configurable
- **No More Magic Numbers**: Replaced all hardcoded values with environment variables

#### Time Display Fixes
- **Fixed Negative Time**: Duration calculations now use absolute values
- **Better Formatting**: Time displayed as "2d 5h 30m" instead of raw minutes
- **Accurate Tracking**: Fixed SQL queries for proper duration calculation

#### Discord Integration
- **Proper User Mentions**: Uses `<@userid>` format for clickable mentions
- **Username Accuracy**: Fixed issue where bot called everyone "Golden"
- **Response Separation**: AI responses now sent outside embeds for better readability

### 🐛 Bug Fixes
- Fixed negative time display in prisoner duration (-203 minutes issue)
- Fixed incorrect username attribution in responses
- Fixed query parsing to prioritize statistical queries over username searches
- Fixed channel restriction bypass for family members
- Removed credits command completely from codebase

### 📝 Technical Changes
- Created new database methods: `get_current_prisoners()`, `get_longest_sentence()`, `get_prison_stats()`, `search_prisoner_by_name()`
- Added AI service methods: `generate_uncle_response()`, `generate_brother_response()`
- Improved modular architecture with better separation of concerns
- Enhanced conversation memory system for context retention
- Updated OpenAI parameters for more natural responses (temperature: 0.9, max_tokens: 300 for family)

### 🔐 Security
- Family member IDs stored securely in environment variables
- Maintained privilege separation between family and regular users
- Protected sensitive operations behind family-only access

### 📦 Dependencies
- Python 3.12
- Discord.py 2.3.2
- OpenAI 0.28.1
- SQLite3 (built-in)

### 🚀 Deployment
- Fully compatible with systemd service management
- Automatic state persistence across restarts
- VPS-ready with proper error recovery

---

## [2.2.0] - Previous Release
- Initial prison system implementation
- Basic AI ragebaiting functionality
- Mute tracking and database logging