# Troubleshooting

Run `make check-env` first (it lists missing or half filled settings, names only), then `python tools/doctor.py` (it tests each service you set up). Both name the problem in plain words.

| What you see | Likely cause | Fix |
|---|---|---|
| Sign in says wrong email or password | Demo password used with `DEMO_MODE=false`, or hash pasted without quotes | Use your own password. Put `OWNER_PASSWORD_HASH='...'` in single quotes. |
| Everything says 401 after a restart | `SESSION_SECRET` changed | Sign in again. |
| 429 too many requests | Behind a proxy without `--proxy-headers` | Start uvicorn with `--proxy-headers --forwarded-allow-ips <proxy address>`. |
| Nothing sends | Draft mode, kill switch, quiet hours, weekend, or mailbox at cap | Check the top strip, then Deliverability. Quiet hours are 18:00 to 08:00 local to the lead. |
| A lead never gets messages | Flags (invalid, role based, customer, unsubscribed) or no time zone | Open the lead sheet. |
| Mailbox paused | Over 5 percent bounces in the last 20 or more sends | Fix the list, then **Resume** (owner). |
| Doctor says FAIL for an adapter | Missing variable or wrong host | It names the variable. |
| Webhook rejected | Wrong secret or old timestamp | Check the secret; check the server clock. |
| "database is locked" on SQLite | Two heavy writers | Use Postgres. |
| Alembic error on Postgres | Wrong URL form | Use `postgresql+psycopg://`. |
| Web build cannot find the ui kit | Vercel root settings | See `06` step 4. |
| Page looks unstyled | Web not built | `pnpm build` then start again. |
| Demo shows no replies | Clock not moved | Press **Run now**, **+1 day**, **Run now** a few times. |

Still stuck: open an issue (see `CONTRIBUTING.md`) with the doctor output. Never paste real keys.
