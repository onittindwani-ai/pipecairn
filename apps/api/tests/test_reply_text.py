"""General reading rules: what counts as the sender's own words, refusals, timing words and other languages."""

import pytest

from pipecairn.offline_llm import OfflineBackend
from pipecairn.reply_text import human_part, normalize
from pipecairn.replies import classify_reply
from sendora_core.llm import LLM
from sendora_core.settings import BaseAppSettings


@pytest.fixture
def llm():
    return LLM(BaseAppSettings(_env_file=None), OfflineBackend())


def test_quoted_original_signature_and_footer_are_not_the_senders_words():
    text = (
        "Sounds good, send me times.\n\nBest,\nSam\n-- \nSam Rivera, Example Dental\nThis email is confidential. To unsubscribe from our newsletter click here.\n\n"
        "On Mon, 3 Mar 2025 at 09:12, Alex <alex@sender.example.test> wrote:\n> Hi Sam, if you want no more mails, reply STOP and I will unsubscribe you.\n"
    )
    kept = human_part(text)
    assert "send me times" in kept and "STOP" not in kept and "unsubscribe" not in kept.lower() and "confidential" not in kept


def test_a_quoted_stop_line_from_our_own_email_is_not_a_stop_request(llm):
    reply = "Yes please, send times.\n\nOn Tue, 4 Mar 2025, Alex wrote:\n> reply STOP to opt out"
    r = classify_reply(reply, llm)
    assert r.intent == "interested" and r.source == "model"


def test_a_company_newsletter_footer_is_not_a_stop_request(llm):
    r = classify_reply("Could you send pricing?\n\nTo unsubscribe from our newsletter, click here.\nSent from my iPhone", llm)
    assert r.intent != "unsubscribe"


def test_a_stop_request_inside_the_reply_still_wins_over_a_footer_and_a_quote(llm):
    r = classify_reply("Please remove me from your list.\n\n> hi, would you like a demo?", llm)
    assert r.intent == "unsubscribe" and r.source == "rule"


def test_only_a_quote_falls_back_to_the_whole_text():
    assert human_part("> just a quote") == "> just a quote"


def test_curly_quotes_and_contractions_are_normalised():
    assert normalize("We don’t need it, I’m sure") == "we do not need it, i am sure"


@pytest.mark.parametrize("text,intent", [
    ("Not interested, thanks.", "unsubscribe"),
    ("No thank you.", "unsubscribe"),
    ("We aren't interested at the moment, try us again next year.", "not_now"),
    ("Not interested in learning more right now. Try me in the spring.", "not_now"),
    ("Not the right person, Lena Fox runs this. lena.fox@practice.example.test", "wrong_person"),
    ("Yes, I would love to hear more. What times work on Thursday?", "interested"),
    ("Could you send over your pricing please", "interested"),
    ("How does it connect to Outlook?", "question"),
    ("does it work on android", "question"),
])
def test_everyday_replies_in_plain_wording(llm, text, intent):
    assert classify_reply(text, llm).intent == intent


@pytest.mark.parametrize("text", [
    "Nie pisz do mnie wiecej, usun mnie z listy.",
    "Bitte nicht mehr kontaktieren und aus dem Verteiler nehmen.",
    "Ne me contactez plus, merci.",
    "Por favor no me escriba mas.",
])
def test_stop_requests_in_other_languages_are_read_as_stop(llm, text):
    r = classify_reply(text, llm)
    assert r.intent == "unsubscribe" and r.source == "rule"


def test_subject_line_marks_a_delivery_notice_and_an_auto_reply(llm):
    assert classify_reply("Your message to jo@example.test could not go through.", llm, "Undeliverable: Quick question").intent == "bounce"
    assert classify_reply("Thanks for writing.", llm, "Automatic reply: Quick question").intent == "out_of_office"


def test_ordinary_sentences_are_not_taken_for_delivery_or_away_notices(llm):
    assert classify_reply("Our install was delayed, can you still help?", llm).source == "model"
    assert classify_reply("Are the replies sent automatically or does someone check?", llm).source == "model"
    assert classify_reply("I will get back to you in touch next week.", llm).source == "model"
    assert classify_reply("Do you handle GDPR requests for our patients?", llm).source == "model"
