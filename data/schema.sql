-- =============================================================================
-- SaydnayaBot Database Schema
-- =============================================================================
-- Database schema for tracking prisoners, conversations, and torture sessions
-- This schema supports Azab's memory and report generation capabilities
-- =============================================================================

-- Prisoners table - tracks all users who have interacted with Azab
CREATE TABLE IF NOT EXISTS prisoners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id TEXT UNIQUE NOT NULL,
    username TEXT NOT NULL,
    display_name TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_messages INTEGER DEFAULT 0,
    total_sessions INTEGER DEFAULT 0,
    psychological_profile TEXT,
    vulnerability_notes TEXT,
    mute_reason TEXT,
    mute_reason_extracted BOOLEAN DEFAULT 0,
    torture_effectiveness_score REAL DEFAULT 0.0,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'broken', 'released', 'resistant')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Torture sessions - tracks individual interaction sessions
CREATE TABLE IF NOT EXISTS torture_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prisoner_id INTEGER NOT NULL,
    channel_id TEXT NOT NULL,
    channel_name TEXT,
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP,
    message_count INTEGER DEFAULT 0,
    confusion_level INTEGER DEFAULT 0 CHECK(confusion_level >= 0 AND confusion_level <= 10),
    topics_discussed TEXT, -- JSON array of random topics Azab brought up
    torture_methods TEXT, -- JSON array of methods used (gaslighting, topic_jumping, etc)
    session_notes TEXT,
    effectiveness_rating INTEGER CHECK(effectiveness_rating >= 1 AND effectiveness_rating <= 5),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prisoner_id) REFERENCES prisoners(id)
);

-- Conversation history - tracks all messages
CREATE TABLE IF NOT EXISTS conversation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    prisoner_id INTEGER NOT NULL,
    message_type TEXT NOT NULL CHECK(message_type IN ('prisoner', 'azab')),
    content TEXT NOT NULL,
    confusion_technique TEXT, -- For Azab messages: what technique was used
    emotional_state TEXT, -- Detected emotional state of prisoner
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES torture_sessions(id),
    FOREIGN KEY (prisoner_id) REFERENCES prisoners(id)
);

-- Psychological analysis - tracks prisoner weaknesses and triggers
CREATE TABLE IF NOT EXISTS psychological_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prisoner_id INTEGER NOT NULL,
    analysis_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    identified_triggers TEXT, -- JSON array of emotional triggers
    vulnerabilities TEXT, -- JSON array of psychological vulnerabilities
    effective_topics TEXT, -- JSON array of topics that confuse them most
    resistance_patterns TEXT, -- JSON array of how they try to resist
    recommended_approaches TEXT, -- JSON array of recommended torture approaches
    analysis_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prisoner_id) REFERENCES prisoners(id)
);

-- Daily reports - aggregated statistics
CREATE TABLE IF NOT EXISTS daily_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date DATE UNIQUE NOT NULL,
    total_prisoners INTEGER DEFAULT 0,
    new_prisoners INTEGER DEFAULT 0,
    total_messages INTEGER DEFAULT 0,
    total_sessions INTEGER DEFAULT 0,
    average_confusion_level REAL DEFAULT 0.0,
    most_effective_techniques TEXT, -- JSON array
    prisoner_breakdown TEXT, -- JSON object with status counts
    notable_incidents TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Torture effectiveness metrics
CREATE TABLE IF NOT EXISTS effectiveness_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prisoner_id INTEGER NOT NULL,
    metric_date DATE NOT NULL,
    messages_sent INTEGER DEFAULT 0,
    confusion_incidents INTEGER DEFAULT 0,
    topic_changes INTEGER DEFAULT 0,
    emotional_breakdowns INTEGER DEFAULT 0,
    resistance_attempts INTEGER DEFAULT 0,
    effectiveness_score REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prisoner_id) REFERENCES prisoners(id),
    UNIQUE(prisoner_id, metric_date)
);

-- Memorable quotes - funny or effective Azab responses
CREATE TABLE IF NOT EXISTS memorable_quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    prisoner_id INTEGER NOT NULL,
    prisoner_message TEXT NOT NULL,
    azab_response TEXT NOT NULL,
    confusion_type TEXT,
    effectiveness_rating INTEGER CHECK(effectiveness_rating >= 1 AND effectiveness_rating <= 5),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES torture_sessions(id),
    FOREIGN KEY (prisoner_id) REFERENCES prisoners(id)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_prisoners_discord_id ON prisoners(discord_id);
CREATE INDEX IF NOT EXISTS idx_prisoners_status ON prisoners(status);
CREATE INDEX IF NOT EXISTS idx_sessions_prisoner_id ON torture_sessions(prisoner_id);
CREATE INDEX IF NOT EXISTS idx_sessions_start_time ON torture_sessions(start_time);
CREATE INDEX IF NOT EXISTS idx_conversations_session_id ON conversation_history(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_prisoner_id ON conversation_history(prisoner_id);
CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversation_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_analysis_prisoner_id ON psychological_analysis(prisoner_id);
CREATE INDEX IF NOT EXISTS idx_daily_reports_date ON daily_reports(report_date);
CREATE INDEX IF NOT EXISTS idx_metrics_prisoner_date ON effectiveness_metrics(prisoner_id, metric_date);

-- Create triggers to update timestamps
CREATE TRIGGER update_prisoners_timestamp 
AFTER UPDATE ON prisoners
BEGIN
    UPDATE prisoners SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- Create views for common queries
CREATE VIEW active_prisoners AS
SELECT 
    p.*,
    COUNT(DISTINCT ts.id) as total_sessions_count,
    AVG(ts.confusion_level) as avg_confusion_level,
    MAX(ts.start_time) as last_session_time
FROM prisoners p
LEFT JOIN torture_sessions ts ON p.id = ts.prisoner_id
WHERE p.status = 'active'
GROUP BY p.id;

CREATE VIEW prisoner_statistics AS
SELECT 
    p.discord_id,
    p.username,
    p.display_name,
    p.total_messages,
    p.total_sessions,
    p.torture_effectiveness_score,
    p.status,
    COUNT(DISTINCT DATE(ch.timestamp)) as days_active,
    COUNT(ch.id) as total_interactions,
    AVG(CASE WHEN ch.message_type = 'azab' THEN LENGTH(ch.content) ELSE NULL END) as avg_azab_response_length
FROM prisoners p
LEFT JOIN conversation_history ch ON p.id = ch.prisoner_id
GROUP BY p.id;