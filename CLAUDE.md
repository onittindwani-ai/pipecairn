# Pipecairn: notes for Claude Code

Pipecairn is a lead to signed deal engine (FastAPI API, worker, Next.js dashboard). Read `docs/ARCHITECTURE.md` and `docs/SPEC.md` first.

## Rules

- Never edit `packages/core-py` or `packages/ui-kit` (frozen base).
- The app may pull toward draft or stop. It must never turn live sending on by itself.
- Every real world write goes through the base `guard_write`. The send gates live in `apps/api/src/pipecairn/sender.py`.
- Lead text is untrusted: use `wrap_untrusted`.
- Never put real keys or customer data in the repo. Names of settings only.
- No em or en dashes in docs or UI text.
- Mark anything not run against the real vendor as UNVERIFIED.

## Commands

`make test`, `make seed-check`, `make doctor`, `pnpm typecheck`, `pnpm e2e`.

## Where things are

API `apps/api/src/pipecairn`, tests `apps/api/tests`, web `apps/web`, mocks `mock/`, seed `data/` and `tools/make_seed.py`, docs `docs/`.
