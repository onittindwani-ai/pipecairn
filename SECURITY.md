# Security

## Reporting a problem

Please do not post security problems in a public issue. Open the repository's **Security** tab and choose **Report a vulnerability**: that report is private. We aim to acknowledge it within 5 working days. Include steps to reproduce. Never include real keys, passwords or customer data.

## Two risks to know before you deploy

- **Demo mode.** `DEMO_MODE=true` switches on a public demo password, made up approver and viewer accounts and a button that erases the database. They turn off the moment `OWNER_PASSWORD_HASH` is set, and the app refuses demo mode on Postgres, but a real install should always run with `DEMO_MODE=false`.
- **Secrets.** `SESSION_SECRET` signs every login. With `DEMO_MODE=false`, or whenever an owner password is set, the app refuses to start on a short or example value. Anyone who learns it can sign in as the owner, so keep `.env` out of git and change it if it may have leaked.

## What was checked

- Webhook signature checks (Telnyx Ed25519, Cal.com and generic HMAC), with tests for wrong signature, old timestamp and oversized body.
- Server side request forgery guard on adapter addresses.
- Login rate limit, signed httpOnly session cookie, CSRF header on writes, role checks (owner only for settings, sequences, lead import and resuming mailboxes).
- Prompt injection: lead text is wrapped as untrusted and cannot trigger sending.
- Secret scan of tracked files (`python tools/scan_secrets.py`): nothing found, with a test that it does catch fake looking keys.
- Dependency audit on 2026-11-22: `pip-audit` over the 39 installed Python packages and `pnpm audit` over all JavaScript packages both reported no known vulnerabilities. This only covers known, published problems on that date.
- A prompt injection test (a reply that tries to make the app send or skip approval) and a server side request forgery test.

## What was not checked

No outside penetration test. No test against real vendor accounts. No deploy to a real host: the CI workflow builds the Docker images and starts the stack, nothing more. Version 1.0.1 fixed the findings of a second, stricter self review (see `CHANGELOG.md`). Treat this as a careful self review, not an audit.

## Supported versions

Only the latest release.
