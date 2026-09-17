# Safe Home CRM → "Safe Home OS" — Gap Analysis

Compares the current system (see `SYSTEM_AUDIT.md`) against the full target
spec the owner provided (Client 360, Property 360, deals/finance, lead
distribution/SLA/next-best-action engines, automation engine, AI assistant,
full RBAC, job queue, observability, disaster recovery, load testing at
300+ agents, etc.). Categorized P0–P3. This is a planning document, not an
implementation — each item becomes its own scoped round of work, delivered
and applied the same way every round so far has been (zip → manual GitHub
upload → Railway auto-deploy), because this system cannot be redeployed
directly from this environment.

## P0 — Critical (security / data-loss / already-broken)

| # | Item | Status |
|---|------|--------|
| 1 | Team-scope authorization bypass on 3 GET endpoints (`reports`, `task-history`, `digest`) | **Fixed this pass** |
| 2 | Missing ownership check on 3 POST endpoints (`swaps/decide`, `questions/answer`, `reports/rate`) | **Fixed this pass** |
| 3 | Bot callback trusts unverified `target_id` for number-swap confirmation | **Fixed this pass** |
| 4 | No `auth_date` freshness check on Telegram Mini App initData (replay never expires) | Open |
| 5 | No unique constraint on `attendance(agent_id, date)` — possible duplicate clock-in rows under concurrent requests | Open |
| 6 | Photo uploads validated only by decoded byte size + a substring guess at file type, not real content sniffing | Open |
| 7 | Multi-step writes (e.g. agent delete, request approval flows) are not wrapped in a single DB transaction — a crash mid-sequence can leave inconsistent state | Open |

## P1 — Core business functionality (the parts of the spec that turn this from "task/attendance bot" into "CRM")

| # | Item | Notes |
|---|------|-------|
| 1 | **Client entity + lifecycle** (NEW→CONTACTED→...→DEAL/LOST) | Today "client" is a derived view over tasks. This is the single biggest structural gap — almost everything else in the spec (next-action engine, SLA, lost-reason analytics, client 360) depends on a real client row existing. |
| 2 | **Property/listing entity + price history** | `exclusives` covers only an agent's own intake; there's no company-wide catalog, no price-change history, no duplicate detection. |
| 3 | **Deal/commission/payment entity + finance reporting** | Does not exist at all today. This is also the one area that is a genuine **money decision** (commission %, splits, who sees financial data) — needs the owner's business rules, not an invented default; recommend building the schema + entry UI first with commission fields left blank/configurable, and confirming the actual split/percentage rules before turning on any automatic calculation. |
| 4 | **Real RBAC** wired to the existing (currently inert) `roles`/`permissions`/`role_permissions` tables | Schema groundwork already exists — this is "finish what Phase 1 started," not a new design. |
| 5 | **Lead distribution engine** beyond "best performer / random" | Current `pick_agent_for_priority` only considers on-time completion rate; no workload/specialization/language matching. |
| 6 | **SLA engine** (response-time targets, tracked + escalated) | None today. |
| 7 | **Audit coverage** for all mutating operations, not just 10 of ~50+ | Straightforward to extend once the pattern (`_audit()`) already exists. |

## P2 — Important operational improvements

Next-best-action recommendations, agent workload scoring, KPI split into
activity/quality/conversion/revenue, KPI anomaly alerts, follow-up
automation rules (configurable, not hardcoded), management daily briefing
beyond the current digest, CEO dashboard (pipeline view), saved
searches/new-listing alerts, structured lost-reason capture, pipeline
stagnation detection, notification engine with delivery status tracking
(queued/sent/failed/retrying) instead of the current fire-and-forget
`send_message` calls, job queue for anything heavier than the current
in-process JobQueue callbacks, health-check endpoint, structured logging
with request/event IDs, backup/restore procedure and a written
`DISASTER_RECOVERY.md`, admin-configurable settings UI for the business
constants that are currently `config.py` env-vars only (quotas, limits,
reminder hours, SLA windows once they exist).

## P3 — Optimization / convenience / future integrations

AI assistant (client summaries, "what needs my attention," natural-language
queries) — genuinely useful, but it is a consumer of the P1 data model
(client lifecycle, next-action, deals) and produces low-value output until
that data model exists; building it first would mean it either shows fake
numbers or nothing, both explicitly against the owner's own "no placeholder
features" rule. Global backend search (today's search is a client-side
filter over an already-fetched list, fine at current data volume). Recruitment
CRM pipeline (application→hired) as a first-class flow rather than the
existing add/remove-agent request workflow. WhatsApp/email channel
integration (no credentials/API access exists today — will be documented as
missing dependencies if/when pursued, never faked). Website
(safehome.ge) listing sync — no API access confirmed to exist; will not be
invented. Multi-instance/horizontal scaling changes (the in-process lock
becomes a real bottleneck only well past current scale).

## Scalability

Not load-tested. At 10–50 agents (today's real range) nothing in the audit
suggests a problem. The two structural ceilings noted in `SYSTEM_AUDIT.md`
§6 (a single process-wide lock, and Python-side filtering instead of
SQL-side filtering on list endpoints) would need addressing before a
confident claim of "300+ agents, production-grade" could be made — that
claim should not be made without an actual load test against realistic data
volume, which has not been run.

## Recommended sequencing

1. P0 items 4–7 (small, scoped, no business decisions needed) — next round.
2. P1 items 1 (client entity/lifecycle) and 4 (real RBAC) — these are the
   foundation everything else in P1/P2 builds on; doing them first avoids
   rework.
3. P1 items 2–3 (property catalog, deals/finance) — item 3 needs the
   owner's commission/split rules confirmed before any auto-calculation is
   turned on.
4. P1 items 5–6 (lead distribution, SLA) once client/property/RBAC exist to
   attach them to.
5. P2 batch, then P3.

Each numbered step above is sized to be one deliverable round (consistent
with how every round of this project has shipped so far), not one giant
release — this keeps every change testable, reviewable, and reversible via
the zip-and-redeploy workflow already in place, and avoids the risk of a
single huge, hard-to-review change touching a live production system.
