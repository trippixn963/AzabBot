-- =============================================================================
-- Enhanced Prison Features Schema
-- =============================================================================
-- New tables for Solitary Confinement, Good Behavior, and Prison Break Detection
-- =============================================================================

-- Solitary Confinement tracking for repeat offenders
CREATE TABLE IF NOT EXISTS solitary_confinement (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prisoner_id INTEGER NOT NULL,
    discord_id TEXT NOT NULL,
    offense_count INTEGER DEFAULT 1,
    severity_level INTEGER DEFAULT 1 CHECK(severity_level >= 1 AND severity_level <= 5),
    last_offense TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    in_solitary BOOLEAN DEFAULT 0,
    solitary_start TIMESTAMP,
    solitary_end TIMESTAMP,
    total_time_in_solitary INTEGER DEFAULT 0, -- in minutes
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prisoner_id) REFERENCES prisoners(id)
);

-- Good Behavior tracking system
CREATE TABLE IF NOT EXISTS good_behavior (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prisoner_id INTEGER NOT NULL,
    discord_id TEXT NOT NULL,
    behavior_score INTEGER DEFAULT 0,
    quiet_minutes INTEGER DEFAULT 0, -- Total minutes being quiet
    last_message TIMESTAMP,
    consecutive_quiet_sessions INTEGER DEFAULT 0,
    harassment_reduction REAL DEFAULT 0.0, -- Percentage reduction in harassment
    good_behavior_streak INTEGER DEFAULT 0, -- Days of good behavior
    last_reset TIMESTAMP,
    rewards_earned TEXT, -- JSON array of earned rewards
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prisoner_id) REFERENCES prisoners(id)
);

-- Prison Break Attempts tracking
CREATE TABLE IF NOT EXISTS prison_breaks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prisoner_id INTEGER NOT NULL,
    discord_id TEXT NOT NULL,
    attempt_type TEXT CHECK(attempt_type IN ('leave_server', 'rejoin_server', 'evade_mute', 'role_manipulation')),
    attempt_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    was_muted BOOLEAN DEFAULT 1,
    mute_remaining_time INTEGER, -- in seconds
    success BOOLEAN DEFAULT 0,
    detection_method TEXT,
    punishment_applied TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prisoner_id) REFERENCES prisoners(id)
);

-- Punishment escalation tracking
CREATE TABLE IF NOT EXISTS punishment_escalation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prisoner_id INTEGER NOT NULL,
    discord_id TEXT NOT NULL,
    current_level INTEGER DEFAULT 1 CHECK(current_level >= 1 AND current_level <= 10),
    total_offenses INTEGER DEFAULT 0,
    solitary_count INTEGER DEFAULT 0,
    break_attempts INTEGER DEFAULT 0,
    bad_behavior_incidents INTEGER DEFAULT 0,
    last_escalation TIMESTAMP,
    next_punishment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prisoner_id) REFERENCES prisoners(id)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_solitary_discord_id ON solitary_confinement(discord_id);
CREATE INDEX IF NOT EXISTS idx_solitary_in_solitary ON solitary_confinement(in_solitary);
CREATE INDEX IF NOT EXISTS idx_good_behavior_discord_id ON good_behavior(discord_id);
CREATE INDEX IF NOT EXISTS idx_good_behavior_score ON good_behavior(behavior_score);
CREATE INDEX IF NOT EXISTS idx_prison_breaks_discord_id ON prison_breaks(discord_id);
CREATE INDEX IF NOT EXISTS idx_prison_breaks_attempt_time ON prison_breaks(attempt_time);
CREATE INDEX IF NOT EXISTS idx_punishment_discord_id ON punishment_escalation(discord_id);
CREATE INDEX IF NOT EXISTS idx_punishment_level ON punishment_escalation(current_level);

-- Create triggers to update timestamps
CREATE TRIGGER update_solitary_timestamp 
AFTER UPDATE ON solitary_confinement
BEGIN
    UPDATE solitary_confinement SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER update_good_behavior_timestamp 
AFTER UPDATE ON good_behavior
BEGIN
    UPDATE good_behavior SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER update_punishment_timestamp 
AFTER UPDATE ON punishment_escalation
BEGIN
    UPDATE punishment_escalation SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- View for current solitary confinement status
CREATE VIEW current_solitary AS
SELECT 
    sc.*,
    p.username,
    p.display_name,
    p.total_messages,
    p.status
FROM solitary_confinement sc
JOIN prisoners p ON sc.prisoner_id = p.id
WHERE sc.in_solitary = 1;

-- View for good behavior rankings
CREATE VIEW good_behavior_rankings AS
SELECT 
    gb.*,
    p.username,
    p.display_name,
    p.status,
    RANK() OVER (ORDER BY gb.behavior_score DESC) as rank
FROM good_behavior gb
JOIN prisoners p ON gb.prisoner_id = p.id
WHERE p.status = 'active';

-- View for recent prison break attempts
CREATE VIEW recent_break_attempts AS
SELECT 
    pb.*,
    p.username,
    p.display_name,
    p.status
FROM prison_breaks pb
JOIN prisoners p ON pb.prisoner_id = p.id
WHERE pb.attempt_time > datetime('now', '-7 days')
ORDER BY pb.attempt_time DESC;