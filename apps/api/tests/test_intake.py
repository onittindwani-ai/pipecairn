from sqlalchemy import func, select

from pipecairn import intake
from pipecairn.models import Contact, Deal, Enrollment, Lead, Sequence
from conftest import NOW


def flagged(session, flag):
    return {l.contact.email for l in session.scalars(select(Lead)) if flag in (l.flags or [])}


def test_import_finds_every_planted_problem(session, seeded):
    key, info = seeded["key"], seeded["info"]["import"]
    assert info.rows == 123 and info.duplicates == key["duplicate_group_count"] == 10
    assert session.scalar(select(func.count()).select_from(Contact)) == 113
    assert flagged(session, "role_based") == set(key["role_based"])
    assert flagged(session, "invalid_email") == set(key["invalid_email"])
    assert flagged(session, "invalid_timezone") == set(key["invalid_timezone"])
    assert flagged(session, "invalid_phone") == set(key["invalid_sms_phone"])
    cust = {l.contact.email for l in session.scalars(select(Lead)) if "existing_customer" in (l.flags or [])}
    assert set(key["customer_leads"]) <= cust
    suppressed = {l.contact.email for l in session.scalars(select(Lead).where(Lead.status == "suppressed"))}
    assert set(key["suppressed_emails"]) <= suppressed


def test_scoring_bands_match_the_key(session, seeded):
    key = seeded["key"]
    intake.enrich_pending(session, {})
    intake.score_pending(session, None)
    by = {l.contact.email: l.score for l in session.scalars(select(Lead))}
    assert all(by[e] >= key["perfect_fit_min_score"] for e in key["perfect_fit"])
    assert all(by[e] <= key["poor_fit_max_score"] for e in key["poor_fit"])


def test_enroll_skips_blocked_and_low_scores_and_is_repeat_safe(session, seeded):
    intake.enrich_pending(session, {})
    intake.score_pending(session, None)
    seq = session.scalars(select(Sequence)).first()
    n = intake.enroll_pending(session, seq, NOW)
    assert n > 50
    assert intake.enroll_pending(session, seq, NOW) == 0
    enrolled = {e.lead.contact.email for e in session.scalars(select(Enrollment))}
    assert not enrolled & set(seeded["key"]["must_not_send"])
    assert session.scalar(select(func.count()).select_from(Deal)) > 0


def test_csv_parse_requires_email_and_limits_size():
    import pytest

    rows = intake.parse_csv("email,first_name\na@x.example.test,Ava\n")
    assert rows == [{"email": "a@x.example.test", "first_name": "Ava"}]
    with pytest.raises(ValueError):
        intake.parse_csv("name\nAva\n")
    with pytest.raises(ValueError):
        intake.parse_csv("email\n" + "a@x.test\n" * 400_000)


def test_reimport_is_idempotent(session, seeded):
    again = intake.import_leads(session, seeded["seed"]["leads"], NOW)
    assert again.created == 0 and again.duplicates == 123
