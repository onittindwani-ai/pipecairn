# What Pipecairn does (with pictures)

All screens show fictional demo data. Desktop and phone versions of each are in `docs/screenshots/`.

## Overview: speed to lead and the funnel
![Overview](screenshots/desktop-01-overview-default.png)

## Pipeline: deals by stage, drag to move
![Pipeline](screenshots/desktop-09-pipeline.png)

## Inbox: replies sorted, with a suggested answer to approve
![Inbox](screenshots/desktop-10-inbox.png)

## Sequences: edit steps and preview exactly what a lead receives
![Sequences](screenshots/desktop-11-sequences.png)

## Lead sheet: everything about one person
![Lead detail](screenshots/desktop-02-detail-lead.png)

## Import: choose a CSV file, check the preview, then import
The Leads page has an Import CSV button. In the dialog, press "Choose a CSV file" (it is a real file input, so the keyboard works) or paste the text. The browser reads the file on your machine, shows the row count, the column count and a preview of the first rows, and warns before you press Import if the file has no data rows or no email column. Nothing is sent until you press Import. Files over 5 MB are refused with a plain message. Tested with a browser test that uploads a small fixture file and finds the new leads in the table.

![Import dialog with a file chosen](screenshots/desktop-17-import-file-chosen.png)

## Proposals: build text, make the PDF, prepare for signature
![Proposals](screenshots/desktop-12-proposals.png)

## Deliverability: a paused mailbox, caps and bounce rates
![Deliverability warning](screenshots/desktop-03-warning-paused-mailbox.png)

## Approvals and audit
![Approvals](screenshots/desktop-14-approvals.png)
![Audit](screenshots/desktop-15-audit.png)

## Integrations: what is selected, what it needs, test button
![Integrations](screenshots/desktop-13-integrations.png)

## States and themes
![Dark](screenshots/desktop-08-dark-overview.png)
![Empty inbox](screenshots/desktop-06-empty-inbox.png)
![Phone overview](screenshots/mobile-01-overview-default.png)

## Capability list (measured)

| Capability | How it was checked |
|---|---|
| Never contacts the 29 planted must not send addresses | `tools/score_seed.py`, 29 of 29, plus 6 randomised property worlds in the test suite |
| Merges 10 duplicate pairs, flags 6 role based, 5 invalid emails, 3 bad time zones, 5 bad phones, 8 customer leads | `tools/score_seed.py` |
| Scores perfect fit leads at 70 or more and poor fit at 30 or less | 12 of 12 each |
| Pauses a bouncing mailbox, honours a mailbox cap | tests and seed check |
| Sorts invented replies | Offline stand in (rules, not a model): **<!--n:reader.set_b_first.strict-->114<!--/n--> of <!--n:reader.set_b_first.total-->170<!--/n--> (<!--n:reader.set_b_first.strict_percent-->67.1<!--/n--> percent) on independent set B**, run once. A live model path exists and is UNVERIFIED. See `REPLY-READER-EVAL.md` |
| Dashboard works on desktop and phone, keyboard, light and dark, reduced motion | <!--n:browser_tests-->40<!--/n--> browser tests; accessibility scan of 10 pages in 2 themes found 0 serious or critical problems |
| 5,000 row table stays smooth | layout shift under 0.1 (desktop) |
