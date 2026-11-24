"""Reading replies. Safety critical intents are decided by rules first. The model only handles the rest."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from pipecairn.model_tasks import ClassifyOut, Intent, NextStep, read_reply  # noqa: F401  (ClassifyOut and Intent are re-exported)
from pipecairn.reply_rules import BOUNCE, OOO, UNSUB
from pipecairn.reply_text import human_part
from sendora_core.llm import LLM, LLMError
from sendora_core.safety import KillSwitchError

class Classification(BaseModel):
    intent: Intent
    confidence: float
    summary: str
    source: Literal["rule", "model"]
    next_step: NextStep = "none"  # advice from the reader. The inbox decides actions from the intent, never from this.


def classify_reply(text: str, llm: LLM | None, subject: str = "") -> Classification:
    """Bounce, out of office and unsubscribe are rules, so a clever reply cannot talk the system out of an opt out.

    The rules read what the person wrote (the quoted message, signature and legal footer are removed first, so our own
    "reply STOP" line or a company footer is never read as their request). The subject helps with delivery notices and auto replies.
    """
    full = text or ""
    subject = subject or ""
    body = human_part(full)
    seen = body + "\n" + subject
    if BOUNCE.search(full + "\n" + subject):
        return Classification(intent="bounce", confidence=0.95, summary="The message could not be delivered.", source="rule")
    if OOO.search(seen) and not UNSUB.search(seen):
        return Classification(intent="out_of_office", confidence=0.9, summary="Automatic away reply.", source="rule")
    if UNSUB.search(seen):
        return Classification(intent="unsubscribe", confidence=0.95, summary="Asked not to be contacted.", source="rule")
    if llm is None:
        return Classification(intent="question", confidence=0.0, summary="No model available. A person should read this.", source="rule")
    try:
        out = read_reply(llm, body, subject)
    except KillSwitchError:
        return Classification(intent="question", confidence=0.0, summary="The model is switched off. A person should read this.", source="rule")
    except LLMError:
        return Classification(intent="question", confidence=0.0, summary="The model reply could not be read. A person should read this.", source="rule")
    return Classification(intent=out.intent, confidence=out.confidence, summary=out.reason, source="model", next_step=out.next_step)


MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
