# Limits and honest notes

Read this before you trust Pipecairn with real customers.

## Not tested against real services

- No adapter is `live_verified`. Email, texting, calendar and CRM adapters were run only against local copies written from public docs, including fake SMTP and IMAP servers over real sockets. Real services may behave differently.
- Tier B adapters (Google Calendar, HubSpot, Notion) were written from docs and never run.
- Tier C (SendKit, Documenso) are recipe prompts, not code.
- Several vendor facts are unverified: see `FACTS-AND-SOURCES.md`.
- Docker images were not built (no Docker daemon in the build environment). The web app build and the compose file check were run. Deploys to Vercel, Railway and Hetzner were not done.

## The reply reader

- The default reader is an offline stand-in made of rules. It is **not** a language model. On two independent sets of replies written by people who never saw the code it read 67 percent (set B, 114 of 170, the number to quote) of replies exactly as their key says, and about 71 percent when the key's own acceptable alternatives count. It missed 7 of 34 clear stop requests on set B. Details, the earlier numbers and what was changed: `REPLY-READER-EVAL.md`.
- A live model path exists and is selected with `LLM_BACKEND=anthropic` plus `ANTHROPIC_API_KEY` (`apps/api/src/pipecairn/model_tasks.py`). It reads replies with a system prompt and a fixed JSON schema, writes the draft answers a person approves, and writes the score explanation and week summary. **UNVERIFIED live**: it was only run against a local fake server that checks the request shape, and against recorded fixtures made from that fake. It has never been run with a real key, so how well a real model reads replies here is not measured. Run `python3 tools/eval_independent.py` on sets A and B with the live backend before a client depends on it.
- Guards that apply to the live path (all tested): the reply is passed as marked data and the system prompt says never to follow it; the answer must match the schema or the reply goes to a person; the model has no tools, so it cannot send, approve, delete or suppress anything; a draft with a link is replaced by the plain template; a draft with a `[[FILL IN]]` part cannot be sent; the kill switch, call budget and spend budget stop the model; unsubscribe, bounce and out of office are still decided by rules first.
- A model that is fooled by a reply can at worst give a wrong class or a poor draft. A wrong class changes what the system does to that one lead (for example "stop contacting" or "wait"). Every outgoing answer still needs a person to approve it. Read the inbox.
- Unsubscribe words are decided by rules first, on purpose, so a model cannot talk itself out of a stop request.

## What the demo data is

All people, companies, numbers and replies are invented. 41 companies, 123 lead rows (113 unique after 10 planted duplicate pairs), 6 role based and 5 invalid emails, 8 suppressed emails and 2 suppressed domains, 8 leads at customer companies, 3 invalid time zones, 5 invalid texting numbers, 4 mailboxes (one at its cap, one with a high bounce rate), 29 addresses that must never be written to, and 10 scripted replies. Do not quote any result from it as real.

## Things that are your job

- Texting carrier registration (10DLC in the US).
- Domain records (SPF, DKIM, DMARC) and warming up mailboxes.
- Knowing your local email and texting rules. This is not legal advice.
- Obtaining consent for texts.

## Known gaps

- Lead import is through the API and CSV text; there is no upload button.
- Time zone handling needs a valid zone per lead; an unknown zone means that lead is not sent to.
- One worker process. It is built for hundreds to low thousands of leads, not millions.
- SQLite is for trying out. Use Postgres for real work.
- English only.
- Three accounts at most: owner, approver and an optional read only viewer.
- Four small changes to the shared base were requested and not made (the base is frozen): a search button label, card heading level, keyboard hint glyphs on phones, and sheet settle time. They are listed in the build ledger.
