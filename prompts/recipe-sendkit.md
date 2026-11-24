# Recipe: build a SendKit email adapter (not built, not tested)

SendKit's API was not checked while building Pipecairn, so no endpoint is claimed here. Paste this into Claude Code:

> Read apps/api/src/pipecairn/adapters/base.py and adapters/smtp_imap.py. Look up the current SendKit API documentation yourself and tell me the source link. Write an adapter `sendkit` that implements the same email interface, registered as Tier C until it is tested. Write tests against a local mock that you write from the documentation. Every real send must go through `guard_write`. Read the key from `SENDKIT_API_KEY` (add it to config.py and .env.example). Check the base URL with the existing `safe_base_url` guard. Mark everything you could not confirm as UNVERIFIED in docs/FACTS-AND-SOURCES.md. Do not call the real service.
