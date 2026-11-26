# Limits and honest notes

Read this before you trust Pipecairn with real customers.

## Not tested against real services

- No adapter is `live_verified`. Email, texting, calendar and CRM adapters were run only against local copies written from public docs, including fake SMTP and IMAP servers over real sockets. Real services may behave differently.
- Tier B adapters (Google Calendar, HubSpot, Notion) were written from docs and never run.
- Tier C (SendKit, Documenso) are recipe prompts, not code.
- Several vendor facts are unverified: see `FACTS-AND-SOURCES.md`.
- The Docker images are built and the compose stack is started on GitHub by the CI workflow (the API and the web app must answer). I did not run Docker on my own machine for this version. No deploy to a real Vercel, Railway or Hetzner host was done, so the three hosting guides are written from the vendors' docs and not run.

## The reply reader

- The default reader is an offline stand-in made of rules. It is **not** a language model. On two independent sets of replies written by people who never saw the code it read 67 percent (set B, 114 of 170, the number to quote) of replies exactly as their key says, and about 71 percent when the key's own acceptable alternatives count. It missed 7 of 34 clear stop requests on set B. Details, the earlier numbers and what was changed: `REPLY-READER-EVAL.md`.
- A live model path exists and is selected with `LLM_BACKEND=anthropic` plus `ANTHROPIC_API_KEY` (`apps/api/src/pipecairn/model_tasks.py`). It reads replies with a system prompt and a fixed JSON schema, writes the draft answers a person approves, and writes the score explanation and week summary. **UNVERIFIED live**: it was only run against a local fake server that checks the request shape, and against recorded fixtures made from that fake. It has never been run with a real key, so how well a real model reads replies here is not measured. Run `python3 tools/eval_independent.py` on sets A and B with the live backend before a client depends on it.
- Guards that apply to the live path (all tested): the reply is passed as marked data and the system prompt says never to follow it; the answer must match the schema or the reply goes to a person; the model has no tools, so it cannot send, approve, delete or suppress anything; a draft with a link is replaced by the plain template; a draft with a `[[FILL IN]]` part cannot be sent; the kill switch, call budget and spend budget stop the model; unsubscribe, bounce and out of office are still decided by rules first.
- A model that is fooled by a reply can at worst give a wrong class or a poor draft. A wrong class changes what the system does to that one lead (for example "stop contacting" or "wait"). Every outgoing answer still needs a person to approve it. Read the inbox.
- Complete stop requests are decided by rules first, on purpose, so a model cannot talk itself out of a stop request. Wording that only might be one is not a permanent stop: it stops the follow ups and goes to a person (see `13`). A reader that is wrong about a plain "no thanks" can still suppress a lead (the reader treats a flat no as a stop); an owner can undo that from the Inbox.

## What the demo data is

All people, companies, numbers and replies are invented. 41 companies, 123 lead rows (113 unique after 10 planted duplicate pairs), 6 role based and 5 invalid emails, 8 suppressed emails and 2 suppressed domains, 8 leads at customer companies, 3 invalid time zones, 5 invalid texting numbers, 4 mailboxes (one at its cap, one with a high bounce rate), 29 addresses that must never be written to, and 10 scripted replies. Do not quote any result from it as real.

## Things that are your job

- Texting carrier registration (10DLC in the US).
- Domain records (SPF, DKIM, DMARC) and warming up mailboxes.
- Knowing your local email and texting rules. This is not legal advice.
- Obtaining consent for texts.

## Known gaps

- There is no export button for leads, the audit log or settings. Back up the database (`11`).
- One mail account (`SMTP_USER`) signs in for every mailbox you add. More than one mail account needs more than one install.
- A bounce is believed only from a delivery status report that names a message we sent. A mail provider that relays mail to the email webhook must pass `dsn` (true for a delivery status report) and `references` (the Message-IDs it names), or its bounces are shown in the Inbox but change nothing. It may also pass `auto_submitted` (the value of the `Auto-Submitted` header, or true); without it a date or a ticket number alone is not taken for an automatic reply.
- Still fixed in the code, not settings: the score weights, the role based address list (info@, sales@ and so on), the free mail list, the contract wording apart from the notice days, and the proposal layout. PDFs use a standard font: Western European letters and the euro sign work, other scripts print as `?`.
- Every email gets the footer from `COMPANY_NAME` and `COMPANY_ADDRESS`, and the seed demo sequence still signs itself "Alex". Real sequences should use `{{sender_name}}`.
- Time zone handling needs a valid zone per lead; an unknown zone means that lead is not sent to.
- One worker process. It is built for hundreds to low thousands of leads, not millions.
- SQLite is for trying out. Use Postgres for real work.
- English only.
- Three accounts at most: owner, approver and an optional read only viewer.
- Sessions cannot be ended one by one: a signed session stays valid until it expires (8 hours). To end all of them change `SESSION_SECRET` (and put the old value in `SESSION_SECRET_PREVIOUS` if you want the unsubscribe links already emailed to keep working).
- The audit chain is not keyed, so it shows accidental and partial edits, not a rewrite by someone with database access. Keep off machine backups.
- Reply drafts are asked for by the system, so any owner or approver may approve them; the rule that the person who asked cannot approve never applies to replies.
- A web form lead is not double opt in: the name is cleaned (links, markup and template fields removed, 60 characters) but the person is written to as soon as the lead is scored. Use the form hook only for people who asked to be contacted.
- A mail provider that relays mail to the email webhook should pass `references` (the Message-IDs of the mail being answered): that is how a reply from an alias or a forward is matched to its lead. Without it such mail is kept in the Inbox as unmatched mail.
- An interrupted send is marked unconfirmed and never repeated automatically (see `11`); whether it was delivered is not known.
- A stop request from an address that is not a lead and that does not name one of our messages (a forward that drops the message headers) is not matched to its lead. With `KEEP_UNMATCHED_MAIL=true` it is shown in the Inbox with a one click **Never write to this address again**; without it that mail is left unread in the mailbox, so read the mailbox now and then.
- Mail that is not from a lead is left unread in the mailbox when `KEEP_UNMATCHED_MAIL` is off, so it is downloaded (only its first 256 KB) and looked at again at every poll (once a minute). A mailbox with a large backlog of other people's mail is slow for that reason: use a mailbox just for this system.
- A message cut off while it was handed to the mail server (unconfirmed) is not added to the mailbox's count of sends today, so a daily cap can be passed by one message.
- The reply reader works on text. A message that cannot be decoded (a broken encoding, an unknown character set) is stored as raw text and shown to a person, but a stop request inside it may not be recognised.
- Four small changes to the shared base were requested and not made (the base is frozen): a search button label, card heading level, keyboard hint glyphs on phones, and sheet settle time. They are only a request to the maintainers of the shared base; they do not affect how the product works.
