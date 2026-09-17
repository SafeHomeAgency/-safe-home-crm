# Safe Home CRM — System Audit

Date: 2026-09-17
Scope: full repository (`app.js`, `webserver.py`, `bot.py`, `sheets_postgres.py`,
`sheets_gspread.py`, `schema.sql`, `config.py`, `db.py`). Read-only inspection,
no behavior changed except the concrete security fixes listed in §6 (applied
immediately because they are unambiguous bugs, not design decisions).

## 1. Architecture today

```
Telegram (bot.py, python-telegram-bot)
   │
   ├─ Conversation handlers (10) — /newtask, /addagent, /addexclusive, ...
   ├─ Command handlers (~31 distinct commands)
   ├─ Callback query handlers (20)
   └─ JobQueue: 7 recurring/daily background jobs
        (task-notify poll 60s, late-arrival check 15min, daily report 09:00,
         compliance check 22:05, team digests 22:10, shift-edge reminders 5min,
         manager-lateness notices 5min)
   │
Flask Mini App (webserver.py, served from the same process, thread)
   │  auth: Telegram initData HMAC-SHA256 verification (correct, timing-safe)
   │  ~35 REST endpoints, role model: admin (env ADMIN_CHAT_IDS) / team_lead
   │  (agents.role='team_lead') / agent / anonymous
   │
sheets.py (dispatcher: DATA_BACKEND env var — "sheets" default, "postgres")
   │
   ├─ sheets_gspread.py  → Google Sheets (13 sheets, gspread + retry wrapper)
   └─ sheets_postgres.py → PostgreSQL (17 tables incl. audit_log + inert RBAC
                            tables, via db.py connection pool)

Frontend: app.js (2258 lines, single file, no build step, no framework) +
style.css + index.html — Telegram Mini App, one global `state` object,
no localStorage, everything re-fetched per session.
```

Both storage backends are required to expose **byte-identical public function
signatures** (checked by an AST script in this session, and by
`sheets._ASSERT_API_PARITY()` in code — note: that assertion is a **test-time
helper only**, never called at runtime, so a drift would not be caught in
production).

## 2. Feature inventory (confirmed present, working)

Attendance/clock-in-out, daily quotas (office + online), tasks with
assignment/reassignment/acknowledgment, KPI (on-time %), meetings log,
client reports (+ optional photos, saved locally under `/uploads/reports/`),
day-off requests with monthly cap, shift-swap requests with monthly cap,
warnings with an auto-deactivation threshold and a manager→director dismissal
workflow, exclusive-listing intake + inter-agent sharing, agent Q&A, hire/fire
request workflow, per-team drilldowns for admin, a Clients aggregate view,
regulations/instructions tab. Full per-tab breakdown and full function list
are in the discovery notes this audit is based on (available on request —
omitted here to keep this document a reasonable size).

## 3. What does NOT exist yet (confirmed by direct code inspection, not inferred)

- **No property/listing table.** `exclusives` is an agent's own-listing intake
  form, not a company-wide property catalog; `tasks.listing_id` is a free-text
  external reference with nothing to join against internally.
- **No deal/commission/payment/finance entity of any kind.** `meetings.price`
  and `exclusives.price`/`percent` are free-text strings with no numeric
  validation, no currency, no ledger, no lifecycle.
- **No client entity.** "Clients" today is a derived view over `tasks` grouped
  by phone number — there is no client status/lifecycle field, no next-action
  field, no preferences record.
- **No real RBAC.** `roles`/`permissions`/`role_permissions` tables exist in
  `schema.sql` (seeded, with a foreign key — the *only* FK in the schema) but
  are queried nowhere; actual authorization is still `chat_id in
  ADMIN_CHAT_IDS` + a single `role == 'team_lead'` string check.
- **No job queue / automation engine.** Background work is 7 hardcoded
  `JobQueue` callbacks in `bot.py`, not a general event→automation framework.
- **No AI integration anywhere in the codebase.**
- **No rate limiting**, anywhere.
- **No persistence for in-flight bot conversations** (no PTB `persistence=`
  configured) and **two in-memory-only reminder-dedup sets** — both are lost
  on every process restart (acceptable for soft reminders, explicitly by
  design; unacceptable if extended to anything durable).

## 4. Data-integrity risks (see full detail in the discovery notes)

- No foreign keys anywhere except `role_permissions`.
- `delete_agent()` is a genuine hard delete (by explicit design, to satisfy
  this round's request) — historical rows survive via denormalized name
  snapshots, but any future code that re-joins by `agent_id` after deletion
  will silently miss that agent.
- No DB transactions spanning multi-step writes; only a single in-process
  `threading.RLock()` serializes access — meaningless across multiple
  app instances, and does not protect against a crash mid-sequence.
- `attendance(agent_id, date)` has an index but **not a unique constraint** —
  a race between two `clock_in()` calls could create duplicate rows.
- No duplicate-client/duplicate-task detection.
- Three different "remove a record" conventions coexist (hard delete / soft
  `active=no` / soft `status` field) with no single rule for which to use
  when.
- All prices/areas/percentages are free-text `TEXT`, never validated as
  numbers.

## 5. Security posture (see full detail in the discovery notes)

**Good:** Telegram Mini App auth is real HMAC-SHA256 verification with a
timing-safe comparison (not a rubber-stamp check); no hardcoded secrets found
anywhere; the photo-upload path uses server-generated UUID filenames (no
path-traversal risk) with size/count caps; error responses never leak stack
traces to the client.

**Fixed in this pass (concrete, narrow bugs, not design decisions):**
1. `GET /api/reports`, `/api/task-history`, `/api/digest` accepted a
   client-supplied `?team=` query parameter even for a non-admin team_lead,
   letting a team lead read another team's reports/history/digest simply by
   changing a URL parameter. Fixed: the `team` filter is now only honored
   from the query string for a true admin; a team_lead's own team is always
   forced server-side.
2. `POST /api/swaps/decide`, `POST /api/questions/answer`, `POST
   /api/reports/rate` checked only "is this an admin or a team_lead" but
   never checked that the specific swap/question/report belonged to the
   team_lead's own team — a team_lead who knew or guessed an ID from another
   team could act on it. Fixed to match the pattern already used correctly
   elsewhere in the same file (`/api/dayoff/decide`,
   `/api/warnings/request-dismiss`): fetch the target row first, compare its
   owning agent's team to the caller's team, 403 on mismatch.
3. `bot.py`'s `swapnumber_response` callback trusted a `target_id` embedded
   directly in Telegram callback data and acted on it (swapping two agents'
   internal phone extensions) without checking that the person who actually
   clicked the button was that target agent. Fixed to re-verify
   `update.effective_chat.id` against the target's `telegram_chat_id` before
   proceeding, matching the safer pattern already used by
   `swapshift_accept`/`taskseen_callback` in the same file.

All three fixes were verified with `python3 -m py_compile` and the existing
30-test suite (all pass) after the change.

**Not fixed in this pass (deliberately — these are scope/prioritization
decisions, not bugs, and are logged in `GAP_ANALYSIS.md` instead):** no
rate limiting; no `auth_date` freshness check on Telegram initData (a
captured initData string never expires); the RBAC tables exist but are
unused (today's simpler role check is not wrong, just not yet
config-driven); no request/action-level audit coverage for most write
operations (only 10 of ~50+ mutating functions call `_audit()`).

## 6. Scale readiness

Nothing in the current design is broken at 10–50 agents (today's real
scale). Two things will start to matter well before 300 agents:
- The single in-process `RLock` serializes *all* reads and writes; this is a
  throughput ceiling, not a correctness bug, at current scale.
- Every dashboard/report endpoint calls `get_agents()`/`get_tasks()` etc. and
  filters in Python rather than filtering in SQL — fine at hundreds of rows,
  will need query-level filtering once tables reach tens of thousands of
  rows.

No load testing has been performed — see `GAP_ANALYSIS.md` §Scalability.
