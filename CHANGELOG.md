# Changelog

## 1.0.1 (2026-11-25)

A second, stricter review found real gaps. What changed, in plain words:

**A real install now works end to end**
- A real (not demo) install can add a sending mailbox (Deliverability page or `POST /api/mailboxes`) and create a sequence (Sequences page or `POST /api/sequences`). Before, only the demo seed could.
- Existing customers (`POST /api/customers`, or `is_customer` in the lead CSV) and an old do not contact list (`POST /api/suppressions`: emails, domains, phone numbers) can be imported. Leads already imported from them stop at once. The CSV also reads `industry`, `size` and `country`.
- New settings for the sender and the business: `SENDER_NAME`, `COMPANY_NAME`, `COMPANY_ADDRESS`, `REPLY_TO`, `PUBLIC_BASE_URL`, target industries, minimum score, bounce limits, default time zone, currency, proposal and contract days, deal values, page size, log level. The app refuses to start with `MODE=live` and `DEMO_MODE=false` while the first three are placeholders.
- Every email gets a footer (company, address, "Reply STOP") added by the program, and `List-Unsubscribe` headers; with `PUBLIC_BASE_URL` set there is also a signed one click unsubscribe link. Texts get a stop line.
- `ESIGN_ADAPTER` is honoured. Signing folders carry the contract number, so two contracts never share a folder. Cells that start with `=`, `+`, `-` or `@` are made plain text in `signers.csv`.

**Security**
- The public demo password, the made up approver and viewer accounts and the demo reset exist only while `DEMO_MODE=true` and no owner password is set.
- Sign in: one cleaned email for the limit and the lookup, size limits, an extra limit per address, and the same work for an unknown account.
- A forged "mail delivery failed" can no longer suppress a lead or pause a mailbox: a bounce counts only from a real delivery status report that names a message this system sent. A request to stop still acts at once, and the audit log notes how it was authenticated.
- Mail connections check the server certificate; plain text is allowed only to this same computer.
- Webhooks: the body is bounded while it is read, a timestamp option stops replays, and the same message or booking sent twice is stored once.
- The kill switch and "force draft" set in the app now also stop the CRM sync. Booking a call locks the lead so two clicks cannot book twice.
- Alembic and the worker read the same settings file as the API; the worker refuses the same unsafe settings. Self hosted CRM or calendar addresses on a private network need `ALLOW_PRIVATE_BASE_URLS=true`.
- The secret scan now judges the matched value, not the whole line.

**Operations and docs**
- `.env.example` and `docs/04` list every setting, with a test that fails when one is missing. An empty line in `.env` now means "not set".
- Backup script works from cron, never keeps an empty dump, saves the signing folders and can copy to another machine. Postgres image pinned to 17.7. Worker and web containers got `init`, a stop grace period and a web health check.
- Docs: Docker path (`DEMO_MODE=false`, secret, owner hash, `POSTGRES_PASSWORD`), Windows (WSL 2) and `python3-venv` notes, corrected cross references, removed promises of an export that does not exist, honest Docker status (CI builds the images; no real host deployed), `SECURITY.md` reporting steps.
- Web: error and not found pages, mailbox and starter sequence buttons, the CSV size limit matches the API (2 MB), the web proxy passes on only the last `x-forwarded-for` address.
- Versions raised to 1.0.1 (API, packages, FastAPI).

### A third look at the hardened version (same release)

An independent review of the version above found more. What changed, in plain words:

**Sending**
- A crash or a kill in the middle of a send batch no longer throws away what was already sent, and no longer sends the same people the same email again. Each message is saved on its own: it is written down as "sending" before the mail server is called and finished afterwards. A message that was being sent when the process died is marked **unconfirmed** and is never repeated by itself.
- Pause all and "force draft" are read again before every send, so pressing them stops a batch that is already running.
- The offline `seed` adapters can no longer make a real install record a fake "sent": a live real install refuses to start with `EMAIL_ADAPTER=seed`, and texts through the offline adapter stay drafts.
- The daily numbers on the Overview read only the 90 days the chart shows, not every message ever sent.

**Reading the inbox**
- Mail is read without marking it read and marked read only after it is stored, one message at a time. A failure part way no longer loses a stop request, and one unreadable message no longer blocks the ones behind it.
- Mail from an address that is not a lead (an alias, a forward, a colleague) is kept and shown in the Inbox instead of being dropped. A reply from an alias that names one of our messages is matched to its lead. Very long Message-IDs and addresses are shortened to fit.
- A reply read as a bounce but not backed by a real delivery report stays open for a person (before, it was hidden as handled). A delivery notice quoted under a normal reply no longer reads as a bounce. New **Mark as read** for replies that need no answer.
- A message of 20,000 blank lines used to keep the worker (and, for the email webhook, the whole API) busy for about 15 seconds. The text is now cut and squeezed line by line first, and the webhooks run off the event loop.

**Approvals and roles**
- A reply that was approved but could not be sent (daily limit reached, outside sending hours, mail server error) stays open and can be sent again or rejected. Before, a second approve and a reject both failed. The Approvals page now shows the message that will be sent and lists approved but unsent replies with **Send again**.
- Only the owner edits sequences, imports leads and enrols them, as the docs said. An approver approves, rejects, books calls, moves deals and can stop contacting people.
- An owner password now needs a real `SESSION_SECRET` even with `DEMO_MODE=true` (the public demo secret could sign a token for the owner).
- There is no longer a sign in limit on one account across all addresses, because anyone could use it to lock the owner out. Each address still has its own limits.

**Smaller**
- `SESSION_SECRET_PREVIOUS` keeps the unsubscribe links already emailed working after the secret is replaced.
- `/health` says only `ok`. The audit check reads the newest 20,000 rows in batches (`limit=0` for all). A proposal scope item is limited to 300 characters. Names typed into the web form lose links, markup and template fields. The web app refuses sign in and webhook paths written with dots, encoded dots or capitals.
- New table `cl_unmatched_mail` (migration 0002): run `alembic upgrade head` when you update an install that uses Postgres.
- The base package tests (81) now run with the rest (`make test`, `pytest.ini`), and the web app's unit tests run with `pnpm test:ui` (and `make test-web`). The test helpers moved from `conftest.py` to `support.py` because two files named `conftest` cannot be imported side by side.
- Documented as known limits: no server side session revocation, an unkeyed audit chain, replies approved by any owner or approver, no double opt in for form leads, base image digests (how to pin them is in `12`).

### Also in 1.0.1 (written before this review)

- Interface and API fixes from walking every screen as a first time owner (two passes): a blank reply can no longer be approved (the server refuses it, the button is disabled); the Proposals lead list includes leads who replied or booked; G then 1 to 9 goes to a page as the palette says; signing in returns to the page you asked for; Pause all and Sign out stay reachable on a phone and the top button says it turns the kill switch off; every audit row opens with its detail; Approvals reads in plain words and links to the draft; the Integrations tier text no longer repeats itself; the pipeline shows all seven columns on a laptop and long columns scroll inside themselves; score explanations read as words; load errors show on Proposals. Browser tests for each fix are in `apps/web/e2e/round5-ui.spec.ts` and `round5-pass2.spec.ts`.
- Base 1.2.1: counting numbers step at the precision of their target.
- Reply reader: reads only what the person wrote (quoted mail, signature, phone line and legal footer removed), reads the subject for delivery notices and auto replies, handles plain refusals, timing words, named referrals and common phrases in other languages. New `tools/eval_independent.py` and two independent held out sets: set B (run once) 114 of 170 exactly right, set A first run 103 of 174. See `docs/REPLY-READER-EVAL.md`.
- Live model path (`LLM_BACKEND=anthropic`, UNVERIFIED live): reader with a system prompt and a strict JSON schema, draft writer, score explainer and week summary in `model_tasks.py`; a local fake server (`mock/anthropic_mock.py`), recorded fixtures (`data/llm_fixtures/`) and tests that a hostile reply cannot change the output fields or send anything.
- Contract tests for Cal.com and Telnyx against saved excerpts of the vendors' public docs (`mock/contracts/`), notes for Twenty and the mail protocols where no spec exists.
- `tools/make_counts.py` and `tools/check_docs.py`: the numbers in README and docs come from `data/measured.json`.
- Renamed from Closeline to Pipecairn after a public name check. The Python package, environment variable prefix, interface text, documents, prompts, templates and screenshots all use the new name.
- Shared base updated to 1.1.0: the top bar search button is named "Search", card titles are second level headings, the keyboard shortcut symbols show on phones, and dialogs settle in 320 ms.
- Lead import: a "Choose a CSV file" button in the import dialog. The browser reads the file, shows the row and column count and the first rows, and warns about a missing email column before anything is sent. Browser test with a fixture file, unit tests for the CSV reader, new screenshots (17).
- Tool comparison: every tool named in the docs and adapters is scored on six criteria with one evidence line each, closeness and a recommendation by user type. `tools/score_tools.py` computes the totals from `data/tool_scores.json` and rewrites `docs/TOOLS-AND-ALTERNATIVES.md`; a test fails if they disagree. The first pass CRM numbers were re-scored with evidence.
- Reply reader evaluation: a held out set of 134 replies written separately (`data/reply_heldout.json`), a second set of 42, `tools/eval_replies.py --set heldout` with per class precision, recall and confusion pairs, and `docs/REPLY-READER-EVAL.md`. First held out score of the offline rules: 44 of 134 (32.8 percent). Opt out, bounce and away rules were then widened; that result is reported separately as no longer held out.
- `make check-env` runs `tools/check_env.py`: lists missing and half filled settings without printing values.
- The secret scan test no longer trips the scan.

## 1.0.0

First release. Draft first sending engine with a chain of safety gates, reply reader (offline stand-in), proposals and PDFs, signature handoff, ten dashboard pages, 15 adapters (none verified live), demo data with planted traps, docs 00 to 15.
