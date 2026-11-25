import random
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from pipecairn import intake
from pipecairn.models import Company, Contact, Enrollment, Lead, Mailbox, Message, Sequence, Suppression
from pipecairn.sender import send_tick
from pipecairn.suppression import add_suppression
from pipecairn.util import aware, normalize_email
from support import NOW, make_settings


def prepare(session, enroll=True):
    intake.enrich_pending(session, {})
    intake.score_pending(session, None)
    seq = session.scalars(select(Sequence)).first()
    if enroll:
        intake.enroll_pending(session, seq, NOW)
    session.commit()
    return seq


def run_days(session, settings, adapters, days=10, step_h=3):
    t = NOW
    rep = []
    for _ in range(days * 24 // step_h):
        rep.append(send_tick(session, settings, adapters, t))
        session.commit()
        t += timedelta(hours=step_h)
    return rep


def out_messages(session, status=("sent", "drafted")):
    return list(session.scalars(select(Message).where(Message.direction == "out", Message.status.in_(status))))


def test_nothing_on_the_answer_key_is_ever_sent_even_if_forced_in(session, settings, adapters, seeded):
    prepare(session)
    seq = session.scalars(select(Sequence)).first()
    # force every must-not-send lead into the sequence, skipping all intake checks
    forced = 0
    for e in seeded["key"]["must_not_send"]:
        c = session.scalars(select(Contact).where(Contact.email == e)).first()
        lead = session.scalars(select(Lead).where(Lead.contact_id == c.id)).first() if c else None
        if lead is None or session.scalars(select(Enrollment).where(Enrollment.lead_id == lead.id)).first():
            continue
        lead.status = "enrolled"
        session.add(Enrollment(lead_id=lead.id, sequence_id=seq.id, status="active", next_send_at=NOW))
        forced += 1
    session.commit()
    assert forced >= 20
    run_days(session, settings, adapters)
    sent_to = {normalize_email(m.to_addr) for m in out_messages(session)}
    assert not (sent_to & set(seeded["key"]["must_not_send"])), sent_to & set(seeded["key"]["must_not_send"])
    assert len(adapters.email.sent) > 50  # the good leads were still written to


def test_mailbox_caps_bounce_pause_and_quiet_hours(session, settings, adapters, seeded):
    prepare(session)
    run_days(session, settings, adapters, days=12)
    key = seeded["key"]
    boxes = {m.id: m for m in session.scalars(select(Mailbox))}
    per_day: dict[tuple[int, str], int] = {}
    for m in out_messages(session, ("sent",)):
        if m.channel != "email":
            continue
        per_day[(m.mailbox_id, aware(m.sent_at).date().isoformat())] = per_day.get((m.mailbox_id, aware(m.sent_at).date().isoformat()), 0) + 1
        lt = aware(m.sent_at).astimezone(ZoneInfo(session.scalars(select(Contact).where(Contact.email == m.to_addr)).first().timezone))
        assert 8 <= lt.hour < 18 and lt.weekday() < 5, (m.to_addr, lt)
    for (mid, _), n in per_day.items():
        assert n <= boxes[mid].daily_cap
    over = next(m for m in boxes.values() if m.address == key["mailbox_over_cap"])
    assert sum(n for (mid, d), n in per_day.items() if mid == over.id and d == NOW.date().isoformat()) == 0  # already at its cap on day one
    bad = next(m for m in boxes.values() if m.address == key["mailbox_high_bounce"])
    assert not bad.is_active and "Bounce rate" in bad.paused_reason
    assert not any(mid == bad.id for (mid, _) in per_day)


def test_draft_mode_sends_nothing(tmp_path, factory, adapters, seeded):
    s = make_settings(tmp_path, mode="draft")
    with factory() as session:
        prepare(session)
        run_days(session, s, adapters, days=5)
        assert adapters.email.sent == []
        assert len(out_messages(session, ("drafted",))) > 0 and out_messages(session, ("sent",)) == []


def test_kill_switch_halts_everything(tmp_path, factory, adapters, seeded):
    s = make_settings(tmp_path, kill_switch=True)
    with factory() as session:
        prepare(session)
        rep = send_tick(session, s, adapters, NOW)
        assert rep.halted and adapters.email.sent == []
        assert session.scalar(select(func.count()).select_from(Message)) == 0


def test_suppression_added_mid_run_stops_that_address(session, settings, adapters, seeded):
    prepare(session)
    send_tick(session, settings, adapters, NOW)
    session.commit()
    first = adapters.email.sent[0]["to"]
    n_before = len([m for m in adapters.email.sent if m["to"] == first])
    add_suppression(session, "email", first, "asked to stop", "test")
    session.commit()
    run_days(session, settings, adapters, days=10)
    assert len([m for m in adapters.email.sent if m["to"] == first]) == n_before == 1


def test_sms_needs_consent_and_a_valid_number(session, settings, adapters, seeded):
    prepare(session)
    run_days(session, settings, adapters, days=14)
    sms = list(session.scalars(select(Message).where(Message.channel == "sms")))
    consent = {c.phone for c in session.scalars(select(Contact).where(Contact.sms_consent.is_(True)))}
    for m in sms:
        if m.status == "sent":
            assert m.to_addr in consent and m.to_addr.startswith("+")
    assert any(m.status == "blocked" and m.blocked_reason == "no_sms_consent" for m in sms)


def test_unknown_timezone_is_stopped_not_looped(session, settings, adapters, seeded):
    prepare(session, enroll=False)
    lead = session.scalars(select(Lead).where(Lead.status == "scored", Lead.score >= 40)).first()
    lead.contact.timezone, lead.flags = "Mars/Olympus", []
    lead.status, lead.score = "scored", 90
    intake.enroll_pending(session, session.scalars(select(Sequence)).first(), NOW)
    session.commit()
    run_days(session, settings, adapters, days=2)
    e = session.scalars(select(Enrollment).where(Enrollment.lead_id == lead.id)).first()
    assert e.status == "stopped" and e.stop_reason == "unknown_timezone"


@pytest.mark.parametrize("seed", range(6))
def test_property_random_worlds_never_break_the_rules(tmp_path, adapters, seed):
    """Random leads, zones, caps and suppressions over two weeks. The invariants must hold in every world."""
    from pipecairn.models import Step
    from sendora_core.db import Base, make_engine, make_session_factory

    r = random.Random(seed)
    settings = make_settings(tmp_path / f"w{seed}" if False else tmp_path, database_url=f"sqlite:///{tmp_path / f'w{seed}.sqlite3'}")
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        co = Company(name="Acme", domain="acme.example.test", industry="dental", size=40)
        s.add(co)
        seq = Sequence(name="s")
        for i in range(3):
            seq.steps.append(Step(position=i, channel="email", delay_hours=r.choice([0, 6, 24, 48]), subject="Hi {{first_name}}", body="Body {{company}}"))
        s.add(seq)
        for i in range(r.randint(2, 4)):
            s.add(Mailbox(address=f"m{i}@mail.example.test", daily_cap=r.randint(1, 6), spf_ok=True, dkim_ok=True, dmarc_ok=True, sent_total=50, warmup_days=30))
        s.flush()
        zones = ["America/New_York", "Europe/Berlin", "Asia/Kolkata", "Australia/Sydney", "America/Los_Angeles", "Mars/Olympus"]
        suppressed = set()
        for i in range(40):
            c = Contact(company_id=co.id, first_name=f"N{i}", email=f"p{i}@acme.example.test", timezone=r.choice(zones))
            s.add(c)
            s.flush()
            lead = Lead(contact_id=c.id, status="scored", score=80, flags=[])
            s.add(lead)
            s.flush()
            s.add(Enrollment(lead_id=lead.id, sequence_id=seq.id, status="active", next_send_at=NOW + timedelta(hours=r.randint(0, 30))))
            if r.random() < 0.2:
                add_suppression(s, "email", c.email, "t", "t")
                suppressed.add(c.email)
        s.commit()
        t = NOW
        for _ in range(14 * 8):
            send_tick(s, settings, adapters, t)
            s.commit()
            t += timedelta(hours=3)
        msgs = list(s.scalars(select(Message).where(Message.status == "sent")))
        caps = {m.id: m.daily_cap for m in s.scalars(select(Mailbox))}
        seen: dict[tuple[int, str], int] = {}
        for m in msgs:
            assert m.to_addr not in suppressed
            lt = aware(m.sent_at).astimezone(ZoneInfo(s.scalars(select(Contact).where(Contact.email == m.to_addr)).first().timezone))
            assert 8 <= lt.hour < 18 and lt.weekday() < 5
            k = (m.mailbox_id, aware(m.sent_at).date().isoformat())
            seen[k] = seen.get(k, 0) + 1
            assert seen[k] <= caps[m.mailbox_id]
        per_lead: dict[int, int] = {}
        for m in msgs:
            per_lead[m.lead_id] = per_lead.get(m.lead_id, 0) + 1
        assert all(n <= 3 for n in per_lead.values())
