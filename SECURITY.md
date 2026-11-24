# Security

## Reporting a problem

Please do not post security problems in a public issue. Use the repository's private security advisory feature, or contact the maintainers privately. Include steps to reproduce. Never include real keys, passwords or customer data.

## What was checked

- Webhook signature checks (Telnyx Ed25519, Cal.com and generic HMAC), with tests for wrong signature, old timestamp and oversized body.
- Server side request forgery guard on adapter addresses.
- Login rate limit, signed httpOnly session cookie, CSRF header on writes, role checks (owner only for settings and resuming mailboxes).
- Prompt injection: lead text is wrapped as untrusted and cannot trigger sending.
- Secret scan of tracked files (`python tools/scan_secrets.py`): nothing found, with a test that it does catch fake looking keys.
- Dependency audit on 2026-11-22: `pip-audit` over the 39 installed Python packages and `pnpm audit` over all JavaScript packages both reported no known vulnerabilities. This only covers known, published problems on that date.
- A prompt injection test (a reply that tries to make the app send or skip approval) and a server side request forgery test.

## What was not checked

No outside penetration test. No test against real vendor accounts. Docker images were not built here. Treat this as a careful self review, not an audit.

## Supported versions

Only the latest release.
