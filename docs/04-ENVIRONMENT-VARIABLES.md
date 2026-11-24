# Environment variables

An environment variable is a named setting you give the program before it starts, instead of typing it in a file the program ships with. Names are listed here. Never put real values in a file you commit. Copy `.env.example` to `.env` and fill it in. `.env` is ignored by git.

Check your setup any time. `make check-env` (same as `python3 tools/check_env.py`) compares your `.env` with `.env.example` and lists what is missing, still a placeholder, or half filled in. `python tools/doctor.py` goes one step further and tests that each service you filled in actually answers. Both print names, never values.

## How to set them

1. Copy the example: `cp .env.example .env`.
2. Edit `.env` in a text editor and fill the values you need.
3. Run the API with `ENV_FILE=.env` (that is the default).
4. On Vercel, Railway or a server, set the same names in that service's settings page instead of a file.

## Core

| Name | What it is | Default |
|---|---|---|
| `DATABASE_URL` | Where data lives. SQLite for trying out, Postgres for real use. | `sqlite:///./pipecairn.sqlite3` |
| `SESSION_SECRET` | A long random string that signs logins. Make one: `python -c "import secrets;print(secrets.token_urlsafe(48))"`. Change it and everyone is signed out. | a dev only value |
| `MODE` | `draft` (nothing leaves) or `live` (really sends). | `draft` |
| `DEMO_MODE` | `true` builds only fake adapters and allows the demo password. Set `false` for real use. | `true` |
| `KILL_SWITCH` | `true` stops everything at start. | `false` |
| `APP_NAME` | Name shown in logs. | `pipecairn` |
| `HANDOFF_DIR` | Folder where proposal PDFs and signature handoffs are written. | `./handoff` |
| `SEED_DIR` | Folder with the demo data. Set automatically when run from the repo. | empty |

## Sign in (steps)

1. Run `python tools/hash_password.py`. Type a password twice (it is hidden).
2. It prints a line like `OWNER_PASSWORD_HASH='...'`. Put that line in `.env`. The quotes matter, because the hash contains `$` characters.
3. Set `OWNER_EMAIL` to your email.
4. Optionally make a second person who can only approve: repeat with `APPROVER_EMAIL` and `APPROVER_PASSWORD_HASH`.
5. Set `DEMO_MODE=false`. The demo password stops working.

| Name | What it is |
|---|---|
| `OWNER_EMAIL`, `OWNER_PASSWORD_HASH` | The owner login. The hash, never the password. |
| `APPROVER_EMAIL`, `APPROVER_PASSWORD_HASH` | Optional second login for approving replies and proposals. |
| `LOGIN_BURST` | Sign in tries in a row from one address and email before a short wait (one more every 12 seconds). Leave it at 5 outside tests. | `5` |
| `VIEWER_EMAIL`, `VIEWER_PASSWORD_HASH` | Optional read only login (an accountant, a client who only watches). It can see every page and change nothing. |

## Adapters

| Name | Choices |
|---|---|
| `EMAIL_ADAPTER` | `seed`, `smtp_imap` |
| `SMS_ADAPTER` | `seed`, `telnyx` |
| `CALENDAR_ADAPTER` | `seed`, `calcom`, `google_calendar` |
| `CRM_ADAPTER` | `seed`, `twenty`, `hubspot`, `notion` |
| `ESIGN_ADAPTER` | `seed`, `breezedoc_handoff` |

## Per adapter

| Adapter | Names |
|---|---|
| smtp_imap | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `IMAP_HOST`, `IMAP_PORT`, `IMAP_USE_SSL` |
| telnyx | `TELNYX_API_KEY`, `TELNYX_PUBLIC_KEY`, `TELNYX_FROM_NUMBER`, `TELNYX_BASE_URL` |
| calcom | `CALCOM_API_KEY`, `CALCOM_EVENT_TYPE_ID`, `CALCOM_WEBHOOK_SECRET`, `CALCOM_BASE_URL`, `CALCOM_SLOTS_VERSION`, `CALCOM_BOOKINGS_VERSION` |
| twenty | `TWENTY_BASE_URL`, `TWENTY_API_KEY` |
| hubspot | `HUBSPOT_TOKEN` |
| notion | `NOTION_TOKEN`, `NOTION_DATABASE_ID` |
| google_calendar | `GOOGLE_CALENDAR_TOKEN` |

Base URLs are checked so a setting cannot point the app at your private network.

## Webhooks and sending rules

| Name | What it is | Default |
|---|---|---|
| `WEBHOOK_SHARED_SECRET` | Signs the email and web form webhooks. Required for live mode. | empty |
| `QUIET_START_HOUR`, `QUIET_END_HOUR` | No sends from 18:00 until 08:00 the lead's local time. | 18, 8 |
| `SEND_WEEKENDS` | Allow weekend sends. | `false` |

## Reply understanding

| Name | What it is | Default |
|---|---|---|
| `LLM_BACKEND` | `offline` (built in stand-in, no account), `fixture` (recorded answers from `LLM_FIXTURES_DIR`) or `anthropic` (real model, needs a key, not yet verified against the real service). Wins over `LLM_MODE`. | `offline` |
| `LLM_MODE` | `fixture` (offline stand-in) or `live`. | `fixture` |
| `ANTHROPIC_API_KEY` | Only for `live`. Shown once at creation. | empty |
| `LLM_HARD_MODEL`, `LLM_BULK_MODEL` | Model names used for hard and bulk reads. | claude-sonnet-5-5, claude-haiku-5-5 |

## Web app only

| Name | What it is |
|---|---|
| `API_BASE_URL` | Where the web app finds the API. Default `http://127.0.0.1:8000`. |
| `INSECURE_COOKIES` | Set `1` only on plain http for local tests. Never in production. |
| `NEXT_PUBLIC_DEMO_HINT` | Set `1` to show the demo sign in hint. Leave empty in production. |

## Going live changes four things

`MODE=live`, `DEMO_MODE=false`, a real `OWNER_PASSWORD_HASH`, and a `SESSION_SECRET` you made. `python tools/doctor.py` lists what is still missing.
