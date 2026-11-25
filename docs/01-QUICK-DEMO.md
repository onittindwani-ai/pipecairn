# Quick demo (about 10 minutes)

You will run the whole product on your own computer with fictional data. Nothing is sent anywhere. No accounts, no keys.

## Before you start

You need: Python 3.12 or newer (or uv), Node 22 or newer, pnpm (`corepack enable` or `npm i -g pnpm`), and Google Chrome (only for the optional automated tests). Check free disk space: you need about 2 GB.

## Steps

1. Open a terminal in the project folder.
2. Make a Python environment and install: `python3.12 -m venv .venv`, then `.venv/bin/pip install -c constraints.txt -e packages/core-py -e "apps/api[dev]"`. No python3.12 on your Mac? Use uv instead: `uv venv --python 3.12 .venv`, then `uv pip install --python .venv/bin/python -c constraints.txt -e packages/core-py -e "apps/api[dev]"`. Or just run `make install`.
3. Install the web part: `pnpm install`, then `pnpm build`.
4. Start the API in demo mode. In one terminal run:
   `MODE=live DEMO_MODE=true DATABASE_URL=sqlite:///./demo.sqlite3 SESSION_SECRET=demo-secret-not-for-real-use-1234 .venv/bin/python -m uvicorn pipecairn.api.app:app_from_env --factory --port 8000 --proxy-headers`
   (Demo mode only builds fake adapters, so MODE=live here still cannot send anything.)
5. Start the web app in a second terminal: `API_BASE_URL=http://127.0.0.1:8000 INSECURE_COOKIES=1 NEXT_PUBLIC_DEMO_HINT=1 pnpm --filter web start`.
6. Open http://localhost:3000. Sign in with `owner@example.test` and the demo password `demo-password-1`. This password works only while `DEMO_MODE=true`.
7. Press Cmd+K (Ctrl+K on Windows or Linux) to open the command palette, choose **Reset the demo data**, and confirm. This loads 41 fictional companies and 113 unique leads.
8. In the blue demo strip press **Run now**, then **+1 day**, then **Run now** again, a few times. Replies from fictional people arrive.
9. Open **Inbox**, pick an interested reply, and press **Approve and send**. In demo mode it goes to the fake outbox.
10. Open **Proposals**, make one for that lead, save it, open the PDF, then press **Prepare for signature**. A folder appears for you to upload by hand.
11. Open **Audit** and press **Verify the chain**. It should say the log is intact.
12. Try the kill switch: press **Pause all**. Everything stops. Press **Turn it off** to resume.

## What to look at

- **Deliverability** shows one mailbox that is at its daily cap and one that was paused for bouncing.
- **Leads** has 29 addresses that must never get a message (invalid, role based, unsubscribed, customers). Run `python tools/score_seed.py` to see that none got one.

## If something fails

See `15-TROUBLESHOOTING.md`.
