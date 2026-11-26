# Connect your tools

Pipecairn talks to outside services through adapters. Each category (email, texting, calendar, CRM, e-signature) has a safe offline adapter called `seed`, and real ones you can switch on. **None of the real ones has been tested against a real account.** Tier A adapters are tested against local copies written from the public docs. Tier B are written from the docs and not run. Tier C are recipe prompts only.

Switch one at a time. After each, run `python tools/doctor.py` (add `--live` to test the real connection; it sends nothing).

## Email (Tier A: smtp_imap)

1. Pick a sending mailbox on a separate domain (see `02`).
2. In Gmail: turn on 2 step verification, then make an app password at myaccount.google.com/apppasswords. Use it as `SMTP_PASSWORD`. Gmail IMAP is `imap.gmail.com` port 993. Gmail SMTP is `smtp.gmail.com` port 465 with SSL. Other hosts have their own settings.
3. Set `EMAIL_ADAPTER=smtp_imap`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `IMAP_HOST`, `IMAP_PORT`.
4. Port 465 uses SSL on connect. Any other port uses STARTTLS. The server's certificate is always checked. `SMTP_USE_TLS=false` and `IMAP_USE_SSL=false` work only for a mail server on this same computer.
5. Add the sending mailbox in the app (Deliverability page): a real install does not come with one. One account signs in for every mailbox.
6. Inbound mail relayed to the email webhook (`/api/webhooks/email`) is signed with `WEBHOOK_SHARED_SECRET`. Add an `x-timestamp` header (seconds) and sign `timestamp.body` to get replay protection. A relay of delivery failure notices should send `"dsn": true` and `"references": ["<message-id>"]`, otherwise they are shown but change nothing. Add the report's own `Action` and `Status` lines as `"dsn_action": "failed"` and `"dsn_status": "5.1.1"`: only a failure with a 5.x.x status counts as a bounce, a "delayed" report or a 4.x.x status (mailbox full, try later) is ignored.
7. Use a mailbox that is only for this system. Pipecairn reads every unread message in the inbox it logs into. A message from a lead is stored and then marked as read. A message from anyone else is left alone (not read, not copied, not marked as read), unless you set `KEEP_UNMATCHED_MAIL=true`, which also keeps a short snippet of it in the Inbox. A reply from an alias or a forward that names one of our messages is matched to its lead either way. Do not connect a personal inbox: a stop request from an address Pipecairn cannot match is then not seen.

## Texting (Tier A: telnyx)

1. Make a Telnyx account, buy a number, and finish carrier registration (your job, see `02`).
2. Create an API key and find the account public key in the portal. The exact menu names are UNVERIFIED (see `facts/telnyx.md`).
3. Set `SMS_ADAPTER=telnyx`, `TELNYX_API_KEY`, `TELNYX_PUBLIC_KEY`, `TELNYX_FROM_NUMBER` (E.164 format, like +15555550123).
4. In Telnyx, point the inbound message webhook to `https://YOUR-API-HOST/api/webhooks/telnyx`.

## Calendar (Tier A: calcom, Tier B: google_calendar)

1. Make a Cal.com event type for your call. Make an API key.
2. Set `CALENDAR_ADAPTER=calcom`, `CALCOM_API_KEY`, `CALCOM_EVENT_TYPE_ID`, `CALCOM_WEBHOOK_SECRET`.
3. In Cal.com add a webhook to `https://YOUR-API-HOST/api/webhooks/calcom` with the same secret.
4. Google Calendar creates events only and needs an OAuth token you already have: `CALENDAR_ADAPTER=google_calendar`, `GOOGLE_CALENDAR_TOKEN`.

## CRM (Tier A: twenty, Tier B: hubspot, notion)

- Twenty: `CRM_ADAPTER=twenty`, `TWENTY_BASE_URL`, `TWENTY_API_KEY`. Real field names are unverified.
- HubSpot: `CRM_ADAPTER=hubspot`, `HUBSPOT_TOKEN` (write scope for contacts).
- Notion: `CRM_ADAPTER=notion`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`. Share the database with your integration first.

## E-signature

- `breezedoc_handoff` (Tier A) prepares a folder with the PDF and a note. You upload it by hand. Nothing is sent automatically. Set `ESIGN_ADAPTER=breezedoc_handoff` and `HANDOFF_DIR`. With the default `seed`, **Prepare for signature** shows the steps but writes no folder. Each folder name starts with the contract number.
- SendKit and Documenso are recipe prompts in `prompts/`. Paste one into Claude Code or Codex to have it build the adapter. They are not built or tested here.

## Reply understanding (optional)

The default reader is an offline stand-in made of rules. To use a language model, set `LLM_BACKEND=anthropic` and `ANTHROPIC_API_KEY` (and set `LLM_CALL_BUDGET` and `LLM_BUDGET_USD`, the only spend limits). Its accuracy here is unverified. `LLM_BACKEND` wins over the older `LLM_MODE`.
