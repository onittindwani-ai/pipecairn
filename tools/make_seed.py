"""Build the seed data, the reply test set and the answer key. Deterministic: same output every run.

Everything is sample data. Domains end in example.test. Run: python tools/make_seed.py
The answer key lists every planted problem, so tools/score_seed.py can check the system found them all.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data"
R = random.Random(2027)

FIRST = ["Ava", "Noah", "Mia", "Liam", "Zoe", "Ethan", "Ivy", "Lucas", "Nora", "Owen", "Ruby", "Jude", "Cleo", "Theo", "Maya", "Finn", "Lena", "Hugo", "Aria", "Kai", "Sana", "Omar", "Priya", "Diego", "Yuki", "Tariq", "Elena", "Marco", "Nadia", "Sven"]
LAST = ["Alder", "Brook", "Calder", "Dunn", "Ellis", "Frost", "Grant", "Hale", "Irwin", "Joyce", "Kerr", "Lowe", "Marsh", "Nash", "Orr", "Pike", "Quill", "Reeve", "Stone", "Thorn", "Upton", "Vale", "Wynn", "Yates", "Zane", "Boyd", "Cross", "Dale", "Fox", "Glenn"]
WORDS = ["Harbor", "Pine", "Summit", "Maple", "Copper", "River", "Lantern", "Orchard", "Bright", "Granite", "Willow", "Anchor", "Cedar", "Delta", "Ember", "Fable", "Garnet", "Hollow", "Indigo", "Juniper"]
KIND = ["Dental", "Plumbing", "Legal", "Realty", "Roofing", "Studio", "Clinic", "Logistics", "Accounting", "Design", "Fitness", "Solar"]
TARGET_INDUSTRIES = ["home services", "dental", "legal", "real estate", "accounting"]
OTHER_INDUSTRIES = ["fitness", "design", "logistics", "solar", "retail"]
KIND_TO_IND = {"Dental": "dental", "Plumbing": "home services", "Legal": "legal", "Realty": "real estate", "Roofing": "home services", "Studio": "design", "Clinic": "dental", "Logistics": "logistics", "Accounting": "accounting", "Design": "design", "Fitness": "fitness", "Solar": "solar"}
TITLES = {
    "top": ["Founder", "Owner", "CEO", "Managing Partner"],
    "head": ["Head of Growth", "VP Sales", "Director of Operations", "Director of Marketing"],
    "mgr": ["Office Manager", "Marketing Manager", "Sales Manager"],
    "low": ["Coordinator", "Assistant", "Associate"],
    "none": ["Intern", "Student"],
}
TZ_US = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"]
TZ_OTHER = ["Europe/London", "Europe/Berlin", "Asia/Kolkata", "Australia/Sydney"]
SOURCES = ["referral", "form", "csv_list", "scraped"]


def slug(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())


def make_companies(n: int = 40) -> list[dict]:
    out, used = [], set()
    while len(out) < n:
        name = f"{R.choice(WORDS)} {R.choice(KIND)}"
        if name in used:
            continue
        used.add(name)
        kind = name.split()[1]
        size = R.choice([1, 3, 6, 12, 25, 40, 80, 150, 300, 700, 1500])
        out.append({"name": name, "domain": f"{slug(name)}.example.test", "industry": KIND_TO_IND[kind], "size": size, "country": "US", "is_customer": False})
    return out


def lead(c: dict, i: int, title_band: str | None = None, source: str | None = None) -> dict:
    first, last = R.choice(FIRST), R.choice(LAST)
    band = title_band or R.choices(["top", "head", "mgr", "low", "none"], [3, 3, 3, 2, 1])[0]
    tz = R.choice(TZ_US) if R.random() < 0.8 else R.choice(TZ_OTHER)
    phone = f"+1415555{1000 + i:04d}"
    return {
        "first_name": first, "last_name": last, "email": f"{first.lower()}.{last.lower()}{i}@{c['domain']}", "phone": phone,
        "title": R.choice(TITLES[band]), "company": c["name"], "domain": c["domain"], "timezone": tz,
        "source": source or R.choice(SOURCES), "sms_consent": False,
    }


def main() -> None:
    companies = make_companies()
    # fixed planted groups first so the key is exact
    customers = companies[:4]
    for c in customers:
        c["is_customer"] = True
    leads: list[dict] = []
    idx = 0

    def add(c: dict, **kw) -> dict:
        nonlocal idx
        idx += 1
        l = lead(c, idx, **kw)
        leads.append(l)
        return l

    # 12 perfect fit and 12 poor fit leads (score bands in the key)
    target_cos = [c for c in companies[4:] if c["industry"] in TARGET_INDUSTRIES and 11 <= c["size"] <= 200]
    perfect = []
    for k in range(12):
        c = target_cos[k % len(target_cos)]
        l = add(c, title_band="top", source="referral")
        perfect.append(l["email"])
    poor_co = {"name": "Solo Retail Cart", "domain": "soloretailcart.example.test", "industry": "retail", "size": 1, "country": "US", "is_customer": False}
    companies.append(poor_co)
    poor = []
    for k in range(12):
        l = add(poor_co, title_band="none", source="scraped")
        l["email"] = f"intern{k}.cart@gmail.example.test"
        poor.append(l["email"])
    # leads at customer companies (do not contact)
    customer_leads = [add(customers[k % 4])["email"] for k in range(8)]
    # filler
    for _ in range(70):
        add(R.choice(companies[4:]))
    # sms consent for 20 leads
    for l in R.sample(leads, 20):
        l["sms_consent"] = True

    answer: dict = {}
    # duplicates: 10 pairs, second copy has different case and spaces
    dup_pairs = []
    for l in R.sample([x for x in leads if x["email"] not in poor], 10):
        copy = dict(l)
        copy["email"] = " " + l["email"].upper() + " "
        copy["source"] = "csv_list"
        leads.append(copy)
        dup_pairs.append([l["email"], l["email"]])
    # role based
    role_based = []
    for k, c in enumerate(R.sample(companies[4:], 6)):
        l = add(c)
        l["email"] = f"{['info', 'sales', 'admin', 'office', 'support', 'hello'][k]}@{c['domain']}"
        role_based.append(l["email"])
    # invalid syntax or domain
    invalid_email = []
    for bad in ["no-at-sign.example.test", "double@@bad.example.test", "spaces in@bad.example.test", "missingtld@localhost", "trailingdot@bad.example.test."]:
        l = add(R.choice(companies[4:]))
        l["email"] = bad
        invalid_email.append(bad)
    # invalid timezone
    bad_tz = []
    for l in R.sample([x for x in leads if x["email"] == x["email"].strip().lower() and x["email"] not in poor and x["email"] not in perfect], 3):
        l["timezone"] = "Mars/Olympus"
        bad_tz.append(l["email"].strip().lower())
    # invalid phone for sms (consenting leads only)
    bad_phone = []
    for l in [x for x in leads if x["sms_consent"] and x["email"] == x["email"].strip().lower()][:5]:
        l["phone"] = "555-0100"
        bad_phone.append(l["email"].strip().lower())

    # suppression list: 8 emails, 2 domains (domain suppression is a whole company)
    plain = [x for x in leads if x["email"] == x["email"].strip().lower() and x["email"] not in poor and x["email"] not in perfect and x["email"] not in customer_leads and x["email"] not in role_based and x["email"] not in invalid_email and x["email"] not in bad_tz]
    sup_emails = [x["email"] for x in R.sample(plain, 8)]
    sup_domains = []
    for c in R.sample([c for c in companies[4:] if c["domain"] not in {x["domain"] for x in leads if x["email"] in perfect}], 2):
        sup_domains.append(c["domain"])
    suppressions = (
        [{"kind": "email", "value": e, "reason": "unsubscribed earlier", "source": "import"} for e in sup_emails]
        + [{"kind": "domain", "value": d, "reason": "asked not to be contacted", "source": "import"} for d in sup_domains]
    )

    mailboxes = [
        {"address": "alex@mail.pipecairn-demo.example.test", "provider": "smtp_imap", "daily_cap": 40, "sent_today": 0, "bounce_count": 0, "sent_total": 220, "warmup_days": 45, "spf_ok": True, "dkim_ok": True, "dmarc_ok": True},
        {"address": "sam@mail.pipecairn-demo.example.test", "provider": "smtp_imap", "daily_cap": 40, "sent_today": 0, "bounce_count": 1, "sent_total": 180, "warmup_days": 38, "spf_ok": True, "dkim_ok": True, "dmarc_ok": True},
        {"address": "jo@send.pipecairn-demo.example.test", "provider": "smtp_imap", "daily_cap": 5, "sent_today": 5, "bounce_count": 0, "sent_total": 40, "warmup_days": 9, "spf_ok": True, "dkim_ok": True, "dmarc_ok": False},
        {"address": "kit@reach.pipecairn-demo.example.test", "provider": "smtp_imap", "daily_cap": 30, "sent_today": 0, "bounce_count": 14, "sent_total": 100, "warmup_days": 20, "spf_ok": True, "dkim_ok": False, "dmarc_ok": True},
    ]
    sequence = {
        "name": "First touch and follow up",
        "steps": [
            {"channel": "email", "delay_hours": 0, "subject": "Quick idea for {{company}}", "body": "Hi {{first_name}},\n\nI help {{industry}} teams answer new enquiries within minutes. Would a short call this week be useful?\n\nBest,\nAlex"},
            {"channel": "email", "delay_hours": 72, "subject": "Re: Quick idea for {{company}}", "body": "Hi {{first_name}}, a short follow up in case my first note got buried. Happy to send a two line summary instead of a call."},
            {"channel": "sms", "delay_hours": 24, "subject": "", "body": "Hi {{first_name}}, Alex here. Sent you an email about faster replies for {{company}}. Reply STOP to opt out."},
            {"channel": "email", "delay_hours": 96, "subject": "Should I close your file?", "body": "Hi {{first_name}}, I will stop writing after this one. If timing is wrong, tell me when to check back."},
        ],
    }
    # scripted demo replies: one per intent, attached to filler leads that are not planted problems
    safe = [x for x in plain if x["email"] not in sup_emails and x["domain"] not in sup_domains and x["sms_consent"] is False and x["timezone"] != "Mars/Olympus"]
    script_intents = [
        ("interested", "Yes, this sounds useful. Can we talk Thursday afternoon?"),
        ("question", "What does this cost, and does it work with our current phone system?"),
        ("not_now", "Not now, we are in the middle of a move. Try me again in January."),
        ("wrong_person", "I do not handle this. You want our office manager, Dana Reed."),
        ("unsubscribe", "Please remove me from your list."),
        ("out_of_office", "I am out of the office until the 14th with limited email access."),
        ("bounce", "Delivery Status Notification (Failure). The address was not found. 550 5.1.1 User unknown."),
        ("interested", "Send me a proposal please, budget is approved."),
        ("question", "Do you have any examples from dental practices?"),
        ("not_now", "Maybe next quarter, send me a note then."),
    ]
    inbound_script = []
    pool = [x for x in safe if x["email"] not in perfect]
    for (intent, text), l in zip(script_intents, R.sample(pool, len(script_intents))):
        inbound_script.append({"email": l["email"], "intent": intent, "text": text, "after_hours": 30})

    # clean emails in the raw data keep their stray spaces for the duplicates only
    must_not_send = sorted(
        {e.strip().lower() for e in sup_emails + role_based + invalid_email + customer_leads}
        | {x["email"].strip().lower() for x in leads if x["domain"] in sup_domains}
        | set(bad_tz)
    )
    n_dup_groups = len(dup_pairs)
    answer = {
        "duplicate_emails": sorted({p[0] for p in dup_pairs}),
        "duplicate_group_count": n_dup_groups,
        "role_based": sorted(role_based),
        "invalid_email": sorted(invalid_email),
        "suppressed_emails": sorted(sup_emails),
        "suppressed_domains": sorted(sup_domains),
        "customer_leads": sorted(customer_leads),
        "invalid_timezone": sorted(bad_tz),
        "invalid_sms_phone": sorted(bad_phone),
        "perfect_fit_min_score": 70,
        "perfect_fit": sorted(perfect),
        "poor_fit_max_score": 30,
        "poor_fit": sorted(poor),
        "must_not_send": must_not_send,
        "mailbox_over_cap": "jo@send.pipecairn-demo.example.test",
        "mailbox_high_bounce": "kit@reach.pipecairn-demo.example.test",
        "scripted_reply_intents": [i for i, _ in script_intents],
    }
    seed = {"companies": companies, "leads": leads, "mailboxes": mailboxes, "suppressions": suppressions, "sequence": sequence, "inbound_script": inbound_script}
    OUT.mkdir(exist_ok=True)
    (OUT / "seed.json").write_text(json.dumps(seed, indent=1) + "\n")
    (OUT / "answer_key.json").write_text(json.dumps(answer, indent=1) + "\n")
    counts = {
        "companies": len(companies), "lead_rows": len(leads), "unique_leads_expected": len(leads) - n_dup_groups,
        "duplicate_groups": n_dup_groups, "role_based": len(role_based), "invalid_email": len(invalid_email),
        "suppressed_emails": len(sup_emails), "suppressed_domains": len(sup_domains), "customer_leads": len(customer_leads),
        "invalid_timezone": len(bad_tz), "invalid_sms_phone": len(bad_phone), "mailboxes": len(mailboxes),
        "must_not_send": len(must_not_send), "scripted_replies": len(inbound_script),
    }
    (OUT / "counts.json").write_text(json.dumps(counts, indent=1) + "\n")
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main()
