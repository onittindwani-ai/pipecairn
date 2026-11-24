"""Clean an inbound email down to what the person wrote.

A reply usually carries more than the person's words: the message it answers (quoted), a signature, a legal footer, a
phone mail line. Words in those parts are not the sender's request. A quoted "reply STOP" from OUR first email must
never read as a stop request, and a company footer saying "unsubscribe from our newsletter" is not one either.

Only general email conventions are used here (quote marks, "On ... wrote:", "-----Original Message-----", the "-- "
signature line, common footer wording), so it works on any mail client and any language.
"""

from __future__ import annotations

import re
import unicodedata

QUOTE_HEADERS = re.compile(
    r"^\s*(-{2,}\s*(original message|forwarded message|ursprüngliche nachricht|message d'origine|mensaje original)\s*-{2,}|"
    r"_{5,}\s*$|begin forwarded message|"
    r"on [^\n]{4,200}\bwrote:\s*$|on [^\n]{4,200}$\n[^\n]{0,120}\bwrote:\s*$|"
    r"le [^\n]{4,200}a écrit\s*:|am [^\n]{4,200}schrieb[^\n]{0,80}:|el [^\n]{4,200}escribió:|em [^\n]{4,200}escreveu:|il [^\n]{4,200}ha scritto:|op [^\n]{4,200}schreef[^\n]{0,80}:|"
    r"from:[^\n]{3,200}\n\s*(sent|date|to|subject):)", re.I | re.M)
SIGNATURE_START = re.compile(
    r"^(-- ?|\u2014+ ?|sent from my [^\n]*|sent from (outlook|mail|yahoo|gmail)[^\n]*|get outlook for [^\n]*|sent via [^\n]*|sent with [^\n]*|"
    r"von meinem [^\n]*gesendet|envoyé de mon [^\n]*|enviado desde mi [^\n]*)\s*$", re.I | re.M)
FOOTER_LINE = re.compile(
    r"(confidential|intended (only )?for the (named )?(recipient|addressee)|intended recipient|privileged|if you (have )?received this (e-?mail|message|communication) (in error|by mistake)|"
    r"disclaimer|legally protected|think before you print|please consider the environment|virus[- ]free|"
    r"(to|click|tap) (here to )?(unsubscribe|stop receiving|opt[- ]?out) (from )?(our|the|this) (newsletter|mailing|list|updates|promotional|bulletin|digest)|"
    r"(unsubscribe|opt[- ]?out) (from )?our (newsletter|mailing list|bulletin|digest)|"
    r"(reply|text|send) ['\"“]?(stop|remove|unsubscribe)['\"”]? (to|and we|and you) [^\n]{0,60}(our|the) (newsletter|list|updates|alerts)|"
    r"manage (your )?(email )?(preferences|subscriptions?)|view (this )?(email )?in (your )?browser|registered (office|in)|company (no|number|reg)|vat (no|number|id)|"
    r"you are receiving this (e-?mail|message) because)", re.I)

_QUOTES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "“": '"', "”": '"', " ": " ", "​": ""})
_CONTRACTIONS = (
    (r"\bwon't\b", "will not"), (r"\bcan't\b", "cannot"), (r"\bshan't\b", "shall not"), (r"\bain't\b", "is not"),
    (r"n't\b", " not"), (r"\bi'm\b", "i am"), (r"\bwe're\b", "we are"), (r"\byou're\b", "you are"), (r"\bthey're\b", "they are"),
    (r"\bi've\b", "i have"), (r"\bwe've\b", "we have"), (r"\bi'd\b", "i would"), (r"\bwe'd\b", "we would"), (r"\bi'll\b", "i will"),
    (r"\bwe'll\b", "we will"), (r"\blet's\b", "let us"), (r"\bit's\b", "it is"), (r"\bthat's\b", "that is"), (r"\bwhat's\b", "what is"),
    (r"\bthere's\b", "there is"), (r"\bhe's\b", "he is"), (r"\bshe's\b", "she is"),
)


def straighten(text: str) -> str:
    """Curly quotes and odd spaces to plain ones, so one pattern matches every way a mail client wrote it."""
    return unicodedata.normalize("NFKC", text or "").translate(_QUOTES)


def normalize(text: str) -> str:
    """Lower case, straight quotes, contractions opened out ("don't" to "do not"), spaces squeezed."""
    t = straighten(text).lower()
    for pat, rep in _CONTRACTIONS:
        t = re.sub(pat, rep, t)
    return re.sub(r"[ \t]+", " ", t)


def human_part(text: str) -> str:
    """The words the person wrote: no quoted message, signature, mobile line or legal footer. Falls back to the whole text if nothing is left."""
    body = straighten(text)
    lines = [ln for ln in body.splitlines() if not ln.lstrip().startswith(">")]
    body = "\n".join(lines)
    for pattern in (QUOTE_HEADERS, SIGNATURE_START):
        m = pattern.search(body)
        if m:
            body = body[: m.start()]
    kept = []
    for para in re.split(r"\n\s*\n", body):
        sentences = re.split(r"(?<=[.!?])\s+|\n", para)
        kept.append(" ".join(s for s in sentences if not FOOTER_LINE.search(s)))
    cleaned = "\n".join(p for p in kept if p.strip()).strip()
    return cleaned if len(cleaned) >= 2 else straighten(text).strip()
