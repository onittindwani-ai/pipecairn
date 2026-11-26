"""An offline stand in for the model, used in demo mode and tests. It is plain rules, NOT a language model.

It answers the same prompts the live model would get, so the whole product runs with no key and no network.
Everything it produces is a rule based guess. Accuracy numbers measured with it say nothing about a live model.
"""

from __future__ import annotations

import ast
import json
import re

from pipecairn import offline_lexicon as lex
from pipecairn.reply_text import normalize
from sendora_core.llm import LLMResponse
from sendora_core.safety import UNTRUSTED_CLOSE, UNTRUSTED_OPEN

# Sentences that try to give the system orders. The stand in drops them before it reads the rest.
INSTRUCTION_LIKE = re.compile(
    r"(ignore (all |your |the )?(previous|prior|above)?\s*(instructions|rules)|ignore your rules|system:|\[assistant|you are now|admin mode|"
    r"mark me as|approve all|delete the|forward this to|send a proposal to|reply to everyone|call the send tool)", re.I)

WRONG = ("wrong person", "wrong contact", "wrong dept", "not me", "do not handle", "i don't handle", "not the one", "colleague", "left this role", "our manager", "our office manager",
         "handled by", "not my area", "receptionist", "question for our", "talk to my", "try our", "right person", "general manager", "not the right person", "not the right contact",
         "not the right team", "not the decision maker", "you want ", "looped him", "looped her", "outsource", "i'm just the", "i am just the", "covers my old", "changed jobs",
         "no longer with", "my replacement", "passing this to", "forwarded your email", "forwarded this to", "head office", "hq's call", "regional office", "i only handle",
         "i handle", "not in charge", "by mistake", "check with the", "contact my", "whoever handles", "mail the founder", "better placed", "not an employee", "no say")
NOT_NOW = ("not now", "next quarter", "bad timing", "no budget", "try me again", "check back", "busy right now", "after the summer", "revisit", "get back to me in",
           "circle back", "not a priority", "not this quarter", "next year", "in the spring", "in january", "follow up in", "reach out next year", "maybe next", "send me a note then", "another provider",
           "heads down", "fiscal year", "next six months", "no new vendors", "right time", "maybe later", "renewed with", "ask me again", "freeze", "no plans to change", "for now",
           "board meets", "at the moment", "reconnect in", "after the new year", "swamped", "next month", "wrong season", "tax season", "budget cycle", "park this", "mid-migration",
           "all set", "ping me after", "write again", "ask then", "until the new", "in 2027", "after april", "call me in q")
INTERESTED = ("sounds useful", "sounds good", "interested", "let's talk", "lets talk", "set up a call", "demo", "book me", "happy to chat", "send me a proposal", "send over",
              "count me in", "call me", "learn more", "we need help", "looking for something", "timely", "let's set up", "tomorrow morning", "open tuesday", "proposal",
              "tell me more", "send times", "calendar", "invite me", "pilot", "next step", "pricing deck", "move ahead", "discovery call", "video call", "let's do it", "sign up", "my attention", "fair point", "could be a fit")
STRONG_INTEREST = ("i am interested", "i'm interested", "yes, interested", "interested in learning", "can we talk", "can we chat", "book me", "set up a call", "send me a proposal", "happy to chat", "let's talk", "lets talk", "count me in", "yes please", "yes, this sounds",
                   "invite me", "send times", "calendar link", "on a call", "video call", "discovery call", "when can your team", "sign up for a trial", "who do i speak to", "move ahead", "let's do it", "pilot", "put something in my calendar", "set up 20", "send over your terms", "hop on")
QUESTION_WORDS = ("what", "how", "do you", "can you", "is there", "which", "where", "who", "does it", "why")


def _strip_instructions(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    kept = [p for p in parts if not INSTRUCTION_LIKE.search(p)]
    cleaned = " ".join(kept)
    return re.sub(r"\[[^\]]*\]|<<[^>]*>>", " ", cleaned)


def _between_markers(prompt: str) -> str:
    m = re.search(re.escape(UNTRUSTED_OPEN) + r"[^\n]*\n(.*?)\n" + re.escape(UNTRUSTED_CLOSE), prompt, re.S)
    return m.group(1) if m else prompt


def classify_text(text: str) -> tuple[str, float, str]:
    """Read one reply with word patterns. Order matters: someone else, a complaint, a time word, a flat no, yes, a question."""
    clean = _strip_instructions(text)
    t = normalize(clean).strip()
    hit = lambda words: any(w in t for w in words)  # noqa: E731
    if hit(WRONG) or lex.WRONG.search(t):
        return "wrong_person", 0.8, "Says someone else handles this."
    greeting = re.match(r"\s*(?:hi|hello|hey|dear|good (?:morning|afternoon))\s+([A-Z][a-z]+)", clean)
    if lex.NAMED_REFERRAL.search(clean.replace(greeting.group(1), " ") if greeting else clean):
        return "wrong_person", 0.7, "Points to a named person."
    timing = hit(NOT_NOW) or lex.NOT_NOW.search(t)
    if timing:
        return "not_now", 0.8, "Interested later or busy now."
    if lex.REFUSAL.search(t):
        return "unsubscribe", 0.7, "A plain no with no later date. Treated as a request to stop."
    asks = "?" in lex.SCHEDULING_QUESTION.sub(" ", t)
    if hit(STRONG_INTEREST) or lex.WARM.search(t):
        return "interested", 0.78, "Wants to talk or see an offer."
    warm = hit(INTERESTED) or lex.STRONG.search(t)
    if warm and not asks:
        return "interested", 0.78, "Wants to talk or see an offer."
    if asks or lex.QUESTION.search(t) or any(re.search(rf"\b{w}\b", t) for w in QUESTION_WORDS):
        return "question", 0.7, "Asks a question before deciding."
    return "question", 0.4, "Unclear. A person should read this."


NEXT_STEP = {"interested": "book_call", "question": "answer_question", "wrong_person": "ask_referral", "out_of_office": "wait", "not_now": "snooze", "unsubscribe": "stop_contact", "bounce": "stop_contact"}


def draft_text(intent: str, first_name: str, slots: list[str], sender_name: str = "Alex") -> str:
    hi = f"Hi {first_name or 'there'},"
    if intent == "interested":
        times = "\n".join(f"- {s}" for s in slots) or "- [[FILL IN: two or three times you can do]]"
        return f"{hi}\n\nGreat to hear. Here are a few times for a short call:\n{times}\n\nTell me which one works and I will send the invite.\n\nBest,\n{sender_name}"
    if intent == "question":
        return f"{hi}\n\nThanks for asking. [[FILL IN: your answer to their question]]\n\nWould a short call help?\n\nBest,\n{sender_name}"
    if intent == "wrong_person":
        return f"{hi}\n\nThanks for letting me know. Who would be the right person to talk to about this? I will keep it short.\n\nBest,\n{sender_name}"
    return f"{hi}\n\nThanks for your reply.\n\nBest,\n{sender_name}"


def _plain_points(raw: str) -> str:
    """A points dict written as 'title: 30, size: 25' instead of a Python dict."""
    try:
        data = ast.literal_eval(raw)
        return ", ".join(f"{k} {v}" for k, v in data.items()) if isinstance(data, dict) else raw
    except (ValueError, SyntaxError):
        return raw


class OfflineBackend:
    """Implements the LLM backend protocol with rules. Recognises the [task:...] marker the product puts first in each prompt."""

    def complete(self, *, model: str, system: str, prompt: str, max_tokens: int) -> LLMResponse:
        task = (re.search(r"\[task:([a-z_]+)\]", prompt) or [None, ""])[1]
        if task == "classify_reply":
            intent, conf, reason = classify_text(_between_markers(prompt))
            text = json.dumps({"intent": intent, "confidence": conf, "reason": reason, "next_step": NEXT_STEP[intent]})
        elif task == "draft_reply":
            facts = json.loads((re.search(r"Facts \(JSON\): (\{.*\})", prompt) or [None, "{}"])[1])
            text = json.dumps({"body": draft_text(facts.get("intent", ""), facts.get("recipient_first_name", ""), facts.get("times_you_may_offer", []), facts.get("sender_first_name") or "Alex")})
        elif task == "explain_score":
            score = re.search(r"score: (\d+)", prompt)
            pts = re.search(r"points: (\{.*?\})", prompt)
            text = f"Scored {score.group(1) if score else '?'} out of 100 by the fixed rubric. Points: {_plain_points(pts.group(1)) if pts else 'n/a'}."
        elif task == "summarise_week":
            text = "A rule based summary: see the numbers above. A live model would write a short narrative here."
        else:
            text = "Offline stand in model: no answer for this task."
        return LLMResponse(text, max(1, len(prompt) // 4), max(1, len(text) // 4), model)
