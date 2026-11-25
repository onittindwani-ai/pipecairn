"""A real (not demo) install can do the product's core job: add a mailbox and a sequence, mark customers and do not contact entries, import leads, send one."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import Adapters, RecordingEmail
from pipecairn import intake
from pipecairn.api.app import create_app
from pipecairn.context import Ctx
from pipecairn.models import Company, Enrollment, Lead, Mailbox, Message, Sequence, Suppression
from pipecairn.sender import send_tick
from sendora_core import models as _core  # noqa: F401
from sendora_core.auth import hash_password
from sendora_core.db import Base, make_engine, make_session_factory
from test_hardening_auth import PASSWORD, real_settings

TUESDAY = datetime(2026, 12, 1, 17, 0, tzinfo=UTC)  # 12:00 in New York
CSV = (
    "first_name,last_name,email,title,company,domain,timezone,industry,size,is_customer\n"
    "Ava,Alder,ava@acmedental.example.test,Owner,Acme Dental,acmedental.example.test,America/New_York,dental,12,\n"
    "Bo,Birch,bo@oldclient.example.test,Owner,Old Client,oldclient.example.test,America/New_York,dental,12,yes\n"
    "Cy,Cedar,cy@blocked.example.test,Owner,Blocked Co,blocked.example.test,America/New_York,dental,12,\n"
    "Di,Dune,di@nozone.example.test,Owner,No Zone,nozone.example.test,,dental,12,\n"
)
SEQUENCE = {"name": "Intro", "steps": [{"channel": "email", "delay_hours": 0, "subject": "Quick idea for {{company}}", "body": "Hi {{first_name}}, I help {{industry}} teams.\n\n{{sender_name}}"}]}


@pytest.fixture
def real(tmp_path):
    s = real_settings(tmp_path, mode="live", sender_name="Sam Rivera", company_name="Rivera Works", company_address="12 Main Street, Springfield, IL 62701, USA",
                      default_timezone="Europe/London", email_adapter="seed")
    engine = make_engine(s.database_url)
    Base.metadata.create_all(engine)
    ctx = Ctx(s, make_session_factory(engine))
    a = Adapters(s)
    a.email = RecordingEmail(s)
    ctx.adapters = a
    c = TestClient(create_app(s, ctx), base_url="http://api.test")
    r = c.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD})
    assert r.status_code == 200, r.text
    c.headers["x-session"] = r.json()["token"]
    return c, ctx, a


def test_a_fresh_database_can_send_one_email_end_to_end(real):
    c, ctx, a = real
    assert c.get("/api/sequences").json() == [] and c.get("/api/deliverability").json() == []
    mb = c.post("/api/mailboxes", json={"address": " Sam@Rivera.example.test ", "daily_cap": 20})
    assert mb.status_code == 200 and mb.json()["address"] == "sam@rivera.example.test"
    assert c.post("/api/mailboxes", json={"address": "sam@rivera.example.test"}).status_code == 409
    assert c.post("/api/mailboxes", json={"address": "not an address"}).status_code == 422
    seq = c.post("/api/sequences", json=SEQUENCE)
    assert seq.status_code == 200 and seq.json()["active"] is True
    assert c.post("/api/sequences", json={**SEQUENCE, "steps": [{"channel": "email", "delay_hours": 0, "subject": "", "body": "x"}]}).status_code == 422
    # customers and the old unsubscribe list come BEFORE the leads, and also work after them
    assert c.post("/api/customers", json={"values": ["oldclient.example.test"]}).json()["domains"] == 1
    sup = c.post("/api/suppressions", json={"csv": "email\ncy@blocked.example.test\n"})
    assert sup.json()["added"] == 1
    imp = c.post("/api/leads/import", json={"csv": CSV})
    assert imp.status_code == 200 and imp.json()["created"] == 4
    assert c.post("/api/leads/process").status_code == 200
    with ctx.factory() as s:
        sent = send_tick(s, ctx.effective(s), ctx.adapters, TUESDAY)
        s.commit()
        by = {m.to_addr: m for m in s.scalars(select(Message).where(Message.direction == "out"))}
    assert sent.sent == 2 and set(by) == {"ava@acmedental.example.test", "di@nozone.example.test"}  # the customer and the suppressed address were not written to
    body = next(m["body"] for m in a.email.sent if m["to"] == "ava@acmedental.example.test")
    assert "Sam Rivera" in body and "Rivera Works" in body and "12 Main Street" in body and "Reply STOP" in body  # name, company, address and opt out line added by code
    assert "I help dental teams" in body  # industry came in through the CSV
    with ctx.factory() as s:
        flags = {l.contact.email: (l.status, l.flags) for l in s.scalars(select(Lead))}
    assert flags["bo@oldclient.example.test"][0] == "dead" and "existing_customer" in flags["bo@oldclient.example.test"][1]
    assert flags["cy@blocked.example.test"][0] == "suppressed"
    assert "invalid_timezone" not in flags["di@nozone.example.test"][1]  # DEFAULT_TIMEZONE filled it


def test_only_the_owner_adds_mailboxes_and_sequences(real):
    c, ctx, _ = real
    from sendora_core.auth import make_session_token

    c.headers["x-session"] = make_session_token(ctx.settings.session_secret, "v", "viewer")
    assert c.post("/api/mailboxes", json={"address": "a@b.example.test"}).status_code == 403
    assert c.post("/api/sequences", json=SEQUENCE).status_code == 403
    assert c.post("/api/customers", json={"values": ["x.example.test"]}).status_code == 403
    assert c.post("/api/suppressions", json={"values": ["x@y.example.test"]}).status_code == 403


def test_a_second_sequence_is_not_active_until_chosen(real):
    c, _, _ = real
    first = c.post("/api/sequences", json=SEQUENCE).json()
    second = c.post("/api/sequences", json={**SEQUENCE, "name": "Other"}).json()
    assert first["active"] and not second["active"]
    assert c.post(f"/api/sequences/{second['id']}/activate").json()["active"] is True
    assert [q["active"] for q in c.get("/api/sequences").json()] == [False, True]


def test_suppression_import_stops_leads_already_enrolled(real):
    c, ctx, _ = real
    c.post("/api/sequences", json=SEQUENCE)
    c.post("/api/leads/import", json={"csv": CSV})
    c.post("/api/leads/process")
    with ctx.factory() as s:
        assert s.scalars(select(Enrollment).where(Enrollment.status == "active")).first() is not None
    r = c.post("/api/suppressions", json={"values": ["acmedental.example.test", "+14155550100", "junk", "%.com"]}).json()
    assert r["added"] == 2 and r["skipped"] == 2  # a wildcard looking domain is not a domain and r["leads_stopped"] >= 1
    with ctx.factory() as s:
        assert s.scalars(select(Enrollment).join(Lead).where(Enrollment.status == "active", Lead.status == "suppressed")).first() is None
        kinds = {x.kind for x in s.scalars(select(Suppression))}
    assert {"domain", "phone"} <= kinds
    assert c.get("/api/suppressions").json()["total"] == 2


def test_customers_marked_after_import_stop_their_leads(real):
    c, ctx, _ = real
    c.post("/api/sequences", json=SEQUENCE)
    c.post("/api/leads/import", json={"csv": CSV})
    c.post("/api/leads/process")
    r = c.post("/api/customers", json={"csv": "domain\nacmedental.example.test\n"}).json()
    assert r["leads_stopped"] == 1
    with ctx.factory() as s:
        assert s.scalars(select(Company).where(Company.domain == "acmedental.example.test")).first().is_customer
        assert s.scalars(select(Enrollment).where(Enrollment.status == "active")).all() == [] or all(e.lead.contact.email != "ava@acmedental.example.test" for e in s.scalars(select(Enrollment).where(Enrollment.status == "active")))
    assert c.post("/api/customers", json={}).status_code == 422


def test_csv_import_reads_customer_industry_and_size_columns(session):
    now = TUESDAY
    rows = intake.parse_csv("email,company,domain,industry,size,is_customer,country\nx@a.example.test,A,a.example.test,Dental,40,yes,gb\n")
    assert rows[0]["is_customer"] == "yes" and rows[0]["industry"] == "Dental"
    intake.import_leads(session, rows, now)
    co = session.scalars(select(Company).where(Company.domain == "a.example.test")).first()
    assert (co.industry, co.size, co.is_customer, co.country) == ("dental", 40, True, "GB")
    assert session.scalars(select(Lead)).first().status == "dead"


def test_business_constants_come_from_settings(tmp_path):
    from pipecairn import proposals
    from pipecairn.config import Settings
    from pipecairn.pdf import build_pdf, parse_markdown

    s = Settings(_env_file=None, target_industries="Plumbing, Roofing", min_enroll_score=70, currency_symbol="EUR", proposal_valid_days=30, page_size="a4", bounce_pause_rate=0.1)
    assert s.industries() == ("plumbing", "roofing")
    md = proposals.build_proposal_md(title="T", client_name="C", client_company="K", scope=["x"], price_cents=123456, call_notes="", valid_days=s.proposal_valid_days, currency=s.currency_symbol)
    assert "EUR1,234.56" in md and "valid for 30 days" in md
    contract = proposals.build_contract_md(proposal_title="T", client_name="C", client_company="K", scope=["x"], price_cents=100, notice_days=30)
    assert "30 days written notice" in contract
    assert b"/MediaBox [0 0 595 842]" in build_pdf(parse_markdown(md), "T", s.page_size)
    assert b"/MediaBox [0 0 612 792]" in build_pdf(parse_markdown(md), "T")
    assert "€".encode("cp1252") in build_pdf([("p", "Fee €100")], "T")  # the euro sign survives


def test_the_bounce_limit_is_a_setting(session, settings):
    from pipecairn.sender import bounce_limits, maybe_pause_for_bounces

    mb = Mailbox(address="a@b.example.test", sent_total=100, bounce_count=7, is_active=True)
    session.add(mb)
    assert maybe_pause_for_bounces(mb, 0.1, 20) is False  # 7 percent is under a 10 percent limit
    assert maybe_pause_for_bounces(mb, *bounce_limits(settings)) is True  # and over the default 5 percent
    assert "5 percent" in mb.paused_reason


def test_the_sender_name_fills_templates_and_drafts(settings):
    from pipecairn.offline_llm import draft_text
    from pipecairn.sender import _ctx

    assert "Best,\nSam" in draft_text("question", "Ava", [], "Sam")
    lead = type("L", (), {"contact": type("C", (), {"first_name": "A", "last_name": "B", "company": None, "title": ""})()})()
    assert _ctx(lead, "Sam")["sender_name"] == "Sam"
