"""Reading replies. Safety critical intents are decided by rules first. The model only handles the rest."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel

from pipecairn.model_tasks import ClassifyOut, Intent, NextStep, read_reply  # noqa: F401  (ClassifyOut and Intent are re-exported)
from pipecairn.reply_rules import BOUNCE, CARRIER_STOP, HARD_STOP, OOO_STRONG, OOO_WEAK, STOP_WORDS
from pipecairn.reply_text import compact, human_part
from sendora_core.llm import LLM, LLMError
from sendora_core.safety import KillSwitchError

class Classification(BaseModel):
    intent: Intent
    confidence: float
    summary: str
    source: Literal["rule", "model"]
    next_step: NextStep = "none"  # advice from the reader. The inbox decides actions from the intent, never from this.
    # False when the wording only MIGHT be a stop request or an automatic reply (a single word such as "block" or "legal team", a date, a ticket number). The inbox then
    # stops the sequence and leaves the reply open for a person, and suppresses nothing. True for a complete, unmistakable request and for every model decision.
    certain: bool = True
    stop_wording: str = ""  # the wide net matched (not a complete request): the person is told which words made the reader careful


STOP_PREFIX = re.compile(r"^\s*(?:(?:re|fwd?|aw|sv|antw|rv|tr|wg)\s*:\s*)+", re.I)


def _plain_subject(subject: str) -> str:
    return re.sub(r"\s+", " ", STOP_PREFIX.sub("", subject or "")).strip().casefold()


def _stop_subject(subject: str, own_subjects: Iterable[str]) -> str:
    """The subject as far as a request to stop is concerned: without Re: and Fwd: and not at all when it is the subject of a message we sent (the lead pressed reply, the
    words are ours: a campaign called "Stop writing follow up emails by hand" is not a request to stop). A mailto unsubscribe link sends the subject "unsubscribe", which counts."""
    plain = _plain_subject(subject)
    if not plain or plain in {_plain_subject(s) for s in own_subjects}:
        return ""
    return STOP_PREFIX.sub("", subject).strip()


def _unless_ours(subject: str, own_subjects: Iterable[str]) -> str:
    """The subject for reading delivery notices and auto replies ("Undeliverable: ...", "Automatic reply: ..."), without the case where it is only our own subject coming
    back with Re: in front (a campaign called "Out of office? Not anymore" is not an away message)."""
    return "" if _plain_subject(subject) in {_plain_subject(s) for s in own_subjects} else subject


def is_carrier_stop(body: str) -> bool:
    """The whole message is one stop word (STOP, STOPALL, QUIT, CANCEL, END, "Please stop"): the standard words of a text message opt out."""
    return len(body) <= 60 and CARRIER_STOP.fullmatch(body.strip()) is not None


def classify_reply(text: str, llm: LLM | None, subject: str = "", *, is_dsn: bool = False, auto_reply: bool | None = None, own_subjects: Iterable[str] = ()) -> Classification:
    """Bounce, out of office and unsubscribe are rules, so a clever reply cannot talk the system out of an opt out.

    The rules read what the person wrote (the quoted message, signature and legal footer are removed first, so our own
    "reply STOP" line or a company footer is never read as their request). The subject helps with delivery notices and auto replies.

    A complete request to stop always wins over a guess that the mail bounced: "please unsubscribe me, this address is no longer used" is an opt out. Only a real
    delivery status report (is_dsn) is read as a bounce first, and even then the report's own Action and Status lines decide what it means (see inbox.dsn_outcome).

    How sure a rule is: a complete request ("unsubscribe", "remove me from your list", "stop emailing me", STOP, STOPALL, QUIT, CANCEL, END) is certain. Wording that
    only might be one ("block", "legal team", "remove the setup fee", "stop sending the PDFs, just call me") goes to the reader like any other reply and comes back with
    certain=False and the words that made it careful, so the inbox stops the sequence but suppresses nothing. An out of office reply is certain when it carries the words
    of one or an auto reply header (auto_reply is True); a date or a ticket number alone (auto_reply False) is not. auto_reply None means the caller has no header to look at.
    own_subjects are the subjects of the messages we sent this person: a reply that only repeats one of them says nothing about stopping.
    """
    subject = compact(subject or "", 300)
    body = human_part(text or "")
    own = list(own_subjects)
    seen = body + "\n" + _unless_ours(subject, own)
    if not is_dsn:
        if is_carrier_stop(body) or HARD_STOP.search(body + "\n" + _stop_subject(subject, own)):  # a request to stop always wins, whatever else the text says
            return Classification(intent="unsubscribe", confidence=0.95, summary="Asked not to be contacted.", source="rule")
    if BOUNCE.search(seen):  # what the person wrote, not the quoted message under it: a reply that quotes an old delivery notice is not a delivery notice
        return Classification(intent="bounce", confidence=0.95, summary="The message could not be delivered.", source="rule")
    wide = None if is_dsn else STOP_WORDS.search(body)
    if not wide:
        strong, weak = OOO_STRONG.search(seen), OOO_WEAK.search(seen)
        if strong or weak:
            sure = bool(strong) or auto_reply is not False
            return Classification(intent="out_of_office", confidence=0.9 if sure else 0.5, summary="Automatic away reply." if sure else "Looks like an away or acknowledgement wording, but nothing proves it is automatic. A person should read this.", source="rule", certain=sure)
    note = f"The wording ({wide.group(0).strip()[:40]!r}) may be a request to stop, but it is not a complete one. Nothing was suppressed: read it before anything is sent." if wide else ""
    if llm is None:
        return Classification(intent="question", confidence=0.0, summary=("No model available. A person should read this. " + note).strip(), source="rule", certain=not wide, stop_wording=note)
    try:
        out = read_reply(llm, body, subject)
    except KillSwitchError:
        return Classification(intent="question", confidence=0.0, summary=("The model is switched off. A person should read this. " + note).strip(), source="rule", certain=not wide, stop_wording=note)
    except LLMError:
        return Classification(intent="question", confidence=0.0, summary=("The model reply could not be read. A person should read this. " + note).strip(), source="rule", certain=not wide, stop_wording=note)
    return Classification(intent=out.intent, confidence=out.confidence, summary=(out.reason + " " + note).strip(), source="model", next_step=out.next_step, certain=not wide, stop_wording=note)


MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
