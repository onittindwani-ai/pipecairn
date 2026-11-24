# Operating and backups

## Daily

- Open Inbox. Approve or reject drafts. Reply to people who want a call.
- Glance at Deliverability. A paused mailbox means more than 5 percent of its last 20 or more sends bounced. Find out why before pressing **Resume** (owner only).

## Weekly

- Audit page, **Verify the chain**. If it says broken, someone or something changed history. Stop and look.
- Look at Approvals for anything stuck.

## Stopping fast

Press **Pause all** (the kill switch). It stops the whole sending tick at once. To stop even if the web app is down, set `KILL_SWITCH=true` and restart the API and worker.

## Backups

- **SQLite:** stop the app, copy the `.sqlite3` file. Or `sqlite3 pipecairn.sqlite3 ".backup backup.sqlite3"` while it runs.
- **Postgres:** `pg_dump --format=custom "$DATABASE_URL_PLAIN" > pipecairn.dump` (use the plain `postgresql://` form of the address). `deploy/hetzner/backup.sh` does this for you.
- Also keep the `HANDOFF_DIR` folder (proposal PDFs).

## Restore (test this once before you need it)

1. Make an empty database.
2. Postgres: `pg_restore --clean --if-exists -d "$DATABASE_URL_PLAIN" pipecairn.dump`. SQLite: put the file back.
3. Start the API. Open Audit, **Verify the chain**.

## Logs

The API and worker log to the console. In Docker: `docker compose logs -f api worker`. Check logs for anything private before you share them.
