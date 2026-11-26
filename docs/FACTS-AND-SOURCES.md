# Facts and sources

Every outside fact this project relies on, with where it came from and when it was checked (2026-11-22). **VERIFIED** means a public page or a package registry said it on that date. **UNVERIFIED** means a third party said it, sources disagreed, or I could not find it. Nothing here was tested against a real account. Vendors change things, so check the page before you rely on a fact. One file per vendor is in `docs/facts/`.

| Fact | Status | Source |
|---|---|---|
| Telnyx sends a text with `POST /v2/messages`, Bearer key, body `to`, `text`, `from`; the reply has `data.id` | VERIFIED | https://developers.telnyx.com (messages API) |
| Telnyx signs webhooks with Ed25519 over `timestamp\|body`; headers `telnyx-signature-ed25519` and `telnyx-timestamp`; 5 minute tolerance | VERIFIED | https://developers.telnyx.com (webhook signing) |
| Where the Telnyx public key lives in the portal | UNVERIFIED | A third party guide said Account Settings, Keys and Credentials |
| Cal.com books with `POST /v2/bookings`, header `cal-api-version: 2026-02-25`, body `start`, `attendee`, `eventTypeId` | VERIFIED | https://cal.com/docs/api-reference/v2 |
| Cal.com slots version header value | UNVERIFIED | Two docs pages gave two values, so it is a setting (`CALCOM_SLOTS_VERSION`) |
| Cal.com webhook signature is HMAC SHA256 hex of the raw body in `x-cal-signature-256` | UNVERIFIED | A third party source |
| Where to create a Cal.com API key and find the event type ID | UNVERIFIED | Sources disagree |
| Twenty CRM takes GraphQL at `/graphql` with a Bearer key | VERIFIED (shape) | https://docs.twenty.com |
| Twenty `createPerson` field names | UNVERIFIED | Introspection can be turned off for API keys |
| HubSpot creates a contact with `POST /crm/v3/objects/contacts` and a `properties` object | VERIFIED | https://developers.hubspot.com |
| HubSpot private app path in the portal | UNVERIFIED | A third party guide |
| Notion creates a page with `POST /v1/pages`, header `Notion-Version: 2026-03-11` | VERIFIED | https://developers.notion.com |
| Notion needs a data source id on newer API versions | UNVERIFIED | Docs hint at it; a database id may still work |
| Google Calendar creates events with `POST /calendar/v3/calendars/primary/events` and scope `calendar.events` | VERIFIED | https://developers.google.com/calendar |
| How to get a Google OAuth token for it | UNVERIFIED | Not walked through |
| Anthropic API keys are made at platform.claude.com, Settings, API keys, shown once, start with `sk-ant-` | VERIFIED | https://docs.claude.com |
| Gmail needs 2 step verification, then an app password; IMAP `imap.gmail.com:993`, SMTP `smtp.gmail.com:465` | VERIFIED (ports as listed), UNVERIFIED (587) | https://support.google.com/mail |
| Documenso API base `https://app.documenso.com/api/v2` | VERIFIED | https://docs.documenso.com |
| Documenso create document endpoints | UNVERIFIED | Not shown, so it is a recipe prompt only |
| Breezedoc and SendKit APIs | UNVERIFIED | Not checked, so no API is claimed |
| Vercel can build a monorepo app from `apps/web` with "Include source files outside of the Root Directory" | VERIFIED | https://vercel.com/docs |
| Railway "Config as Code" is deprecated, new services cannot opt in, existing files work until 2026-12-01 | VERIFIED | https://docs.railway.com |
| Hetzner cloud-init user data starts with `#cloud-config` | VERIFIED | https://docs.hetzner.com |
| Hetzner firewall and SSH key details | UNVERIFIED | Official pages were thin |
| Next.js 16 uses `proxy.ts` instead of middleware | VERIFIED | https://nextjs.org/docs (page updated 2026-11-18) |
| Library versions: next 16.4.6, react 19.3.1, @tanstack/react-query 5.108.2, @playwright/test 1.65.1, fastapi 0.165.0, alembic 1.20.1, cryptography 50.0.2 | VERIFIED | npm and PyPI registries, 2026-11-22 |

## What is measured here, not looked up

The seed counts, test counts, coverage and the reply classifier score come from running this repo. They are in `docs/14-LIMITS-AND-HONEST-NOTES.md` and the README. If a number there and a number somewhere else disagree, the measured one is right.

Tool comparison sources (pricing pages, licences, 2026-11-23): see `facts/comparison-sources.md`.

## Model path (added 2026-11-23, round 4)

| Fact | Source | Status |
|---|---|---|
| The live reader, drafter, score explainer and week summary call the shared wrapper (`sendora_core.llm`, Anthropic Messages API: `POST /v1/messages`, headers `x-api-key`, `anthropic-version: 2026-10-21`, `output_config.format` json_schema, no temperature or tools) | Anthropic public API documentation read 2026-11-23 (the page addresses are in the facts file of the shared base, which is not part of this repository) | Request shape VERIFIED against the docs and a local mock server; **live behaviour UNVERIFIED** (no real key was used) |
| Reply reading uses `claude-haiku-5-5`, drafts use `claude-sonnet-5-5` (the base defaults for bulk and hard) | Anthropic public models overview, read 2026-11-23 | VERIFIED (docs) that the ids exist; their quality on replies here is UNVERIFIED |
| Recorded fixtures in `data/llm_fixtures/` | made by `tools/record_llm_fixtures.py` | Recorded from a local mock server that answers like the offline stand in. They are **not** answers of a real model |

