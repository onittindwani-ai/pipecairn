# Changelog

## Unreleased

- Interface and API fixes from walking every screen as a first time owner (two passes): a blank reply can no longer be approved (the server refuses it, the button is disabled); the Proposals lead list includes leads who replied or booked; G then 1 to 9 goes to a page as the palette says; signing in returns to the page you asked for; Pause all and Sign out stay reachable on a phone and the top button says it turns the kill switch off; every audit row opens with its detail; Approvals reads in plain words and links to the draft; the Integrations tier text no longer repeats itself; the pipeline shows all seven columns on a laptop and long columns scroll inside themselves; score explanations read as words; load errors show on Proposals. Browser tests for each fix are in `apps/web/e2e/round5-ui.spec.ts` and `round5-pass2.spec.ts`.
- Base 1.2.1: counting numbers step at the precision of their target.
- Reply reader: reads only what the person wrote (quoted mail, signature, phone line and legal footer removed), reads the subject for delivery notices and auto replies, handles plain refusals, timing words, named referrals and common phrases in other languages. New `tools/eval_independent.py` and two independent held out sets: set B (run once) 114 of 170 exactly right, set A first run 103 of 174. See `docs/REPLY-READER-EVAL.md`.
- Live model path (`LLM_BACKEND=anthropic`, UNVERIFIED live): reader with a system prompt and a strict JSON schema, draft writer, score explainer and week summary in `model_tasks.py`; a local fake server (`mock/anthropic_mock.py`), recorded fixtures (`data/llm_fixtures/`) and tests that a hostile reply cannot change the output fields or send anything.
- Contract tests for Cal.com and Telnyx against saved excerpts of the vendors' public docs (`mock/contracts/`), notes for Twenty and the mail protocols where no spec exists.
- `tools/make_counts.py` and `tools/check_docs.py`: the numbers in README and docs come from `data/measured.json`.
- Renamed from Closeline to Pipecairn after a public name check. The Python package, environment variable prefix, interface text, documents, prompts, templates and screenshots all use the new name.

## 1.0.1

- Shared base updated to 1.1.0: the top bar search button is named "Search", card titles are second level headings, the keyboard shortcut symbols show on phones, and dialogs settle in 320 ms.
- Lead import: a "Choose a CSV file" button in the import dialog. The browser reads the file, shows the row and column count and the first rows, and warns about a missing email column before anything is sent. Browser test with a fixture file, unit tests for the CSV reader, new screenshots (17).
- Tool comparison: every tool named in the docs and adapters is scored on six criteria with one evidence line each, closeness and a recommendation by user type. `tools/score_tools.py` computes the totals from `data/tool_scores.json` and rewrites `docs/TOOLS-AND-ALTERNATIVES.md`; a test fails if they disagree. The first pass CRM numbers were re-scored with evidence.
- Reply reader evaluation: a held out set of 134 replies written separately (`data/reply_heldout.json`), a second set of 42, `tools/eval_replies.py --set heldout` with per class precision, recall and confusion pairs, and `docs/REPLY-READER-EVAL.md`. First held out score of the offline rules: 44 of 134 (32.8 percent). Opt out, bounce and away rules were then widened; that result is reported separately as no longer held out.
- `make check-env` runs `tools/check_env.py`: lists missing and half filled settings without printing values.
- The secret scan test no longer trips the scan.

## 1.0.0

First release. Draft first sending engine with a chain of safety gates, reply reader (offline stand-in), proposals and PDFs, signature handoff, ten dashboard pages, 15 adapters (none verified live), demo data with planted traps, docs 00 to 15.
