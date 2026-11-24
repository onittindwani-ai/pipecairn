"""Write data/reply_heldout2.json: a SECOND small set, written 2026-11-23 AFTER the rules were tuned on the first held out set.

It shows how the tuned rules do on fresh wording. It is only partly held out: its author had read the tuned rules. Every sender is invented.
Run: python tools/make_reply_heldout2.py
"""

from __future__ import annotations

import json
from pathlib import Path

CASES: list[tuple[str, str]] = [
    ("interested", "Looks promising. Can you ring me tomorrow around 10?"),
    ("interested", "My team is keen. What is the quickest way to get a walkthrough?"),
    ("interested", "ok send the link to pick a time, we are in"),
    ("interested", "Right, I read it twice. Let's get 30 minutes in the diary before the end of the month."),
    ("interested", "Saw your note this morning, seems relevant to the missed calls we keep having. Free Monday if that helps."),
    ("interested", "Yes to a first chat. Bring prices."),
    ("question", "Does the text part need any special phone number registration on our side?"),
    ("question", "Roughly how much of my time does this take each week once it's running?"),
    ("question", "Hi there, is this tied to one email provider or can I use my own domain?"),
    ("question", "What languages does the reply reading handle?"),
    ("question", "Are the replies sent automatically or does someone check them first"),
    ("question", "Is there a minimum contract length?"),
    ("not_now", "Honestly we can't deal with new software before our year end close, try me in February."),
    ("not_now", "We are re-organising the whole team this quarter. Better to speak once that is done."),
    ("not_now", "Thanks but we are not changing anything before the summer season is over."),
    ("not_now", "Ask me again once our new website is live, probably early next year."),
    ("not_now", "Currently paused on all new projects. Happy to hear from you in six months."),
    ("not_now", "We already have something in place this year; check in with me in 2027."),
    ("wrong_person", "I think you should reach out to Elena in finance for this, not to me."),
    ("wrong_person", "Sorry, we have a separate IT team for that. I will pass your details along."),
    ("wrong_person", "I'm a part time assistant, I don't decide on any of this."),
    ("wrong_person", "Please contact the owner, Mr Hale. He reads all vendor mail personally."),
    ("wrong_person", "Hello, I moved to a different department last spring so this is not my remit any more."),
    ("wrong_person", "Not mine. Speak to Chris."),
    ("unsubscribe", "Enough. Take me out of your database."),
    ("unsubscribe", "I never signed up for this. Please wipe my email from your records."),
    ("unsubscribe", "No further contact, thank you."),
    ("unsubscribe", "pls dont send me anything else"),
    ("unsubscribe", "Remove this email from your outreach, I'm not the right audience and I'd rather not get more of these."),
    ("unsubscribe", "Je ne souhaite plus recevoir vos messages. Merci de me retirer de votre liste."),
    ("out_of_office", "Thank you for your email. I'm travelling and will check messages on my return on 5 March."),
    ("out_of_office", "Away on parental leave. For urgent requests contact support at the main office."),
    ("out_of_office", "Hello! I'm at a retreat with no wifi until the 18th, I'll write back after."),
    ("out_of_office", "Currently on a work trip. I will be slow to reply until next Tuesday."),
    ("out_of_office", "Estoy fuera de la oficina hasta el lunes."),
    ("out_of_office", "Not in the office today or tomorrow, back Thursday morning."),
    ("bounce", "The following message to <lee@gone.example> was undeliverable: the destination server said 'no mailbox here by that name'."),
    ("bounce", "Sorry, we were unable to deliver your message. Error code 550. Host unknown."),
    ("bounce", "Your message to info@closedshop.example could not be sent: that user's account has been disabled."),
    ("bounce", "SMTP error from remote mail server after RCPT TO: 550 user not found"),
    ("bounce", "Failure notice. Hi. This is the mail program at mail.fictional.example. I'm afraid I wasn't able to deliver your message."),
    ("bounce", "Your mail was refused by the receiving server. Recipient address does not exist."),
]


def main() -> None:
    rows = [{"id": f"k{i:03d}", "text": t, "intent": intent, "adversarial": False, "tags": []} for i, (intent, t) in enumerate(CASES, 1)]
    payload = {"label": "Second set, written after tuning. Only partly held out. All text is invented and fictional.", "written": "2026-11-23", "cases": rows}
    out = Path(__file__).resolve().parent.parent / "data" / "reply_heldout2.json"
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(len(rows), "cases")


if __name__ == "__main__":
    main()
