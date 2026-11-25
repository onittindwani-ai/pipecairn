"""Safety rules for reading replies: bounce, out of office, and a request to stop.

These three are decided by patterns, not by a model, so a clever reply cannot talk the system out of an opt out. The
patterns are written from general knowledge of how mail systems and people word these things (delivery notices, auto
replies, ways of asking to be left alone, legal and privacy wording, a few common phrases in other languages).
They run on the text with quoted messages, signatures and legal footers already removed (reply_text.human_part).
"""

from __future__ import annotations

import re

BOUNCE = re.compile(
    r"(mailer-daemon|postmaster@|delivery status notification|undeliverable|undelivered|delivery has failed|mail delivery failed|permanent (failure|error)|550 5\.1\.1|\b55\d 5\.\d\.\d\b|returning message to sender|"
    r"message blocked|address was not found|no such user|user unknown|unknown user|recipient mailbox does not exist|"
    r"(could not|couldn'?t|wasn'?t|was not|not) (be )?delivered|delivery (incomplete|failure|failed|delayed|delay)|returned mail|mail system error|\bbounced\b|failed permanently|"
    r"address rejected|nxdomain|quota exceeded|over quota|mailbox (is )?(full|unavailable|not found)|mail delivery software|status:? ?[45]\.\d\.\d|"
    r"\b[45]\.\d\.\d{1,3}\b (recipient|mailbox|sender|address|user|smtp)|\b55\d\b[^\n]{0,40}(reject|denied|relay|blocked|unavailable)|remote server returned|diagnostic-code|unable to deliver|(was|were) (not able|unable) to deliver|wasn'?t able to deliver|host unknown|smtp error|rcpt to|user not found|(recipient )?address does not exist|refused by the receiving|failure notice|mail program at|invalid (address|recipient|mailbox)|domain (not found|does not exist)|error code 5\d\d|was refused|"
    r"(message|e-?mail|delivery|mail)[^\n]{0,60}(has been|was|is being) delayed|(will|shall) (keep|continue) (trying|to try|retrying) (to )?(deliver|send)|still trying to deliver|temporary (delivery )?(failure|error)|(address|account|mailbox) (no longer (exists|active|in service)|is no longer)|"
    r"(your )?message (to|could)[^\n]{0,60}(not|never) (be )?(delivered|sent|reach))", re.I)

# Wording of a delivery notice that says the mail is only late. The notice's own Action and Status lines decide a real report; these words decide only when it has none.
DELAY = re.compile(r"(delivery|message|e-?mail|mail)[^\n]{0,60}(has been|was|is being|is) delayed|delivery (delayed|delay)|(will|shall) (keep|continue) (trying|to try|retrying)|still trying to deliver|temporary (delivery )?(failure|error)|"
                   r"mailbox (is )?full|over quota|quota exceeded", re.I)

OOO = re.compile(
    r"(out of (the )?office|automatic (reply|response)|auto-?(reply|response|generated)|^[ \t]*auto:|autoresponder|away from (my|the) (desk|office|email|computer)|on (holiday|vacation|pto|safari)|on (annual |parental |maternity |paternity |sick |medical |study |bereavement )?leave|"
    r"travell?ing (until|till|and|abroad|with|this)|office is closed|(is|are) closed (until|for|on|from)|no access to (my )?email|(limited|restricted|intermittent|no) (email |e-mail |internet |phone )?(access|connectivity)|"
    r"(am|is|i'm|im) (currently |presently |now )?(out|away|travell?ing|abroad|unavailable|offline|off) ?(until|till|from|at|of|on|for|in|the|this|next|and|with|work|sick)|"
    r"out until|away until|off sick|honeymoon|jury duty|sabbatical|vacation responder|trade (fair|show)|summer shutdown|shut ?down until|(will|shall) be (away|out|back|travell?ing|unavailable|off)|"
    r"(i'?ll|i will|i'm|will|am) (be )?(back|returning|return) ?(on|from|mid|next|after|by|at|once|when|monday|tuesday|wednesday|thursday|friday|in (the office|two|three|four|a (few|couple|week|month)|\d|early|mid|late|january|february|march|april|may|june|july|august|september|october|november|december))\b|\bback on the \d|(?:^|[.!?]\s+)back (in|on|next|this) \w+|returning \d|returning (on )?(mon|tue|wed|thu|fri|sat|sun)|"
    r"respond (to your (email|message) )?(on|upon|when|after|once) (my|i) (return|am back|get back)|reply once i'?m back|time off|until i return|upon my return|on my return|(will|shall) (reply|respond|get back to you) (when|once|after|on|upon)|"
    r"(public|bank) holiday|not in (the )?(office|today|tomorrow|town)|\bwork trip|\bbusiness trip|\bon (a )?(trip|retreat|course|training|conference|assignment|site visit|secondment)\b|\bretreat\b|slow to (reply|respond)|(no|limited|poor) (wi-?fi|signal|reception|service|connection)|(back|returning|return) (on |next |this )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)|(out|away|unavailable|offline|off) (today|tomorrow|all (day|week)|this week|next week)|(until|till|through) (the )?\d{1,2}(st|nd|rd|th)\b|national holiday|(for )?urgent (matters|issues|enquiries|inquiries|requests)[^\n]{0,60}(contact|call|reach|email)|"
    r"(we have|we've|we) (received|got) your (e-?mail|message|request|enquiry|inquiry|ticket|query)|ticket (number|no\.?|id|#)|\[?ticket[ #:-]*\d|(request|enquiry|inquiry|message|e-?mail|case|ticket) (has been|was|is) (received|logged|created|registered|opened)|"
    r"this is an automat|automated (reply|response|message|acknowledg)|do not reply to this|please do not reply|no-reply|noreply|this (mailbox|inbox|address) is (not monitored|unattended|no longer monitored)|"
    r"automatische antwort|abwesenheitsnotiz|abwesend|nicht erreichbar|bin (ab|bis)|im urlaub|absent du bureau|absence du bureau|je suis absent|en congé|de retour le|fuera de la oficina|estoy (de vacaciones|fuera|ausente)|respuesta automática|"
    r"fora do escritório|estou (ausente|fora|de férias)|resposta automática|fuori ufficio|sono (assente|in ferie)|risposta automatica|afwezigheid|buiten kantoor|ben (afwezig|met vakantie)|automatisch antwoord)", re.I | re.M)

UNSUB = re.compile(
    r"(\bunsubscribe\b|\bunsub\b|\bun-subscribe\b|remove me|remove my (address|email|e-mail|number|details|name|data)|\bremove (both|all|us|this|him|her|them|our|the)\b|^[ \t]*remove[ \t]*[.!]*[ \t]*$|take (me|us|this|my \w+|our \w+) (off|out|away)|^[ \t]*enough[ \t]*[.!]|off (any|all|your|this|the|that) (mailing |email |contact |call )?(lists?|thing|database)|"
    r"\b(stop|quit|cease|halt)\b[^.!?\n]{0,25}\b(emailing|e-?mails?|mailing|writing|texting|contacting|sending|messaging|messages?|spamming|bothering|harass\w*|solicit\w*|calling|phoning|pestering|reaching)\b|"
    r"do not contact|don'?t contact|never contact|do not wish to (receive|hear|be contacted)|(do not|don'?t|dont|never) (want|wish) (to )?(hear|receive|be (contacted|emailed|called|texted))|no more (e-?mails?|messages?|texts?|contact|calls?)|"
    r"(no|any|nor) (further|more|future|additional) (contact|e-?mails?|correspondence|communication|messages?|outreach|solicitation|follow[- ]?ups?)|"
    r"opt(ing)?[- ]?(me |us )?out(?!s)|(report|reporting|reported|marked?|marking|flag(ged|ging)?) (this|you|it|this address|the address|your (e-?mail|message))[^.\n]{0,30}(as )?(spam|junk|abuse|phishing)|this is spam|it'?s spam|\bunsolicited\b|\bcease\b|"
    r"delete (my|our) (data|details|info|information|address|contact|number|record)|erase (my|our)|wipe (my|our)|right to (erasure|be forgotten|object)|article 17|(under|per|pursuant to|violat\w+|breach\w*|in breach of|contrary to) (the )?(gdpr|data protection|ccpa|can-?spam|tcpa)|(this is (a|my)|my|formal|hereby) (gdpr|data protection|privacy) (request|complaint|notice)|(gdpr|data protection|privacy) (complaint|notice)|(data protection|privacy) (authority|commissioner)|complain\w* to (the )?(ico|regulator|authority|ftc|fcc)|do[- ]not[- ]call|"
    r"cease[- ]and[- ]desist|legal action|take legal|my (lawyer|attorney|solicitor)|our (lawyer|attorney|solicitor|legal (team|department|counsel))|report(ing)? you to|\bblock(ed|ing)? (you|this|your|the sender|that)|blacklist|"
    r"^[ \t]*stop[ \t]*[.!]+|^[ \t]*stop[ \t]*$|do not (e-?mail|text|call|message|write) (me|us)|never (e-?mail|text|write|call|message)|(don'?t|do not) (e-?mail|write|message|text|call|ring|contact|send)( me| us)?( again| anymore| any more| any| more| these| further| another| e-?mails?| messages?| anything)|"
    r"leave (me|us) alone|lose (my|our|this) (e-?mail|address|number|details|contact)|"
    r"(do not|don'?t) (write|e-?mail|message|text|call) (me )?(again|anymore)|please not message me|"
    r"no me (escriba|escriban|contacte|envíe|envie|molest\w+)|ne m'?[ée]crivez plus|ne (me )?(souhaite|veux|désire) plus|plus recevoir|(retir|supprim)\w+ (moi|me|mon|nous)|de (votre|la) liste|nicht mehr erhalten|von (ihrer|der) liste|(ya )?no (quiero|deseo) (recibir|más)|ne (me )?contactez plus|ne plus me contacter|désabonn\w+|desabonn\w+|désinscri\w+|aus (ihrem|dem|der) (verteiler|liste)|austragen|abmelden|"
    r"nicht mehr (kontaktieren|schreiben|anschreiben|mailen|anrufen)|keine (weiteren |weitere )?(e-?mails?|mails?|nachrichten|werbung)( mehr)?|löschen sie (meine|mich)|darme de baja|dar de baja|no (quiero|deseo) recibir|elimin\w+ (mi|mis|mi correo)|"
    r"não (me )?(envie|escreva|contacte|contacte-me)|nao (me )?(envie|escreva|contacte)|remova (o meu|meu|me)|cancelar (a )?(inscrição|subscrição)|non (mi )?(scrivere|contattare|inviare|mandare)|non voglio (più )?ricevere|rimuov\w+ (il mio|me)|cancellarmi|"
    r"niet meer (mailen|contacteren|benaderen|e-?mailen|schrijven)|geen (e-?mails?|berichten|mails) meer|verwijder (mijn|me|ons)|uitschrijven|afmelden|nie pisz|usu[nń] mnie|nie chc[eę] otrzymywa\w+|bana (yazma|mail atma|mesaj atma)|skriv inte|ta bort mig|"
    r"mat (bhejo|bhejiye|bhejna|karo)|mujhe .{0,30}mat |band kar(o|iye)|hata (do|dijiye))", re.I | re.M)
