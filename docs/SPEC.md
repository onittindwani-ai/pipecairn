# Pipecairn specification (build spec, version 1)

Pipecairn takes a lead from first contact to a signed deal. This file is the spec the build follows. `ARCHITECTURE.md` is the final description of what was built.

## Entities (tables are prefixed `cl_`)

| Entity | Purpose | Key fields |
| --- | --- | --- |
| Company | The business a person works for | name, domain (unique), industry, size, country, is_customer |
| Contact | A person | company, first and last name, email (unique, lower case), phone, title, timezone |
| Lead | A contact being worked | contact, source, status, score, score_breakdown, score_explanation, first_touch_at |
| Sequence, Step | A series of messages | name, steps with channel (email or sms), delay in hours, subject, body |
| Enrollment | A lead inside a sequence | current_step, status, next_send_at, stop_reason, paused_until |
| Message | One email or text, in or out | channel, direction, mailbox, status (drafted, queued, sent, failed, blocked, received), blocked_reason |
| Reply | The reading of an inbound message | intent, confidence, summary, suggested_action, draft_reply, handled |
| Meeting | A booked call | starts_at, ends_at, external_id, status |
| Proposal | Offer text and price | scope, price, call_notes, body, status |
| Contract | Contract text and hand off package | proposal, body, status, package_path |
| Deal | The money side of a lead | stage, value, closed_at, lost_reason |
| Activity | A human readable timeline entry | lead, kind, summary |
| Suppression | Never contact again | kind (email, domain, phone), value, reason |
| Mailbox | A sending address | address, provider, daily_cap, sent_today, bounce_count, sent_base and bounce_base (the counts at the last resume, so the pause rule counts from there), health, spf, dkim, dmarc |
| Event | Every meaningful change | stored in the base `core_events` table |

Pipeline stages on a deal: new, contacted, replied, meeting, proposal, won, lost.

## The flow

intake (CSV, form, webhook, CRM sync) then dedupe and enrich, score with a rubric in code plus a model written explanation, enroll in a sequence, send with stop rules, quiet hours by the contact's timezone, a daily cap per mailbox and a suppression check before every send, capture replies, classify intent (interested, question, not now, wrong person, unsubscribe, out of office, bounce), act (draft a reply for approval, book a call, stop and suppress), meeting, proposal and contract, hand off for signature, won or lost, metrics.

## Jobs (database queue, one worker)

`send_tick`, `reply_poll`, `enrich`, `score`, `crm_sync`, `report`.

## Adapters

| Category | Tier A (built and tested against a mock) | Tier B (from public docs, UNVERIFIED live) | Tier C (recipe prompt) |
| --- | --- | --- | --- |
| Email | seed, smtp_imap | none | sendkit |
| SMS | seed, telnyx | none | none |
| Calendar | seed, calcom | google_calendar | none |
| CRM | seed (CSV and seed), twenty | hubspot, notion | none |
| E-signature | seed, breezedoc_handoff | none | documenso |

Every category has an offline `seed` adapter. A tier A adapter has a mock vendor server in `mock/` written from the vendor's public docs and tests that run against it. Nothing is `live_verified`.

## Evals

A reply classifier test set with an answer key. Property tests that nothing is sent after an opt out, outside quiet hours, above a mailbox cap, or to a suppressed address. Score consistency (same input, same score).

## API (FastAPI, base app)

Auth: login, logout, me. Leads: list, create, import CSV, detail, score, enrol. Sequences: list, detail, update. Inbox: replies list, detail, classify, approve a draft. Pipeline: deals list, move. Proposals: create, preview, PDF, contract hand off package. Deliverability: mailboxes. Integrations: list, test. Approvals: list, decide. Audit: list, verify chain. Metrics: overview. Settings: mode and kill switch (owner only). Webhooks: Telnyx inbound, Cal.com booking, signed generic inbound email. Demo (demo mode only): reset, tick, advance clock, simulate reply.

## Pages (Next.js)

Overview (speed to lead ring, funnel), Pipeline board, Inbox split view, Sequence builder, Leads table, Proposal studio, Deliverability, Approvals, Integrations wizard, Audit log, Sign in.

## Environment variables

APP_NAME, DATABASE_URL, SESSION_SECRET, MODE, KILL_SWITCH, DEMO_MODE, LLM_MODE, ANTHROPIC_API_KEY, OWNER_EMAIL, OWNER_PASSWORD_HASH, API_BASE_URL (web), EMAIL_ADAPTER, SMS_ADAPTER, CALENDAR_ADAPTER, CRM_ADAPTER, ESIGN_ADAPTER, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, IMAP_HOST, IMAP_PORT, TELNYX_API_KEY, TELNYX_PUBLIC_KEY, TELNYX_FROM_NUMBER, CALCOM_API_KEY, CALCOM_EVENT_TYPE_ID, CALCOM_WEBHOOK_SECRET, TWENTY_BASE_URL, TWENTY_API_KEY, HUBSPOT_TOKEN, NOTION_TOKEN, NOTION_DATABASE_ID, GOOGLE_CALENDAR_TOKEN, WEBHOOK_SHARED_SECRET.

## Hard limits

Nothing sends in draft mode. In demo mode only seed adapters can be built. US texting needs the client's own carrier registration. Cold email domains are separate from the main domain.
