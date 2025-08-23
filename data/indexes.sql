-- =============================================================================
-- Database Indexes for Performance Optimization
-- =============================================================================

-- Prisoners table indexes
CREATE INDEX IF NOT EXISTS idx_prisoners_discord_id ON prisoners(discord_id);
CREATE INDEX IF NOT EXISTS idx_prisoners_status ON prisoners(status);
CREATE INDEX IF NOT EXISTS idx_prisoners_last_seen ON prisoners(last_seen);

-- Torture sessions indexes
CREATE INDEX IF NOT EXISTS idx_sessions_prisoner_id ON torture_sessions(prisoner_id);
CREATE INDEX IF NOT EXISTS idx_sessions_channel_id ON torture_sessions(channel_id);
CREATE INDEX IF NOT EXISTS idx_sessions_start_time ON torture_sessions(start_time);
CREATE INDEX IF NOT EXISTS idx_sessions_end_time ON torture_sessions(end_time);

-- Conversation history indexes
CREATE INDEX IF NOT EXISTS idx_conversation_session_id ON conversation_history(session_id);
CREATE INDEX IF NOT EXISTS idx_conversation_prisoner_id ON conversation_history(prisoner_id);
CREATE INDEX IF NOT EXISTS idx_conversation_timestamp ON conversation_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_conversation_message_type ON conversation_history(message_type);

-- Psychological analysis indexes
CREATE INDEX IF NOT EXISTS idx_psych_prisoner_id ON psychological_analysis(prisoner_id);
CREATE INDEX IF NOT EXISTS idx_psych_analysis_date ON psychological_analysis(analysis_date);

-- Daily reports indexes
CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_reports(report_date);

-- Effectiveness metrics indexes
CREATE INDEX IF NOT EXISTS idx_metrics_prisoner_id ON effectiveness_metrics(prisoner_id);
CREATE INDEX IF NOT EXISTS idx_metrics_date ON effectiveness_metrics(metric_date);

-- Composite indexes for common queries
CREATE INDEX IF NOT EXISTS idx_sessions_prisoner_time ON torture_sessions(prisoner_id, start_time);
CREATE INDEX IF NOT EXISTS idx_conversation_session_type ON conversation_history(session_id, message_type);
CREATE INDEX IF NOT EXISTS idx_metrics_prisoner_date ON effectiveness_metrics(prisoner_id, metric_date);