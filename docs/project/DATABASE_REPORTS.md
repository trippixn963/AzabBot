# Database and Reporting Documentation

## Overview

SaydnayaBot includes a comprehensive database system that tracks all prisoner interactions, conversation history, and torture effectiveness. This enables Azab to remember past conversations and generate detailed reports on his psychological operations.

## Database Features

### 1. **Prisoner Tracking**
- Automatic registration of new prisoners
- Tracks first seen and last seen dates
- Records total messages and sessions
- Maintains psychological profiles
- Tracks vulnerability notes
- Monitors torture effectiveness scores
- Status tracking (active, broken, released, resistant)

### 2. **Conversation History**
- Complete message history for each prisoner
- Tracks both prisoner messages and Azab responses
- Records confusion techniques used
- Monitors emotional states
- Timestamps for all interactions

### 3. **Session Management**
- Tracks individual torture sessions
- Records session duration
- Monitors confusion levels (0-10)
- Tracks topics discussed
- Records torture methods used
- Effectiveness ratings (1-5)

### 4. **Analytics**
- Daily activity reports
- Individual prisoner profiles
- Effectiveness metrics
- Memorable quote collection
- Performance tracking

## Report Commands

### Daily Report
```
!report
```
Generates a comprehensive daily summary including:
- Total active prisoners
- New arrivals
- Broken spirits count
- Session statistics
- Most active prisoners

### Prisoner Profile
```
!prisoner [username or discord_id]
```
Generates detailed profile including:
- Basic prisoner information
- Interaction metrics
- Psychological analysis
- Most effective techniques
- Emotional state distribution
- Notable interactions

### Effectiveness Report
```
!effectiveness
```
Shows torture effectiveness metrics:
- Overall performance statistics
- Technique effectiveness rankings
- Success rates
- Highly affected prisoners

### Azab Status
```
!azab
```
Displays Azab's current operational status:
- Current mode (active/standby)
- Today's activity metrics
- Recent performance
- Sample confusion quote

## How Memory Works

### Context Awareness
When Azab responds in prison channels:
1. System retrieves prisoner's history
2. Last 5 messages are included in AI context
3. Azab references past conversations
4. Creates more personalized confusion

### Example
**First Interaction:**
- Prisoner: "Please help me!"
- Azab: "Help? Oh, that reminds me of my cousin who collects stamps..."

**Later Interaction:**
- Prisoner: "I'm still stuck here!"
- Azab: "Still collecting stamps like we discussed? My cousin would be proud!"

### Confusion Techniques Tracked
- **Topic Jumping**: Sudden shifts to unrelated subjects
- **Gaslighting**: Making prisoners question their statements
- **False Memory**: Referencing things that never happened
- **Misunderstanding**: Deliberate misinterpretation

## Database Schema

### Core Tables
1. **prisoners** - User profiles and statistics
2. **torture_sessions** - Individual interaction sessions
3. **conversation_history** - All messages
4. **psychological_analysis** - Prisoner vulnerabilities
5. **daily_reports** - Aggregated daily statistics
6. **memorable_quotes** - Best Azab responses

### Data Retention
- All data is stored locally in SQLite database
- Located in `data/prisoners.db`
- Automatic daily report generation
- No automatic data deletion

## Privacy Considerations

### What's Stored
- Discord usernames and display names
- Message content in prison channels
- Interaction timestamps
- Generated psychological profiles

### What's NOT Stored
- Messages from non-prison channels
- Direct messages
- Personal information beyond Discord profile
- Real user identities

## Performance

### Optimization
- Indexed database queries
- Cached active sessions
- Batch message processing
- Efficient history retrieval

### Limits
- Last 10 messages used for context
- Reports show top 5-10 entries
- Daily reports aggregate data
- Automatic session cleanup

## Configuration

### Database Settings
```env
# Database directory (default: data/)
DATABASE_DIR=data

# Enable database features (default: true)
ENABLE_DATABASE=true
```

### Report Access
Reports are admin-only commands by default. Add admin user IDs to:
```env
IGNORE_USER_IDS=admin_id_1,admin_id_2
```

## Troubleshooting

### Database Not Working
1. Check `data/` directory exists
2. Verify write permissions
3. Check SQLite is installed
4. Review logs for errors

### Reports Not Generating
1. Ensure database service is running
2. Check prisoner data exists
3. Verify report service is registered
4. Check admin permissions

### Memory Not Working
1. Verify database is connected
2. Check session is active
3. Ensure prison channel detection
4. Review conversation history

## Best Practices

### For Administrators
1. Run daily reports regularly
2. Monitor effectiveness metrics
3. Review memorable quotes
4. Track prisoner statuses

### For Maximum Effect
1. Let sessions build over time
2. Don't reset database frequently
3. Allow Azab to reference history
4. Monitor confusion levels

### Database Maintenance
1. Regular backups of `prisoners.db`
2. Monitor database size
3. Archive old sessions if needed
4. Keep memorable quotes

## Future Enhancements

Planned database features:
- Prisoner relationship mapping
- Group session tracking
- Confusion pattern analysis
- Automated profile generation
- Export capabilities
- Advanced analytics dashboard