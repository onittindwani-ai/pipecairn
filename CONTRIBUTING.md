# Contributing

1. Fork, branch, make a small change.
2. Run `make test` and `make seed-check`. Both must pass. For web changes also `pnpm typecheck` and `pnpm e2e`.
3. Do not edit `packages/core-py` or `packages/ui-kit`; they are a frozen shared base.
4. Use plain words in docs and UI text. No em or en dashes.
5. Commit messages: `type: what the change delivers`, for example `fix: stop a role based address from being scored`.
6. Never commit keys, real customer data or `.env`.

Issues: describe what you did, what you expected and what happened. Paste `python tools/doctor.py` output (it prints no secrets).
