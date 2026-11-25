# Updating

1. Back up the database (`11`).
2. Read `CHANGELOG.md` for what changed.
3. Pull the new code: `git pull`.
4. Reinstall: `make install`, or `.venv/bin/pip install -c constraints.txt -e packages/core-py -e "apps/api[dev]"` (with a uv environment: `uv pip install --python .venv/bin/python -c constraints.txt -e packages/core-py -e "apps/api[dev]"`) and `pnpm install && pnpm build`.
5. Migrate (Postgres): `cd apps/api && ../../.venv/bin/alembic upgrade head`. SQLite creates missing tables on start but does not change old ones, so for SQLite across a schema change use Postgres. There is no export button: keep the old `.sqlite3` file as your backup (`11`). `alembic` reads `DATABASE_URL` from the environment or from `.env` (or the file named by `ENV_FILE`) and stops when it finds none.
6. Restart the API, worker and web app.
7. Run `python tools/doctor.py` and open the Audit page.

The shared packages in `packages/` (the base) are versioned separately. Do not edit them in a client install; changes belong upstream.

Settings can be added in an update. `.env.example` lists every name (a test fails when a setting is missing from it or from `04`); run `make check-env` to compare it with your `.env`.

## Pinning the Docker base images

The Dockerfiles name a version tag (`python:3.12-slim`, `node:22-slim`) and the compose file `postgres:17.7`. A tag can move. To fix one image for good, find its digest with `docker buildx imagetools inspect python:3.12-slim` (the line `Digest: sha256:...`) and write `FROM python:3.12-slim@sha256:<digest>`; do the same for the other images and update them on purpose, not by accident. This repository does not pin digests because they go stale and would then quietly stop receiving security updates.

## Pinned packages

`constraints.txt` pins every third party Python package to the version the tests ran against, so an install today gives the same set as the one that was tested (`make install`, the Docker image and CI all use it). After a deliberate upgrade of a package, install the new version, run the tests, then rewrite the file with `tools/make_constraints.py` from the hub repository (`sendora-ai-systems`).
