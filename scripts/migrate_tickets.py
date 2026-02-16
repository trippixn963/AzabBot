"""Migrate archived tickets back to main tickets table."""
import sqlite3

conn = sqlite3.connect("data/azab.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Get all archived tickets
cur.execute("SELECT * FROM ticket_history")
archived = cur.fetchall()

print("Found %d archived tickets to migrate" % len(archived))

migrated = 0
for row in archived:
    ticket_id = row["ticket_id"]
    try:
        # Use 0 as placeholder for deleted channels
        cur.execute("""
        INSERT INTO tickets (
            ticket_id, user_id, guild_id, thread_id, category, subject, status,
            priority, claimed_by, assigned_to, created_at, last_activity_at,
            warned_at, closed_at, closed_by, close_reason, claimed_at,
            transcript_html, control_panel_message_id, transcript, case_id, transcript_token
        ) VALUES (?, ?, ?, 0, ?, ?, 'closed', 'normal', ?, NULL, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)
        """, (
            row["ticket_id"], row["user_id"], row["guild_id"],
            row["category"], row["subject"], row["claimed_by"],
            row["created_at"], row["closed_at"], row["closed_at"],
            row["closed_by"], row["close_reason"], row["claimed_at"],
            row["transcript_html"], row["transcript"], row["transcript_token"]
        ))
        migrated += 1
        print("  Migrated %s" % ticket_id)
    except sqlite3.IntegrityError:
        print("  SKIP %s: already exists" % ticket_id)
    except Exception as e:
        print("  ERROR %s: %s" % (ticket_id, str(e)))

conn.commit()
print("\nTotal migrated: %d" % migrated)

# Verify
cur.execute("SELECT count(ticket_id) FROM tickets")
print("Total tickets now: %d" % cur.fetchone()[0])
cur.execute("SELECT count(ticket_id) FROM tickets WHERE status = 'closed'")
print("Closed tickets: %d" % cur.fetchone()[0])
