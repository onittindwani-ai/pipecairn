# Updating

1. Back up the database (`11`).
2. Read `CHANGELOG.md` for what changed.
3. Pull the new code: `git pull`.
4. Reinstall: `make install`, or `.venv/bin/pip install -c constraints.txt -e packages/core-py -e "apps/api[dev]"` (with a uv environment: `uv pip install --python .venv/bin/python -c constraints.txt -e packages/core-py -e "apps/api[dev]"`) and `pnpm install && pnpm build`.
5. Migrate (Postgres): `cd apps/api && ../../.venv/bin/alembic upgrade head`. SQLite needs no step: on start the API and the worker create missing tables and add missing columns (never removing or changing one), so an old `.sqlite3` file keeps working; a change that is more than adding a column is not done for you, so use Postgres for real work. There is no export button: keep the old `.sqlite3` file as your backup (`11`). `alembic` reads `DATABASE_URL` from the environment or from `.env` (or the file named by `ENV_FILE`) and stops when it finds none.
6. Restart the API, worker and web app.
7. Run `python tools/doctor.py` and open the Audit page.

The shared packages in `packages/` (the base) are versioned separately. Do not edit them in a client install; changes belong upstream.

Settings can be added in an update. `.env.example` lists every name (a test fails when a setting is missing from it or from `04`); run `make check-env` to compare it with your `.env`.

## Updating a Docker install

1. Back up first: `deploy/hetzner/backup.sh` (Postgres dump and the signing folders), or at least `docker compose exec -T db pg_dump -U pipecairn -Fc pipecairn > before-update.dump`.
2. In the repository folder: `git pull`, then read `CHANGELOG.md`.
3. `docker compose up -d --build`. This rebuilds the images and restarts the containers. The API runs `alembic upgrade head` itself when it starts on Postgres, so the migrations are applied for you; `docker compose exec api alembic upgrade head` runs them by hand and `docker compose logs api` shows the result. The `.env` file and the `dbdata` and `handoff` volumes are kept.
4. `docker compose ps` should show `db`, `api`, `worker` and `web` as running and healthy. Open the web address, sign in and open the Audit page.
5. To go back: restore the dump (`11`), check out the previous version with `git checkout <tag or commit>`, and run `docker compose up -d --build` again. A migration is not undone by itself, so restore the dump first.

## Pinning the Docker base images

The Dockerfiles name a version tag (`python:3.12-slim`, `node:22-slim`) and the compose file `postgres:17.7`. A tag can move. To fix one image for good, find its digest with `docker buildx imagetools inspect python:3.12-slim` (the line `Digest: sha256:...`) and write `FROM python:3.12-slim@sha256:<digest>`; do the same for the other images and update them on purpose, not by accident. This repository does not pin digests because they go stale and would then quietly stop receiving security updates.

## Pinned packages

`constraints.txt` pins every third party Python package to the version the tests ran against, so an install today gives the same set as the one that was tested (`make install`, the Docker image and CI all use it). After a deliberate upgrade of a package, install the new version, run the tests, then rewrite the file with `tools/make_constraints.py` from the hub repository (`sendora-ai-systems`).
