# Troubleshooting

Run `make check-env` first (it lists missing or half filled settings, names only), then `python tools/doctor.py` (it tests each service you set up). Both name the problem in plain words.

| What you see | Likely cause | Fix |
|---|---|---|
| Sign in says wrong email or password | Demo password used with `DEMO_MODE=false`, or hash pasted without quotes | Use your own password. Put `OWNER_PASSWORD_HASH='...'` in single quotes. |
| Everything says 401 after a restart | `SESSION_SECRET` changed | Sign in again. |
| 429 too many requests | Behind a proxy without `--proxy-headers` | Start uvicorn with `--proxy-headers` and set `FORWARDED_ALLOW_IPS=<proxy address>` (the Docker image reads that variable). |
| Nothing sends | Draft mode, kill switch, quiet hours, weekend, or mailbox at cap | Check the top strip, then Deliverability. Quiet hours are 18:00 to 08:00 local to the lead. |
| A lead never gets messages | Flags (invalid, role based, customer, unsubscribed) or no time zone | Open the lead sheet. |
| Mailbox paused | Over 5 percent bounces, counted over at least 20 sends (from the last resume, if there was one). A mail server that says an address does not exist also counts as a bounce; a policy or relay refusal does not. | Fix the list, then **Resume** (owner). The rate starts again from the resume. |
| A lead shows "A message may not have been sent" | The worker stopped, or the connection broke, while the message was being handed to the mail server | Look in the Sent folder. If it is not there, press the button on the lead. It is never resent on its own. |
| A lead was stopped with the reason `send_failed_repeatedly` | The mail server refused the message three times | The lead's timeline says so. Check the address and the mailbox (Deliverability). The sequence does not write to that person again by itself; write to them by hand if it matters. |
| A lead was stopped with the reason `possible_stop`, `unverified_bounce` or `possible_auto_reply` | A reply had wording that might be a stop request, a bounce or an automatic reply, but not a complete or proven one | Nothing was suppressed. Open the reply in the Inbox, read it, then answer, press **Never contact this person again**, or **Mark as read**. |
| A lead was stopped with the reason `send_error` | Preparing its next step raised an error three times in a row (a broken template, a bad row) | The lead's timeline says what happened. Fix the step or the lead; the other people in the batch were not affected. |
| Someone was suppressed by mistake | A reply was read as a stop request | Owner: open the reply in the Inbox and press **Lift the stop (owner)**. They are not put back in a sequence on their own. |
| Replies do not appear in the Inbox | The inbox is not the one in `IMAP_HOST`, the sender is not a lead, or it is a personal inbox | Mail that is not from a lead is left alone unless `KEEP_UNMATCHED_MAIL=true`. Use a mailbox just for this system. |
| Doctor says FAIL for an adapter | Missing variable or wrong host | It names the variable. |
| Webhook rejected | Wrong secret or old timestamp | Check the secret; check the server clock. |
| "database is locked" on SQLite | Two heavy writers | Use Postgres. |
| Alembic error on Postgres | Wrong URL form, or `DATABASE_URL` set nowhere | Use `postgresql+psycopg://`. Alembic reads the environment or `.env` and stops with a message when it finds none. |
| The API will not start: "settings are not safe" | `DEMO_MODE=false` with an example `SESSION_SECRET`, `DEMO_MODE=true` on Postgres, or `MODE=live` with the placeholder `SENDER_NAME`, `COMPANY_NAME` or `COMPANY_ADDRESS` | The message names the setting. Fix it and start again. |
| No mailbox or sequence in a new install | A real install starts empty | Deliverability, **Add a sending mailbox**; Sequences, **Create a starter sequence** (owner). See `10`. |
| Web build cannot find the ui kit | Vercel root settings | See `06` step 4. |
| Page looks unstyled | Web not built | `pnpm build` then start again. |
| Demo shows no replies | Clock not moved | Press **Run now**, **+1 day**, **Run now** a few times. |

Still stuck: open an issue (see `CONTRIBUTING.md`) with the doctor output. Never paste real keys.
