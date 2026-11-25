# Architecture

```
Browser  ->  Web app (Next.js)  ->  API (FastAPI)  ->  Database (SQLite or Postgres)
                  |                      ^   |
                  |                      |   +-> Adapters -> email, text, calendar, CRM, e-signature
                  +-- /api/session       |
                      /api/[...path]     Worker (same code, polls the job table)
```

## Pieces

- **Web (`apps/web`)**: Next 16 App Router. A small server layer holds the login cookie (`sx_session`, httpOnly) and forwards `/api/*` calls to the API with the session in a header. Writes need an `x-pipecairn: 1` header. It refuses to forward `auth/login` and `webhooks`. Pages use TanStack Query and the shared UI kit.
- **API (`apps/api/src/pipecairn`)**: routers for auth, data, ops, docs, webhooks and demo, on top of the shared base app (request ids, rate limit, health, uniform errors). A middleware requires a session for every `/api/*` call except login, logout and signed webhooks.
- **Worker**: loop that claims jobs from the database table, retries with backoff, and schedules due work (process new leads, send tick, poll inbox, reminders).
- **Adapters**: one interface per category, registered with a tier. The seed adapters are fully offline.
- **Base (`packages/`)**: frozen shared code (`sendora_core` and the UI kit). Never edited here.

## The lead flow

1. **Intake**: CSV or web form. Emails are normalised, duplicates merged, problems flagged (invalid email, role based address, invalid phone or time zone, existing customer).
2. **Enrich and score**: a 0 to 100 fit score from simple rules (see `apps/api/src/pipecairn/scoring.py`).
3. **Enrol** in the sequence.
4. **Send tick** (the heart): for each due step it runs the gates in order and then chooses a mailbox.
5. **Replies** arrive through IMAP, the Telnyx webhook or the email webhook. A reader sorts them; stop words stop everything for that person at once.
6. **Draft reply and approval**: the suggested reply waits in the Inbox until a person approves.
7. **Book** a call (Cal.com or Google Calendar), **proposal** and **contract** as PDFs, then **handoff** for signature.

## The send gates, in order

kill switch, lead status stop rules, suppression list (read again from the database every time), address validity, role based address, existing customer, text consent and phone format, quiet hours (08:00 to 18:00 local on weekdays; an unknown time zone stops), a mailbox under its daily cap, then the mode (draft records and advances; live sends). The footer (company, address, stop line) is added to the body at this step. A mailbox over `BOUNCE_PAUSE_RATE` (5 percent) bounces on `BOUNCE_MIN_SENDS` (20) or more sends is paused. The business rules that are settings are listed in `04`.

## Safety design

The app can pull toward draft or stop (State keys `kill_switch`, `force_draft`). It can never turn live on. Demo mode builds only seed adapters. All real world writes go through the base's `guard_write`.

## Data

16 tables prefixed `cl_` plus the base's `core_` tables (events, approvals, audit, jobs, costs). Alembic migrations in `apps/api/alembic`. Migration up, drift check, down and up again pass on SQLite and Postgres 17.7.

## API

52 paths, 57 operations, in `docs/openapi.json`. Live docs at `/docs` on the API, in demo mode only (they are off when `DEMO_MODE=false`).
