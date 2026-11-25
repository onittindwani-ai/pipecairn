# Go live checklist

Do not skip items. Tick each one. Going live means real messages reach real people.

## Before

- [ ] `02-BUSINESS-BASICS-CHECK.md` is fully done (separate domains, SPF, DKIM, DMARC, address, texting registration if you text).
- [ ] `DEMO_MODE=false`, a real `OWNER_PASSWORD_HASH`, a long `SESSION_SECRET` (32 or more random characters; the app will not start with `DEMO_MODE=false` and an example value), and a `WEBHOOK_SHARED_SECRET`.
- [ ] `SENDER_NAME`, `COMPANY_NAME` and `COMPANY_ADDRESS` are your real ones. With `MODE=live` the app refuses to start while they are the placeholders. Every email gets a footer with them and an opt out line, added by the program.
- [ ] `make check-env` and then `python tools/doctor.py --live` report no problem and no FAIL.
- [ ] You sent a test email from the mailbox to yourself and the reply came back into Pipecairn.
- [ ] The Integrations page **Test** button passes for every category you switched on, and the Telnyx and Cal.com webhook addresses are set at those services.
- [ ] A sending mailbox is added (Deliverability page, owner only, or `POST /api/mailboxes`) and a sequence exists (Sequences page, "Create a starter sequence", or `POST /api/sequences`). A fresh install has neither, and nothing is sent without both. See `10`.
- [ ] Your unsubscribe list from any older tool is imported FIRST (`POST /api/suppressions`: emails, whole domains or phone numbers, see `10`). Leads already imported from them stop at once.
- [ ] Your existing customers are marked FIRST (`POST /api/customers` with their domains, or an `is_customer` column in the lead CSV), so they are never prospected.
- [ ] Lead list imported (the Leads page, **Import CSV**, or CSV text sent to `POST /api/leads/import`, see `10`). Its reply counts the duplicates merged and the problems found. Open Leads and look at the flags on the rows.
- [ ] Two people know where the kill switch is.

## First day

- [ ] Run in `draft` for a week and read every draft. Approve by hand.
- [ ] Switch to `live` with one mailbox and a low daily cap.
- [ ] Watch Deliverability. If a mailbox is paused for bounces, stop and find out why before resuming.

## Always

- [ ] Reply to real replies the same day.
- [ ] Check the Audit page weekly and press **Verify the chain**.
- [ ] Back up the database (see `11`).
