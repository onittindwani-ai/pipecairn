# Using it for a client

You run Pipecairn for someone else's business. Keep each client in their own copy.

## Rules that keep you safe

1. **One install per client.** Own database, own settings, own mailboxes, own domains. Never mix two clients' leads in one database.
2. **Their accounts, their names.** The client creates and owns the email, texting, calendar and CRM accounts. You get access, not ownership. The texting carrier registration is in the client's business name.
3. **Their consent.** Only import lists the client has the right to contact. You are not a source of leads in this system.
4. **Two logins.** The client owner is the owner. If you need to approve work for them, use the approver login so you cannot change settings, edit the sequences or import leads.
5. **Start in draft.** Run a week of drafts with the client reading them.

## Setting up

1. Do `02` with the client.
2. Set up the install (`05` to `08`). Use the client's name in `OWNER_EMAIL`, and the client's real `SENDER_NAME`, `COMPANY_NAME` and `COMPANY_ADDRESS` (they go in every footer).
3. Add the sending mailbox: Deliverability page, **Add a sending mailbox** (owner only). A real install starts with none. One mail account (`SMTP_USER`) signs in for every mailbox, so add only that address, or addresses it may send as. To use two separate accounts, run two installs.
4. Create the sequence: Sequences page, **Create a starter sequence**, then edit it. Write `{{sender_name}}` where the name goes. The preview shows a step exactly as one real lead would receive it. The footer (company, address, "Reply STOP") is added for you; do not type it into the steps.
5. Before the leads, load the people who must never be written to. Customers: `curl -X POST https://api.theirdomain.com/api/customers -H "x-session: $TOKEN" -H "content-type: application/json" -d '{"values": ["theirclient.com", "other@customer.com"]}'` (domains or email addresses, or `{"csv": "domain\nclient.com\n"}`). Do not contact list from an old tool: `.../api/suppressions` with `{"values": ["a@b.com", "badcompany.com", "+15555550123"]}` or `{"csv": "email\na@b.com\n"}` (a `kind` column of email, domain or phone is optional; without it the kind is guessed). Both also stop leads already imported from them.
6. Import their leads. The easy way: open the Leads page, press **Import CSV**, then **Choose a CSV file**. You see the row count and the first rows before anything is sent, then press **Import**. The same steps by API: sign in to the API to get a token, then send the CSV text (this was run against a fresh copy of the repo):
   `TOKEN=$(curl -s -H "content-type: application/json" -d '{"email":"you@theirdomain.com","password":"..."}' https://api.theirdomain.com/api/auth/login | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")`
   `curl -X POST https://api.theirdomain.com/api/leads/import -H "x-session: $TOKEN" -H "content-type: application/json" -d '{"csv": "email,first_name,company,timezone\nnia@example.com,Nia,Example Co,America/New_York\n"}'`
   Columns: `first_name`, `last_name`, `email`, `phone`, `title`, `company`, `domain`, `timezone`, `source`, `sms_consent`, `industry`, `size`, `country`, `is_customer`. Only `email` is required. Fill `industry` and `size` too: the score uses them (without them a lead cannot score above 55, and `{{industry}}` in a template would be empty). `is_customer` set to `yes` marks that company as a customer. **A lead with no valid `timezone` (like America/New_York) is flagged and never sent to**, because quiet hours cannot be checked, unless you set `DEFAULT_TIMEZONE`. The reply tells you how many rows, how many were created, duplicates and flags.
7. Press **Process** or wait for the worker. Look at the flags on the Leads page.

## What to charge for

This guide gives no price figures. It gives the shape of the offer, so you can price it yourself after looking at your market and your costs.

- **Setup, once.** Business basics check (`02`), accounts and domains, install and hosting, sequence writing, list cleaning, a week in draft mode with the client reading every message. Charge for the hours and the care, not for the software, which is free.
- **Running it, monthly.** Watching deliverability, reading the Approvals page on the days it needs a person, tuning sequences, a short report. State plainly how many hours a month that includes.
- **Costs that pass through, at cost.** Hosting, the sending mailboxes and domains, the texting number and carrier fees, the calendar and CRM seats, and any model usage. Show the client these as their own accounts, not as your markup.
- **Never charge for** a promised number of meetings or deals. This system drafts, sends within safety limits and reads replies. It cannot promise results, and the demo numbers come from sample data.

## Onboarding checklist

1. Business basics check (`02`) signed off by the client.
2. Client created their own email, texting, calendar and CRM accounts and gave you access.
3. Outreach domains bought in the client's name, with sender checks passing (`02`).
4. Install running with its own database, backups on (`11`), `make doctor` clean.
5. Their lead list imported, flags read, existing customers and anyone who asked not to be contacted marked.
6. Sequence written with the client and previewed on a real lead.
7. One week in draft mode, the client reads the drafts and says yes or no.
8. Switch to live for a few leads a day, then raise the daily limit slowly.

## Handover

When you finish or the client takes it over: give them the owner login, the list of every account and who owns it, the location of the backups and the restore steps (`11`), and the sequences and templates (copy them from the Sequences page). There is no export button: the audit log and the data are in the database, so hand over a database backup if they want a copy. Ask them to change every password and key while you watch, then remove your access. Keep nothing of theirs on your machines.

## What to put in the client contract

Plain wording, checked by your own lawyer: what is included in setup and in the monthly work; that costs of third party accounts are the client's; that the client owns the data, the accounts and the domains; that the client confirms they have the right to contact every person on their lists; that no results are promised; who answers if a message goes wrong, and how fast; how either side ends the work and what happens to the data afterwards. This is not legal advice.

## Reporting

The Overview page shows the speed to lead ring and the funnel. Numbers there are counts from the database, not promises. Do not quote results to a client from the demo data; it is sample data.

## When the client leaves

Give them a database backup (`11`), delete their install and database, and revoke every key they gave you. See `13` for what personal data means here.
