"""Pipecairn tables. They sit on the shared Base, so core tables and these migrate together."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sendora_core.db import Base, UTCDateTime, utcnow

LEAD_STATUSES = ("new", "enriched", "scored", "enrolled", "replied", "meeting", "proposal", "won", "lost", "suppressed", "dead")
DEAL_STAGES = ("new", "contacted", "replied", "meeting", "proposal", "won", "lost")
INTENTS = ("interested", "question", "not_now", "wrong_person", "unsubscribe", "out_of_office", "bounce")


class Company(Base):
    __tablename__ = "cl_company"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(200), unique=True)
    industry: Mapped[str] = mapped_column(String(80), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    country: Mapped[str] = mapped_column(String(2), default="US")
    is_customer: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Contact(Base):
    __tablename__ = "cl_contact"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("cl_company.id"), nullable=True)
    first_name: Mapped[str] = mapped_column(String(80), default="")
    last_name: Mapped[str] = mapped_column(String(80), default="")
    email: Mapped[str] = mapped_column(String(254), unique=True)
    phone: Mapped[str] = mapped_column(String(32), default="")
    title: Mapped[str] = mapped_column(String(120), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="")
    sms_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    company: Mapped[Company | None] = relationship()


class Lead(Base):
    __tablename__ = "cl_lead"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("cl_contact.id"), unique=True)
    source: Mapped[str] = mapped_column(String(40), default="csv_list")
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    score_explanation: Mapped[str] = mapped_column(Text, default="")
    flags: Mapped[list] = mapped_column(JSON, default=list)  # for example role_based, invalid_timezone
    crm_id: Mapped[str] = mapped_column(String(120), default="")
    first_touch_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    contact: Mapped[Contact] = relationship()


class Sequence(Base):
    __tablename__ = "cl_sequence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    steps: Mapped[list[Step]] = relationship(order_by="Step.position", back_populates="sequence", cascade="all, delete-orphan")


class Step(Base):
    __tablename__ = "cl_step"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sequence_id: Mapped[int] = mapped_column(ForeignKey("cl_sequence.id"))
    position: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(8), default="email")
    delay_hours: Mapped[int] = mapped_column(Integer, default=0)
    subject: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    sequence: Mapped[Sequence] = relationship(back_populates="steps")
    __table_args__ = (UniqueConstraint("sequence_id", "position"),)


class Enrollment(Base):
    __tablename__ = "cl_enrollment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("cl_lead.id"), index=True)
    sequence_id: Mapped[int] = mapped_column(ForeignKey("cl_sequence.id"))
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)  # active, paused, stopped, done
    next_send_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    paused_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    stop_reason: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    lead: Mapped[Lead] = relationship()
    sequence: Mapped[Sequence] = relationship()
    __table_args__ = (UniqueConstraint("lead_id", "sequence_id"),)


class Mailbox(Base):
    __tablename__ = "cl_mailbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    address: Mapped[str] = mapped_column(String(254), unique=True)
    provider: Mapped[str] = mapped_column(String(40), default="smtp_imap")
    daily_cap: Mapped[int] = mapped_column(Integer, default=30)
    sent_today: Mapped[int] = mapped_column(Integer, default=0)
    sent_day: Mapped[str] = mapped_column(String(10), default="")
    sent_total: Mapped[int] = mapped_column(Integer, default=0)
    bounce_count: Mapped[int] = mapped_column(Integer, default=0)
    warmup_days: Mapped[int] = mapped_column(Integer, default=0)
    spf_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    dkim_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    dmarc_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    paused_reason: Mapped[str] = mapped_column(String(200), default="")


class Message(Base):
    __tablename__ = "cl_message"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("cl_lead.id"), index=True)
    enrollment_id: Mapped[int | None] = mapped_column(ForeignKey("cl_enrollment.id"), nullable=True)
    mailbox_id: Mapped[int | None] = mapped_column(ForeignKey("cl_mailbox.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(8), default="email")
    direction: Mapped[str] = mapped_column(String(8), default="out")
    to_addr: Mapped[str] = mapped_column(String(254), default="")
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)
    blocked_reason: Mapped[str] = mapped_column(String(120), default="")
    external_id: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (Index("ix_cl_message_ext", "external_id"),)


class Reply(Base):
    __tablename__ = "cl_reply"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("cl_message.id"), unique=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("cl_lead.id"), index=True)
    intent: Mapped[str] = mapped_column(String(20), index=True)
    confidence: Mapped[float] = mapped_column(default=0.0)
    summary: Mapped[str] = mapped_column(String(300), default="")
    suggested_action: Mapped[str] = mapped_column(String(40), default="")
    draft_reply: Mapped[str] = mapped_column(Text, default="")
    approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handled: Mapped[bool] = mapped_column(Boolean, default=False)
    return_on: Mapped[str] = mapped_column(String(10), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    message: Mapped[Message] = relationship()


class UnmatchedMail(Base):
    """Mail that came to the inbox from an address that is not a lead (an alias, a forward, someone else at the company). Kept so it is read, never silently dropped."""

    __tablename__ = "cl_unmatched_mail"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    from_addr: Mapped[str] = mapped_column(String(254), default="")
    to_addr: Mapped[str] = mapped_column(String(254), default="")
    subject: Mapped[str] = mapped_column(String(300), default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    flag: Mapped[str] = mapped_column(String(20), default="", server_default="")  # "" or "unreadable" (the message could not be read; only sender and subject are kept)
    handled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Meeting(Base):
    __tablename__ = "cl_meeting"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("cl_lead.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime())
    external_id: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default="booked")
    notes: Mapped[str] = mapped_column(Text, default="")


class Proposal(Base):
    __tablename__ = "cl_proposal"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("cl_lead.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    scope: Mapped[list] = mapped_column(JSON, default=list)
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    call_notes: Mapped[str] = mapped_column(Text, default="")
    body_md: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Contract(Base):
    __tablename__ = "cl_contract"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("cl_proposal.id"), unique=True)
    body_md: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    package_path: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Deal(Base):
    __tablename__ = "cl_deal"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("cl_lead.id"), unique=True)
    stage: Mapped[str] = mapped_column(String(12), default="new", index=True)
    value_cents: Mapped[int] = mapped_column(Integer, default=0)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    lost_reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    lead: Mapped[Lead] = relationship()


class Activity(Base):
    __tablename__ = "cl_activity"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("cl_lead.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Suppression(Base):
    __tablename__ = "cl_suppression"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))  # email, domain, phone
    value: Mapped[str] = mapped_column(String(254))
    reason: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    __table_args__ = (UniqueConstraint("kind", "value"),)


class State(Base):
    """Small key value table, for example the demo clock offset."""

    __tablename__ = "cl_state"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
