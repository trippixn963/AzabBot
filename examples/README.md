# Code Examples

These are **production modules** extracted from AzabBot's source code. They demonstrate the architecture, patterns, and code quality used across the full 30K+ line codebase.

## Modules

### [`case_log/`](case_log/) — Case Management System
Forum-based moderation case tracking. Every mute, ban, and warn creates a thread with auto-tags, evidence, and resolution tracking. Uses tag stacking (Mute + Automod + Evasion on the same case).

### [`tickets/`](tickets/) — Support Ticket System
Full ticket workflow with forum threads, staff claim/transfer/close, HTML transcript generation, and auto-close on inactivity.

### [`antispam/`](antispam/) — Spam Detection Engine
Multi-layer spam detection with pattern matching, rate limiting, duplicate content detection, and reputation-based escalation.

### [`prison/`](prison/) — Prison Handler
Manages the muted user lifecycle: personalized welcome embeds, offense tracking, VC kick with progressive timeout, release announcements, and appeal button generation.

### [`server_logs/`](server_logs/) — Audit Logging
Comprehensive server logging with 20+ event types routed to categorized forum threads. Covers messages, members, voice, roles, channels, and moderation actions.

### [`mute/`](mute/) — Mute Command System
Cross-server mute/unmute with absent user support (pending mutes enforce on rejoin), concurrent mute detection, XP drain on repeat offenses, and buyout system.

### [`database/`](database/) — Database Layer
SQLite WAL-mode database with mixin architecture (17 specialized classes), schema management, and migration support.

### [`api/`](api/) — FastAPI Backend
REST + WebSocket API setup with lifespan management, rate limiting middleware, and socket reuse for instant port rebind on restart.

---

> **Note:** These modules import from `src.core`, `src.utils`, and other internal packages not included in this repository. They are provided as reference code, not runnable examples.
