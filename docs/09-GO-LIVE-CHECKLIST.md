# Go live checklist

Do not skip items. Tick each one. Going live means real messages reach real people.

## Before

- [ ] `02-BUSINESS-BASICS-CHECK.md` is fully done (separate domains, SPF, DKIM, DMARC, address, texting registration if you text).
- [ ] `DEMO_MODE=false`, a real `OWNER_PASSWORD_HASH`, a long `SESSION_SECRET`, and a `WEBHOOK_SHARED_SECRET`.
- [ ] `python tools/doctor.py --live` reports no FAIL.
- [ ] You sent a test email from the mailbox to yourself and the reply came back into Pipecairn.
- [ ] The Integrations page **Test** button passes for every category you switched on, and the Telnyx and Cal.com webhook addresses are set at those services.
- [ ] Lead list imported (CSV text sent to `POST /api/leads/import`, see `10`). Its reply counts the duplicates merged and the problems found. Open Leads and look at the flags on the rows.
- [ ] Your existing customers are marked, or imported as customers, so they are never prospected.
- [ ] Your unsubscribe list from any older tool is imported (Leads, "Never contact").
- [ ] Two people know where the kill switch is.

## First day

- [ ] Run in `draft` for a week and read every draft. Approve by hand.
- [ ] Switch to `live` with one mailbox and a low daily cap.
- [ ] Watch Deliverability. If a mailbox is paused for bounces, stop and find out why before resuming.

## Always

- [ ] Reply to real replies the same day.
- [ ] Check the Audit page weekly and press **Verify the chain**.
- [ ] Back up the database (see `11`).
