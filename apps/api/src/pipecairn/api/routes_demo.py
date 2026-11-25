"""Demo mode only. These routes return 404 when DEMO_MODE is off."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from pipecairn import clock, demo
from pipecairn.adapters.base import InboundEmail
from pipecairn.adapters.seed import push_inbound_email
from pipecairn.api.deps import db, demo_only, get_ctx, owner, writer
from pipecairn.context import Ctx
from pipecairn.jobs import run_cycle
from pipecairn.models import Lead

router = APIRouter(prefix="/api/demo", tags=["demo"], dependencies=[Depends(demo_only)])


@router.get("/state", summary="The demo clock")
def state(s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    return {"now": ctx.now(s).isoformat()}


@router.post("/reset", summary="Reset to the seed data and a fresh clock")
def reset(s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(owner)):
    try:
        return demo.reset(s, ctx)
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/tick", summary="Run every job once, now")
def tick(s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    return run_cycle(s, ctx)


class AdvanceIn(BaseModel):
    hours: float = Field(ge=0, le=24 * 30)


@router.post("/advance", summary="Move the demo clock forward")
def advance(b: AdvanceIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    return {"now": clock.advance(s, b.hours).isoformat()}


class ReplyIn(BaseModel):
    lead_id: int
    text: str = Field(min_length=1, max_length=2000)


@router.post("/simulate-reply", summary="Drop a reply into the seed inbox")
def simulate_reply(b: ReplyIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    lead = s.get(Lead, b.lead_id)
    if lead is None:
        raise HTTPException(404, "That lead does not exist.")
    import uuid

    push_inbound_email(ctx.settings, InboundEmail(external_id=f"sim-{uuid.uuid4().hex[:10]}", from_addr=lead.contact.email, to_addr="alex@mail.pipecairn-demo.example.test", subject="Re: Quick idea", body=b.text))
    return {"ok": True}


class StressIn(BaseModel):
    n: int = Field(ge=1, le=6000)


@router.post("/stress-leads", summary="Add many fictional leads, to test the table with thousands of rows")
def stress(b: StressIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(owner)):
    from pipecairn import intake

    rows = [{"first_name": f"Test{i}", "last_name": "Person", "email": f"stress{i}@stress.example.test", "title": "Manager", "company": "Stress Co", "domain": "stress.example.test", "timezone": "America/New_York", "source": "csv_list"} for i in range(b.n)]
    rep = intake.import_leads(s, rows, ctx.now(s))
    return {"created": rep.created}
