# Security and data

## What the app does

- Sign in with email and password. Passwords are stored only as argon2 hashes. Sessions are signed, httpOnly cookies. Five wrong tries at one account from one address slow down fast, a wider limit counts every try from one address, and spaces or capitals in the email never give a fresh set of tries. There is deliberately no limit on one account across all addresses, because it would let a stranger lock the owner out of their own system by typing wrong passwords.
- The app refuses to start with an example or short `SESSION_SECRET` when `DEMO_MODE=false` or whenever `OWNER_PASSWORD_HASH` is set, and refuses `DEMO_MODE=true` on Postgres. The public demo password, the made up approver and viewer accounts and the demo data reset (which erases every table) exist only while `DEMO_MODE=true` AND no `OWNER_PASSWORD_HASH` is set.
- Writes from the browser must carry a special header, which blocks cross site tricks. The web app refuses to forward login and webhook calls.
- Webhooks are verified before anything is read: Telnyx by Ed25519 signature with a 5 minute window, Cal.com and the email and form hooks by HMAC. Bodies over 1 MB are refused before they are read in full. The email and form hooks accept an `x-timestamp` header and then sign `timestamp.body`, so a captured request stops working after five minutes; the same message sent twice is stored once.
- Email connections check the server certificate; plain text mail is refused for any host except this same computer.
- A request to stop in a reply is honoured at once. A bounce is believed only when it is a real delivery status report that names a message this system sent, so a forged "mail delivery failed" cannot suppress anyone or pause a mailbox. The Audit page notes how each stop request was authenticated.
- The kill switch and "force draft" set in the app also stop the CRM sync, not only sending.
- Every email carries a footer (your company, address and how to stop) and `List-Unsubscribe` headers; with `PUBLIC_BASE_URL` set it also has a signed one click unsubscribe link.
- Adapter addresses are checked so a setting cannot point at a private network (server side request forgery guard).
- Anything a lead writes is wrapped as untrusted text before a language model sees it. The model can suggest a reply; it cannot send, change settings or switch live sending on.
- Every important action goes in a hash chained audit log. **Verify the chain** detects edits. The chain is not keyed: someone who can write to the database can rewrite the whole chain and its hashes, so it catches accidents and partial edits, not a determined attacker. Keep backups on another machine. The check reads the newest 20,000 rows by default (`/api/audit/verify?limit=0` reads all of them, in batches).
- The suppression list is re-read from the database before every send, and so are the kill switch and "force draft".
- Each send is recorded as "sending" and committed before the mail server is called, and finished one message at a time, so a crash never loses what was sent and never sends the same message twice (an interrupted one is marked unconfirmed).
- The mailbox is read without marking mail as read; a message is marked read only after it is stored, so a failure never loses a stop request. Mail from an address that is not a lead is kept and shown in the Inbox.
- The public `/health` page says only that the app is up. Roles: the owner changes sequences, imports leads and settings; an approver approves, rejects, books and stops people; a viewer reads.

## What you must do

- Keep `.env` out of git. Use long random values for `SESSION_SECRET` and `WEBHOOK_SHARED_SECRET`.
- Put the API and web behind HTTPS.
- Keep keys to the minimum scope (HubSpot write only, a Telnyx key for messaging only).
- Back up, and rotate any key you suspect leaked. If you replace `SESSION_SECRET`, everyone is signed out and the unsubscribe links in emails already sent stop working; put the old value in `SESSION_SECRET_PREVIOUS` so those links keep working.

## Personal data

Leads are personal data. You decide the retention period. To remove a person, add them to the suppression list first (so they are never re-imported and contacted), then delete the lead if the law or they ask. Keep a suppression record even after deletion, otherwise a re-import could contact them again.

## Checks run

Secret scan (`tools/scan_secrets.py`), `pip-audit` and `pnpm audit` on 2026-11-22 found nothing. Details in `SECURITY.md`.

## Reporting a problem

See `SECURITY.md` at the repository root.
