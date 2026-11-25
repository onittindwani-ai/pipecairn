# Deploy on a Hetzner server

**Not tested by me: I did not create a Hetzner server.** The files in `deploy/hetzner/` are written from Hetzner's public docs (see `facts/hosting.md`) and checked only for valid YAML and shell syntax. One small server runs everything with Docker Compose and Caddy (which gets a free HTTPS certificate for you).

## Steps

1. In Hetzner Cloud make a server (a small one is enough to start; Ubuntu LTS). Add your SSH key while creating it, since you cannot add it later without a rebuild.
2. Add a firewall allowing only ports 22, 80 and 443.
3. Point two DNS names at the server's address: one for the web app (`app.yourdomain.com`) and one for the API (`api.yourdomain.com`).
4. Optional: paste `deploy/hetzner/cloud-init.yaml` into the "Cloud config" box when creating the server. It installs Docker and Caddy. It holds **no secrets**; do not add any.
5. Log in with SSH. Clone your repository to `/opt/pipecairn`.
6. `cp .env.example .env` and fill it in (see `04`). The Docker path needs these four, or the API will not start:
   - `DEMO_MODE=false`
   - `SESSION_SECRET`: a random value of 32 or more characters, `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`
   - `OWNER_PASSWORD_HASH`: from `python tools/hash_password.py`, in single quotes
   - `POSTGRES_PASSWORD`: letters and digits only, or percent encoded, because it sits inside the database address: `openssl rand -hex 24`

   Also set `SENDER_NAME`, `COMPANY_NAME` and `COMPANY_ADDRESS` before `MODE=live`. Set the two DNS names in `deploy/hetzner/Caddyfile`.
7. `docker compose up -d --build`. The API runs the database migrations itself when it starts; `docker compose exec api alembic upgrade head` is only needed to run them by hand.
8. Copy `deploy/hetzner/Caddyfile` to `/etc/caddy/Caddyfile` and `sudo systemctl reload caddy`.
9. Open the web address and sign in.

## Backups

`deploy/hetzner/backup.sh` writes a compressed Postgres dump to `/var/backups/pipecairn`. It also saves the signing folders. Run it daily with cron: `0 3 * * * /opt/pipecairn/deploy/hetzner/backup.sh` (it works from cron's own folder). Set `BACKUP_COPY_TO` to copy the files to another machine. Also turn on Hetzner server backups. Test a restore (see `11`) before you need it.
