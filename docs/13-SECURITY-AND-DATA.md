# Security and data

## What the app does

- Sign in with email and password. Passwords are stored only as argon2 hashes. Sessions are signed, httpOnly cookies. Five wrong tries from one address slow down fast.
- Writes from the browser must carry a special header, which blocks cross site tricks. The web app refuses to forward login and webhook calls.
- Webhooks are verified before anything is read: Telnyx by Ed25519 signature with a 5 minute window, Cal.com and the email and form hooks by HMAC. Bodies over 1 MB are refused.
- Adapter addresses are checked so a setting cannot point at a private network (server side request forgery guard).
- Anything a lead writes is wrapped as untrusted text before a language model sees it. The model can suggest a reply; it cannot send, change settings or switch live sending on.
- Every important action goes in a hash chained audit log. **Verify the chain** detects edits.
- The suppression list is re-read from the database before every send.

## What you must do

- Keep `.env` out of git. Use long random values for `SESSION_SECRET` and `WEBHOOK_SHARED_SECRET`.
- Put the API and web behind HTTPS.
- Keep keys to the minimum scope (HubSpot write only, a Telnyx key for messaging only).
- Back up, and rotate any key you suspect leaked.

## Personal data

Leads are personal data. You decide the retention period. To remove a person, add them to the suppression list first (so they are never re-imported and contacted), then delete the lead if the law or they ask. Keep a suppression record even after deletion, otherwise a re-import could contact them again.

## Checks run

Secret scan (`tools/scan_secrets.py`), `pip-audit` and `pnpm audit` on 2026-11-22 found nothing. Details in `SECURITY.md`.

## Reporting a problem

See `SECURITY.md` at the repository root.
