# Docker

`docker-compose.yml` at the repository root starts Postgres, the API, the worker and the web app. Follow `docs/08-DEPLOY-HETZNER.md` (it uses this file). Ports are bound to 127.0.0.1, so put a reverse proxy (Caddy, see `deploy/hetzner/Caddyfile`) in front for HTTPS.

Status: the compose file passes `docker compose config` and YAML parsing. The GitHub CI workflow builds both images and starts the whole stack (database, API, worker, web) and checks that the API and the web app answer. No deploy to a real host was done. The `.env` must have `DEMO_MODE=false`, a real `SESSION_SECRET`, `OWNER_PASSWORD_HASH` and a `POSTGRES_PASSWORD` of letters and digits (`openssl rand -hex 24`); see `docs/04` and `docs/08`.
