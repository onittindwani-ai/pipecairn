# Operating and backups

## Daily

- Open Inbox. Approve or reject drafts. Reply to people who want a call. A reply that was approved but did not go out (the daily limit was reached, it was outside sending hours, the mail server failed) stays open: press **Approve and send** again, or **Reject** it.
- Also in the Inbox: mail from addresses that are not leads (an alias, a forward, a colleague) and bounce notices that could not be verified. Read them and press **Mark as read**. Nothing is dropped.
- Glance at Deliverability. A paused mailbox means more than 5 percent of its last 20 or more sends bounced. Find out why before pressing **Resume** (owner only).

## Weekly

- Audit page, **Verify the chain**. If it says broken, someone or something changed history. Stop and look.
- Look at Approvals for anything stuck.

## Stopping fast

Press **Pause all** (the kill switch). It stops the whole sending tick at once, also one that is already part way through a batch: the switch is read again before every send. To stop even if the web app is down, set `KILL_SWITCH=true` and restart the API and worker.

## If the worker was killed while sending

Every send is recorded the moment it starts and kept when it finishes, one message at a time. If the worker is killed in the middle, the message that was being sent is marked **unconfirmed** (see the lead's message list, or `status = 'unconfirmed'` in `cl_message`). It is never sent a second time on its own: the mail server may or may not have sent it, and a second copy to a real person is worse than a missing one. Look in the mailbox's Sent folder, and write to that person by hand if it did not go.

## Backups

- **SQLite:** stop the app, copy the `.sqlite3` file. Or `sqlite3 pipecairn.sqlite3 ".backup backup.sqlite3"` while it runs.
- **Postgres, Docker:** `deploy/hetzner/backup.sh` does it for you. It can run from cron (it moves to the repository folder itself), writes the dump to a partial file and keeps it only when it is not empty, also saves the `handoff` folder as a tar file, keeps the newest 14 of each, and with `BACKUP_COPY_TO=user@host:/path/` copies them to another machine with rsync. A copy on the same disk is not a backup: set it, or copy the folder off the server another way.
- **Postgres, your own server:** `pg_dump --format=custom "postgresql://USER:PASSWORD@HOST:5432/pipecairn" > pipecairn.dump` (the plain `postgresql://` form of `DATABASE_URL`, without `+psycopg`).
- Also keep the `HANDOFF_DIR` folder (the signing folders). In Docker that is the `handoff` volume; `backup.sh` saves it.

## Restore (test this once before you need it)

1. Make an empty database.
2. Postgres: `pg_restore --clean --if-exists -d "postgresql://USER:PASSWORD@HOST:5432/pipecairn" pipecairn.dump`. In Docker: `docker compose exec -T db pg_restore --clean --if-exists -U pipecairn -d pipecairn < pipecairn-DATE.dump`. SQLite: put the file back. Restore into a spare database first and look at it; a restore that was never tried is a hope, not a backup.
3. Start the API. Open Audit, **Verify the chain**.

## Logs

The API and worker log to the console. In Docker: `docker compose logs -f api worker`. Check logs for anything private before you share them.
