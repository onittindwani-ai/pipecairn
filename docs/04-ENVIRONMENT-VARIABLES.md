# Environment variables

An environment variable is a named setting you give the program before it starts, instead of typing it in a file the program ships with. Names are listed here. Never put real values in a file you commit. Copy `.env.example` to `.env` and fill it in. `.env` is ignored by git.

Check your setup any time. `make check-env` (same as `python3 tools/check_env.py`) compares your `.env` with `.env.example` and lists what is missing, still a placeholder, or half filled in. `python tools/doctor.py` goes one step further and tests that each service you filled in actually answers. Both print names, never values.

## How to set them

1. Copy the example: `cp .env.example .env`.
2. Edit `.env` in a text editor and fill the values you need.
3. The API and the worker both read the file named by `ENV_FILE` (default `.env`), and so does `alembic upgrade head`. They always run on the same settings.
4. On Vercel, Railway or a server, set the same names in that service's settings page instead of a file.

## Core

| Name | What it is | Default |
|---|---|---|
| `DATABASE_URL` | Where data lives. SQLite for trying out, Postgres for real use. Alembic stops with a message when it is set nowhere. | `sqlite:///./pipecairn.sqlite3` |
| `SESSION_SECRET` | A long random string that signs logins. Make one: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. With `DEMO_MODE=false`, or whenever `OWNER_PASSWORD_HASH` is set (even with `DEMO_MODE=true`), the app refuses to start when it is shorter than 32 characters or still looks like an example. Change it and everyone is signed out, and the unsubscribe links already emailed stop working unless the old value goes into `SESSION_SECRET_PREVIOUS`. | a dev only value |
| `SESSION_SECRET_PREVIOUS` | The `SESSION_SECRET` you replaced. The one click unsubscribe links in emails already sent were signed with it, so it keeps them valid. It signs nothing new and does not sign anyone in. Empty it once old emails no longer matter. | empty |
| `MODE` | `draft` (nothing leaves) or `live` (really sends). Live also needs the sender name, company name and address below. | `draft` |
| `DEMO_MODE` | `true` builds only fake adapters, moves the clock, and allows the public demo password until an owner password is set. Set `false` for real use. | `true` in code, `false` in `.env.example` |
| `ALLOW_DEMO_SERVER` | The app refuses `DEMO_MODE=true` on a Postgres database, because a demo has a reset button that erases the data. `true` allows it for a throw away trial. | `false` |
| `KILL_SWITCH` | `true` stops everything at start. The owner can also press the switch in the app. | `false` |
| `MAX_BODY_BYTES` | The largest request the API reads. | `26214400` (25 MB) |
| `APP_NAME` | Name shown in logs. | `pipecairn` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. | `INFO` |
| `HANDOFF_DIR` | Folder where signature hand off folders are written. Back it up (see `11`). | `./handoff` |
| `SEED_DIR` | Folder with the demo data. Set automatically when run from the repo. | empty |
| `ENV_FILE` | Which file the API, the worker and alembic read. Not part of the file itself: set it in the shell. | `.env` |

## Sign in (steps)

1. Run `python tools/hash_password.py`. Type a password twice (it is hidden).
2. It prints a line like `OWNER_PASSWORD_HASH='...'`. Put that line in `.env`. The quotes matter, because the hash contains `$` characters.
3. Set `OWNER_EMAIL` to your email.
4. Optionally make a second person who can approve: repeat with `APPROVER_EMAIL` and `APPROVER_PASSWORD_HASH`. An approver approves or rejects replies, books calls from the Inbox, moves deals, writes proposals and can stop contacting someone. An approver cannot import leads, enrol them, edit or create a sequence, add a mailbox, change the switches or resume a mailbox: those change what goes out to people and are owner only.
5. Set `DEMO_MODE=false`. The demo password and the made up approver and viewer accounts stop working the moment an owner hash is set, even if `DEMO_MODE` is still `true`.

| Name | What it is | Default |
|---|---|---|
| `OWNER_EMAIL`, `OWNER_PASSWORD_HASH` | The owner login. The hash, never the password. | `owner@example.test`, empty |
| `APPROVER_EMAIL`, `APPROVER_PASSWORD_HASH` | Optional second login for approving replies and proposals. It cannot import leads, edit sequences or change settings (owner only). | empty |
| `LOGIN_BURST` | Sign in tries in a row from one address and email before a short wait (one more every 12 seconds). There is also a wider limit per address alone. Leave it at 5 outside tests. | `5` |
| `VIEWER_EMAIL`, `VIEWER_PASSWORD_HASH` | Optional read only login (an accountant, a client who only watches). It can see every page and change nothing. | empty |

## Who the messages come from

Every email gets a footer with your company name, your postal address and "Reply STOP to opt out", and carries `List-Unsubscribe` headers. The footer is added by the program, not by the template. With `MODE=live` and `DEMO_MODE=false` the app refuses to start while the first three are still the placeholders.

| Name | What it is | Default |
|---|---|---|
| `SENDER_NAME` | Signs replies and fills `{{sender_name}}` in sequences. | `Alex` (placeholder) |
| `COMPANY_NAME` | The "From" company on proposals and contracts, and the first footer line. | `Your Company` (placeholder) |
| `COMPANY_ADDRESS` | Your physical postal address, one line, in the footer of every email. | empty (placeholder) |
| `REPLY_TO` | Optional Reply-To address on outgoing email. | empty |
| `PUBLIC_BASE_URL` | Where this API is reachable from the internet, starting with `https://`. When set, email also carries an https one click unsubscribe link. | empty |

## Adapters

| Name | Choices |
|---|---|
| `EMAIL_ADAPTER` | `seed`, `smtp_imap` |
| `SMS_ADAPTER` | `seed`, `telnyx` |
| `CALENDAR_ADAPTER` | `seed`, `calcom`, `google_calendar` |
| `CRM_ADAPTER` | `seed`, `twenty`, `hubspot`, `notion` |
| `ESIGN_ADAPTER` | `seed` (writes no folder), `breezedoc_handoff` (writes the signing folder) |

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

Email connections always check the server's certificate and name. `SMTP_USE_TLS=false` and `IMAP_USE_SSL=false` are accepted only for a mail server on this same computer (127.0.0.1). One mail account (`SMTP_USER`, `SMTP_PASSWORD`) signs in for every mailbox you add, so add only that address or addresses it may send as.

Base URLs are checked so a setting cannot point the app at your private network. `ALLOW_PRIVATE_BASE_URLS=true` is the owner's opt in for a self hosted Twenty or Cal.com on a private address (default `false`).

## Webhooks and sending rules

| Name | What it is | Default |
|---|---|---|
| `WEBHOOK_SHARED_SECRET` | Signs the email and web form webhooks. Required for live mode. A sender may add an `x-timestamp` header and sign `timestamp.body`; a request older than five minutes is then refused. | empty |
| `QUIET_START_HOUR`, `QUIET_END_HOUR` | No sends from 18:00 until 08:00 the lead's local time. | 18, 8 |
| `SEND_WEEKENDS` | Allow weekend sends. | `false` |
| `ALLOW_PRIVATE_BASE_URLS` | See above. | `false` |
| `KEEP_UNMATCHED_MAIL` | Also keep a 600 character snippet of mail from addresses that are not leads (an alias, a forward, a stranger), shown in the Inbox with a "never write to this address again" button. Off by default: mail that is not from a lead is then left completely alone (not read, not copied, not marked as read). Turn it on only for a mailbox that is used for nothing else. | `false` |

## Business rules

These used to be fixed in the code. The defaults are the old values. Role based addresses (info@, sales@), the free mail list and the score weights are still code (see `14`).

| Name | What it is | Default |
|---|---|---|
| `TARGET_INDUSTRIES` | Comma separated industries that earn the full industry points in the score. | `home services,dental,legal,real estate,accounting` |
| `MIN_ENROLL_SCORE` | A lead scoring below this is not enrolled in the sequence. | `40` |
| `BOUNCE_PAUSE_RATE`, `BOUNCE_MIN_SENDS` | A mailbox pauses when its share of bounces passes the rate, after at least this many sends. | `0.05`, `20` |
| `DEFAULT_TIMEZONE` | Used for a CSV row with no valid time zone, for example `America/New_York`. Empty means such rows are flagged and never sent to. | empty |
| `CURRENCY_SYMBOL` | Shown before prices in proposals and contracts. | `$` |
| `PROPOSAL_VALID_DAYS`, `CONTRACT_NOTICE_DAYS` | Days a proposal is valid; days of written notice in the contract text. | `14`, `14` |
| `DEAL_VALUE_SMALL_CENTS`, `DEAL_VALUE_MEDIUM_CENTS`, `DEAL_VALUE_LARGE_CENTS` | Placeholder deal value (in cents) for companies of 10 or fewer, 11 to 200, and over 200 people. Replace with your price list. | `150000`, `600000`, `1200000` |
| `PAGE_SIZE` | `letter` or `a4` for proposal and contract PDFs. | `letter` |

## Reply understanding

| Name | What it is | Default |
|---|---|---|
| `LLM_BACKEND` | `offline` (built in stand-in, no account), `fixture` (recorded answers from `LLM_FIXTURES_DIR`) or `anthropic` (real model, needs a key, not yet verified against the real service). Wins over `LLM_MODE`. Use this one. | `offline` |
| `LLM_MODE` | The older switch: `fixture` or `live` (`live` means `anthropic` when `LLM_BACKEND` is empty). | `fixture` |
| `ANTHROPIC_API_KEY` | Only for `anthropic`. Shown once at creation. | empty |
| `LLM_HARD_MODEL`, `LLM_BULK_MODEL` | Model names used for hard and bulk reads. | claude-sonnet-5-5, claude-haiku-5-5 |
| `LLM_MODEL` | One model name for both kinds. | empty |
| `ANTHROPIC_BASE_URL`, `ANTHROPIC_VERSION` | The API address (https only, except 127.0.0.1 for tests) and the version header. | `https://api.anthropic.com`, `2026-10-21` |
| `LLM_TIMEOUT`, `LLM_MAX_TOKENS`, `LLM_MAX_RETRIES` | Seconds per request, reply size limit, retries after a failure. | `120`, `4096`, `2` |
| `LLM_CALL_BUDGET`, `LLM_BUDGET_USD` | The only spend limits for the live model: most calls per process, most dollars in total. Empty means no limit, so set both before you switch to `anthropic`. | empty |
| `LLM_THINKING` | `default` or `off`. | `default` |
| `LLM_FIXTURES_DIR`, `LLM_RECORD` | Where recorded answers are read, and whether live answers are saved there. | empty, `false` |
| `LLM_REDACT`, `LLM_LOG_PROMPTS` | Logs and fixtures never hold a full prompt or a key; a redacted short prompt can be logged. | `true`, `false` |

## Web app and Docker only

| Name | What it is |
|---|---|
| `API_BASE_URL` | Where the web app finds the API. Default `http://127.0.0.1:8000`. |
| `INSECURE_COOKIES` | Set `1` only on plain http for local tests. Never in production. |
| `NEXT_PUBLIC_DEMO_HINT` | Set `1` while you run `pnpm build` to show the demo sign in hint. It is built into the page, so it has no effect when set only at start. Leave empty in production. |
| `POSTGRES_PASSWORD` | Docker compose only. Letters and digits only, or percent encoded, because it sits inside the database address. Make one: `openssl rand -hex 24`. |
| `FORWARDED_ALLOW_IPS` | Which addresses may tell the API who the visitor is. The image uses `127.0.0.1`; compose widens it to the private network that holds the web container. Set it to your proxy only. |

## Going live changes these things

`MODE=live`, `DEMO_MODE=false`, a real `OWNER_PASSWORD_HASH`, a `SESSION_SECRET` you made, and a real `SENDER_NAME`, `COMPANY_NAME` and `COMPANY_ADDRESS`. `python tools/doctor.py` lists what is still missing.
