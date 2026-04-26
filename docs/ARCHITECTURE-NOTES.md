# Architecture Notes — Things That Look Like Bugs But Aren't

> **For future code reviewers:** read this first. Every entry below
> has been flagged at least once by an audit (REVIEW.md, REVIEW-2.md,
> or a model-driven scan) as a problem to fix. Each one has been
> investigated, and the listed design is the **intended** state.
> If you find something here that you genuinely believe should
> change, raise it with the owner before "fixing" it — the
> reasoning is in the linked file.
>
> Last reviewed: 2026-04-25. When this doc gets stale, prune.

---

## 1. Owner-only gating on `/suggest`, `/bug`, `/link`

**What looks like a bug:** All state-changing buttons on the
suggestion / bug-report / link panels are gated on `is_owner(...)`.
A scanner sees `has_mod_role` used everywhere else and flags this
as "mods locked out of an entire feature surface."

**Why it's intentional:** These three commands are the bot owner's
**personal triage queues**. Only the owner decides what gets
implemented vs. declined. Mods can submit, but only the owner
acts on submissions.

**Where:**
- `src/commands/suggest/views.py` (header docstring)
- `src/commands/bug/views.py` (header docstring)

**REVIEW-2 (2026-04-25)** flagged this as a bug; owner-only model
was reconfirmed as intended. Comment headers explicitly say
"Do not 'fix' the gating to has_mod_role."

---

## 2. Two "backup" modules — `services/server_backup/` vs `services/backup/`

**What looks like a bug:** Two top-level packages with "backup" in
the name. Auditors flag as duplicate / candidate for collapse.

**Why it's intentional:** They're different concerns at different
layers:

| Module | Backs up what | Where it goes | Lifecycle |
|---|---|---|---|
| `services/server_backup/` | Discord guild snapshots — roles, channels, perms, emojis, member-role assignments | Local snapshot files | Manual / scheduled, used for **nuke recovery** |
| `services/backup/` | The bot's SQLite database file | Cloudflare R2 (off-site) | Hourly, automatic |

The two never share data. Collapsing them would mix Discord-state
recovery with local-data integrity, which are different failure
modes with different recovery procedures.

---

## 3. Two "transcript" modules — `services/ticket_transcript/` vs `services/tickets/transcript/`

**What looks like a bug:** Two transcript modules. Auditors flag
the duplication.

**Why it's intentional:** Different lifecycle, different output,
different consumer:

| Module | Lifecycle | Output | Consumed by |
|---|---|---|---|
| `services/ticket_transcript/` | LIVE — runs while ticket is open | Forum-thread messages (impersonated via webhook) | Mods watching the live thread |
| `services/tickets/transcript/` | POST-CLOSE — runs after ticket closes | JSON blob | React SPA at `/azab/ticket-transcripts/:ticketId` |

The live version uses Discord's forum threads for real-time
visibility; the post-close version produces a self-contained JSON
artifact that survives independently of Discord.

---

## 4. `@everyone` in raid-lockdown / nuke-attempt alerts

**What looks like a bug:** The strings `"@everyone 🚨 RAID DETECTED…"`
and `"@everyone 🚨 NUKE ATTEMPT DETECTED…"` are sent literally with
`allowed_mentions=AllowedMentions(everyone=True, …)`. Auditors say
"@everyone wakes the whole server at 3 AM."

**Why it's intentional:** The alert channel is in the
`mod_server_id` guild — a **private staff guild** where every
member IS staff. `@everyone` here is the way to page the entire
mod team. The `moderation_role_id` mention does NOT work in this
context because that role is defined on the **main public**
server and doesn't exist in the mods server.

**Where:**
- `src/services/raid_lockdown/service.py` (`@everyone` block, see inline comment)
- `src/services/antinuke/service.py` (same)

A previous attempt to "fix" this on 2026-04-25 by swapping in the
mod-role mention silently broke the alert (see git history).

---

## 5. `main.py` is gitignored

**What looks like a bug:** Other source files are tracked, but
`main.py` is in `.gitignore`. Looks like an oversight.

**Why it's intentional:** `main.py` is the deploy entry point. It
has been kept private since the showcase-repo split (`a69eff1`)
and stayed private when `src/` was re-tracked on 2026-04-25 (see
the comment in `.gitignore`).

---

## 6. Pipeline two-input rule for handlers

**What looks like a bug:** Each handler in
`src/handlers/messages/pipeline/` only has `self.cog` as an
instance attribute. Looks like the bot/config/db references are
"missing."

**Why it's intentional:** Spec lock-in (see
`docs/superpowers/shipped/2026-04-24-on-message-pipeline/design.md`).
Handlers receive `cog` at construction (cross-message mutable
state ONLY) and `ctx` per call (everything else, including
`ctx.bot` / `ctx.config` / `ctx.db`). Storing bot/config/db on the
handler instance is a bug — services can be re-bound at runtime,
config can hot-reload, and a stale snapshot on the handler defeats
both. The rule is documented inline at
`src/handlers/messages/pipeline/base.py`.

---

## 7. `case_forum.py` returns `STOP` after `handle_reason_reply`

**What looks like a bug:** The pre-pipeline `on_message.py` did
NOT return after `handle_reason_reply`. A pure behavior-preserving
refactor would also fall through.

**Why it's intentional:** REVIEW-2 explicitly flagged the
fall-through as a bug — case-forum replies were running through
ticket-activity, ticket-transcript, mod-logs forum parser, and
polls handlers, double-logging every reply. The refactor's "no
logic changes" mandate was **overridden** for this one block in
favor of REVIEW-2's bug fix. The handler now returns `STOP`. See
inline comment in `src/handlers/messages/pipeline/case_forum.py`.

---

## When you find something else that "looks like a bug"

1. Search this doc for the file path or pattern.
2. If it's not here: check the file's docstring / header comment.
   Most intentional patterns explain themselves where they live.
3. If it's still unclear, raise the question — don't change the
   code. The code is right surprisingly often.
4. After resolving (whether the change ships or not), add an entry
   here so the next audit doesn't re-flag the same thing.

---

## House-Style Block Index

The bot's living conventions live as comment headers at the top of
specific files. When in doubt about a convention question (how do I
log this? what's the verb prefix? what should this label look like?),
read these blocks first before grepping the codebase:

  - `src/utils/log_fields.py:18-55`         — log field formatting (10 rules)
  - `src/core/logger.py` (top)              — tree logging conventions (10 rules)
  - `src/core/database/__init__.py` (top)   — DB method verb prefixes
    (`create_*` / `add_*` / `save_*` / `set_*` / `update_*` / `remove_*`
    / `delete_*` / `get_*` / `fetch_*` / `is_*` / `cleanup_*`)
  - `src/core/constants.py` (REASON_* block) — `REASON_SHORT_MAX = 200` /
    `REASON_MEDIUM_MAX = 500` / `REASON_LONG_MAX = 1000` for modal
    `max_length` per category

These are the blessed location for each convention. Adding a new
rule? Put it in the existing block, not a new file — codifying
across multiple locations is what creates drift.

---

## Audit-Trail Citation Format

Canonical inline citation:

```
(<AUDIT-TOKEN> / <YYYY-MM-DD>[ — <one-line why>])
```

Examples:

```
# Wrapped in to_thread to avoid blocking the event loop
# (REVIEW-2 / 2026-04-25)
```

```
# JS Number rounds at 2^53 — Discord snowflakes exceed that
# (DEEP-CONSISTENCY R6 / 2026-04-26 — JS Number precision)
```

```
# Promoted warning→tree to match recovery-success log
# (POLISH-PASS Round 4 / 2026-04-25 — zero readers on warning channel)
```

Rules:

1. **Audit token first, date second**, separated by ` / `. Never reverse.
2. **Drop the `.md` suffix** — token only.
3. **WHY leads the comment**; the citation is the trailing parenthetical.
   The citation tells future-you which audit doc has the full context;
   the WHY tells them whether the rationale still applies without
   needing to look it up.
4. A bare `# (DEEP-CONSISTENCY R6 / 2026-04-26)` is OK ONLY when the
   paragraph above is a complete WHY. Don't use it as the entire
   comment.
5. **New self-review fixes use `SELF-REVIEW / <date>`** so the
   breadcrumb pattern continues for non-audit-driven work. Same
   format, just a different token.

The 290 inline citations in the codebase are this project's
superpower: they let any reviewer reach the original rationale in
one grep. Worth preserving.

---

## Deleted Audit Doc Trail

These audit docs were retired once their punch lists were complete.
Inline comments still reference them as historical breadcrumbs —
that's intentional. To look up the original content, use git history.

| Doc | Last lived at SHA | Date deleted |
|---|---|---|
| `REVIEW.md`            | `e7a99a8` | 2026-04-25 |
| `REVIEW-2.md`          | `e7a99a8` | 2026-04-25 |
| `LOGGING-GAPS.md`      | `e7a99a8` | 2026-04-25 |
| `PING-SUPPRESSION.md`  | `1bd5b69` | 2026-04-25 |
| `POLISH-PASS.md`       | `e2658a3` | 2026-04-25 |
| `LOG-CONSISTENCY.md`   | (untracked — worktree only) | n/a |
| `DEEP-CONSISTENCY.md`  | (untracked — worktree only) | n/a |
| `DOC-CONSISTENCY.md`   | (untracked — worktree only, retired with this commit) | n/a |

To pull a deleted doc back temporarily:

```bash
git show <SHA>:<doc-name> > /tmp/<doc-name>
```

---

## Author Headers

All `src/**/*.py` files use the Arabic pen-name `حَـــــنَّـــــا` in
their `Author:` header. The `LICENSE` file uses the legal name
`John Hamwi`. Both are intentional — do not normalize the source
headers to match the LICENSE file.
