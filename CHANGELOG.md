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
- A reply from an alias or a forward that names one of our messages is matched to its lead. Mail from other addresses is left alone unless `KEEP_UNMATCHED_MAIL=true` (see the fourth look below). Very long Message-IDs and addresses are shortened to fit.
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
- New table `cl_unmatched_mail` (migration 0002, and a `flag` column in 0003): run `alembic upgrade head` when you update an install that uses Postgres. SQLite gets the table and the column at start.
- The base package tests (81) now run with the rest (`make test`, `pytest.ini`), and the web app's unit tests run with `pnpm test:ui` (and `make test-web`). The test helpers moved from `conftest.py` to `support.py` because two files named `conftest` cannot be imported side by side.
- Documented as known limits: no server side session revocation, an unkeyed audit chain, replies approved by any owner or approver, no double opt in for form leads, base image digests (how to pin them is in `12`).

### A fourth look at the version above (same release)

A third independent review found two serious gaps in the mail code added just before. What changed, in plain words:

**Reading mail**
- One badly made message can no longer stop the inbox. A message with a character set that does not exist (anyone could send one), broken encoding, a huge header, thousands of nested parts or no parts is read on its own: its text is decoded with replacement characters and flagged, or, if even that fails, the whole message is kept as raw text and shown to a person as "could not be read properly" (nothing is drafted or sent from it, and, as for any reply, that person's follow ups stop). The message behind it, a stop request included, is read as normal. Before, one such message made every poll fail, so the stop request behind it was never stored. A message that cannot be stored three polls in a row is kept as unreadable mail for a person.
- A request to stop now wins over bounce wording: "Please unsubscribe me, this address is no longer used" or "remove me, this mailbox is no longer monitored" used to be read as a bounce guess and ignored, so the lead stayed in the sequence.
- A delivery report is read from its own `Action` and `Status` lines: only "failed" with a 5.x.x status is a bounce. "Delayed", "mailbox full" and other 4.x.x reports change nothing (before, they suppressed the address for good, marked the lead dead and counted against the mailbox). The email webhook accepts `dsn_action` and `dsn_status` for relays.
- HTML only mail is now read (its text is taken out of the markup); before, a stop request in an HTML only message was not seen.
- Mail from an address that is not a lead is no longer read, copied or marked as read by default: connecting a personal inbox used to copy a snippet of every message into the database. Set `KEEP_UNMATCHED_MAIL=true` to keep it (a short snippet, with a new one click **Never write to this address again**); use a mailbox that is only for this system.

**Sending**
- A message that was being sent when the worker died is not sent again however late the restart is. Before, a restart more than 10 minutes later marked it unconfirmed but did not move the sequence on, so the person was mailed again. Now the step counts as done (also when the person had meanwhile asked to wait, and for rows an older version left behind) and a person can press **It is not in the Sent folder, send it again** on the lead.
- A mail server that refuses an address for good (a 5xx answer at RCPT) is a hard bounce at once: the address is suppressed, the lead is dead and the mailbox's bounce count goes up. Before, it was retried every hour for ever.
- Any other refusal of the message or the address (for now) is tried three times, an hour apart, then the person is stopped for a person to look at. A wrong password, an unreachable mail server or a refused sender address never stops anyone.
- An error after the server took the message (a broken connection while it closed, or no answer after the message was handed over) no longer counts as failed. It is "sent" or "unconfirmed" and is never sent again.

**Smaller**
- The live refresh of the web app now works: the server names each event and the page only listened to unnamed ones, and every connection replayed the history from the start. The page now starts after the newest event and listens for each kind (`GET /api/events/latest`). The shared base's stream route is unchanged.
- The web proxy refuses a path that decodes to `?`, `#` or a control character (`auth/login%3F` used to pass the sign in guard and reach the API as `auth/login?`), and sends every segment encoded again.
- The sign in request is limited to 4 KB (it accepted 25 MB without a session).
- CSV import: headers such as `First Name`, `E-mail` or `Job Title` are matched (they were silently dropped), the result lists the columns that were ignored, and a cell that is too long is skipped and counted instead of failing the whole file; a file the reader cannot parse gives a plain message instead of an error.
- Backups are written readable by their owner only. `PUBLIC_BASE_URL` is in the Hetzner steps and docs `12` has a Docker update path.
- A save that fails is now an error, not a success: on this FastAPI version a route that took the database session the plain way saved after the answer had gone out, so a failed save still showed success and a webhook sender (which only retries on an error) never sent the message again. Every route now saves before it answers, and the webhooks also save explicitly before they say ok.
- A test that always passed (`hasattr` on a field that does not exist) now reads the enrolment itself.

### A fifth look at the version above (same release)

A fourth independent review found two serious and five medium gaps. What changed, in plain words:

**Reading mail**
- One email could keep the worker busy for minutes. A message full of unfinished `<script ` tags, or a header made of quotation marks, took seconds to minutes to read, and mail from people who are not leads is read again at every poll, so the single worker never got past it. Now only the first 256 KB of a message is fetched and read (a bigger one is read from its first part and marked "large message"), every header value is cut to 2,000 characters before it is parsed, tags are stripped in one pass, and a message that still takes more than 5 seconds is stopped and kept as raw text. The 5 second stop works in the worker (it needs the main thread); the size limits and the one pass reader protect everywhere else.
- Ordinary hot replies are no longer a permanent opt out. "Can we block this Thursday", "I'll loop in our legal team", "remove the setup fee", "please stop sending the PDFs, just call me", "forward to my attorney" and "this unsolicited message is actually relevant" used to suppress the lead for good and file the reply as handled, and a reply to a campaign called "Stop writing follow up emails by hand" was matched on its subject alone. Now only a complete request ("unsubscribe", "remove me from your list", "stop emailing me", "do not contact me") suppresses. Wording that only might be one stops the follow ups, suppresses nothing and leaves the reply open with a note, and the Inbox has **Never contact this person again**. `Re:` is dropped from the subject and a subject that is one of ours is ignored; the subject "unsubscribe" that the unsubscribe link sends still counts.
- Carrier style stop words now count when they are the whole message: STOPALL, QUIT, CANCEL, END and "Please stop" (before, they were read as questions and a reply was drafted). "Cancel my Tuesday meeting" is not a stop.
- A reply that only sounds like a bounce ("refused by our spam filter, but I am interested") now stops the follow ups and stays open; before, the next step still went out. A date or a ticket number alone ("I'm back in the office next Tuesday", "re ticket #4412") is no longer filed away as an automatic reply: an automatic reply needs its words or an auto reply header (`Auto-Submitted`, `X-Autoreply`), which the mail reader now notices and the email webhook accepts as `auto_submitted`.
- There is an owner only way to undo a stop: **Lift the stop (owner)** on the reply, or `POST /api/leads/{id}/lift-suppression`. It is written to the audit log, and the person is not put back into a sequence on their own.

**Sending**
- Resuming a mailbox that was paused for bounces now works. The pause rule counted every send and bounce since the mailbox began, so the same totals paused it again at the next send. The rate is now counted from the last resume (new columns on the mailbox table, migration 0004; SQLite adds them at start).
- Only an address the server says does not exist is a hard bounce (an enhanced status of 5.1.x, or 550, 551 or 553 with no wording about relaying, blocking or policy). Code 554, "relay denied", a blocked sending address and spam list refusals used to suppress up to about 20 leads before the mailbox paused, with no way back. They are now the mailbox's problem: tried again later, never counted against the lead, and noted on the Audit page as `mailbox.server_refusal`.
- One broken enrolment can no longer block every send behind it. An error while preparing a step is caught for that person only: the work is undone, the error is written on their timeline, they move an hour back in the queue, and after three errors in a row they are stopped (`send_error`). A database that stops answering still stops the whole run. A rendered subject over 300 characters is cut to what the column holds.

**Smaller**
- The CSV import cleans first name, last name and title the same way the web form does (links, markup, template fields and line breaks are removed).
- The test count in the docs is read from `data/measured.json` again, and that file was updated from a full run.

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
