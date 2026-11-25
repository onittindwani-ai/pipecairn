from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from pipecairn import proposals
from pipecairn.api.deps import db, get_ctx, writer
from pipecairn.api.serializers import iso
from pipecairn.context import Ctx
from pipecairn.models import Activity, Contract, Deal, Lead, Proposal
from sendora_core.audit import record_audit

router = APIRouter(prefix="/api", tags=["proposals"])


class ProposalIn(BaseModel):
    lead_id: int
    title: str = Field(min_length=1, max_length=200)
    scope: list[str] = Field(default_factory=list, max_length=20)
    price_cents: int = Field(ge=0, le=100_000_000)
    call_notes: str = Field(default="", max_length=8000)


def _md(lead: Lead, b: ProposalIn, ctx: Ctx) -> str:
    c, st = lead.contact, ctx.settings
    return proposals.build_proposal_md(title=b.title, client_name=f"{c.first_name} {c.last_name}".strip() or c.email, client_company=c.company.name if c.company else "", scope=b.scope,
                                       price_cents=b.price_cents, call_notes=b.call_notes, your_company=st.company_name, valid_days=st.proposal_valid_days, currency=st.currency_symbol)


def row(p: Proposal) -> dict:
    return {"id": p.id, "lead_id": p.lead_id, "title": p.title, "scope": p.scope, "price_cents": p.price_cents, "status": p.status, "body_md": p.body_md, "created_at": iso(p.created_at)}


@router.post("/proposals/preview", summary="Build the proposal text without saving")
def preview(b: ProposalIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    lead = s.get(Lead, b.lead_id)
    if lead is None:
        raise HTTPException(404, "That lead does not exist.")
    return {"body_md": _md(lead, b, ctx)}


@router.post("/proposals", summary="Save a proposal")
def create(b: ProposalIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    lead = s.get(Lead, b.lead_id)
    if lead is None:
        raise HTTPException(404, "That lead does not exist.")
    p = Proposal(lead_id=lead.id, title=b.title, scope=b.scope, price_cents=b.price_cents, call_notes=b.call_notes, body_md=_md(lead, b, ctx), status="ready", created_at=ctx.now(s))
    s.add(p)
    deal = s.scalars(select(Deal).where(Deal.lead_id == lead.id)).first()
    if deal:
        deal.stage, deal.value_cents = "proposal", b.price_cents
    lead.status = "proposal"
    s.add(Activity(lead_id=lead.id, kind="proposal", summary=f"Proposal saved: {b.title}", created_at=ctx.now(s)))
    s.flush()
    record_audit(s, u["user"], "proposal.created", f"proposal:{p.id}", {"price_cents": b.price_cents})
    return row(p)


@router.get("/proposals", summary="List proposals")
def listing(lead_id: int | None = None, s: Session = Depends(db)):
    stmt = select(Proposal).order_by(Proposal.id.desc())
    if lead_id:
        stmt = stmt.where(Proposal.lead_id == lead_id)
    return [row(p) for p in s.scalars(stmt)]


@router.get("/proposals/{pid}/pdf", summary="The proposal as a PDF")
def pdf(pid: int, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    p = s.get(Proposal, pid)
    if p is None:
        raise HTTPException(404, "That proposal does not exist.")
    return Response(proposals.md_to_pdf(p.body_md, p.title, ctx.settings.page_size), media_type="application/pdf", headers={"content-disposition": f'inline; filename="proposal-{p.id}.pdf"'})


@router.post("/proposals/{pid}/contract", summary="Create the contract text from a proposal")
def make_contract(pid: int, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    p = s.get(Proposal, pid)
    if p is None:
        raise HTTPException(404, "That proposal does not exist.")
    c = s.scalars(select(Contract).where(Contract.proposal_id == p.id)).first()
    if c is None:
        lead = s.get(Lead, p.lead_id)
        md = proposals.build_contract_md(proposal_title=p.title, client_name=f"{lead.contact.first_name} {lead.contact.last_name}".strip(), client_company=lead.contact.company.name if lead.contact.company else "", scope=p.scope, price_cents=p.price_cents,
                                        your_company=ctx.settings.company_name, currency=ctx.settings.currency_symbol, notice_days=ctx.settings.contract_notice_days)
        c = Contract(proposal_id=p.id, body_md=md)
        s.add(c)
        s.flush()
        record_audit(s, u["user"], "contract.created", f"contract:{c.id}", {})
    return {"id": c.id, "body_md": c.body_md, "status": c.status, "open_items": proposals.contract_open_items(c.body_md), "package_path": c.package_path}


@router.get("/contracts/{cid}/pdf", summary="The contract as a PDF")
def contract_pdf(cid: int, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    c = s.get(Contract, cid)
    if c is None:
        raise HTTPException(404, "That contract does not exist.")
    return Response(proposals.md_to_pdf(c.body_md, "Contract", ctx.settings.page_size), media_type="application/pdf")


@router.post("/contracts/{cid}/handoff", summary="Prepare the signing package (nothing is sent)")
def handoff(cid: int, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    c = s.get(Contract, cid)
    if c is None:
        raise HTTPException(404, "That contract does not exist.")
    p = s.get(Proposal, c.proposal_id)
    lead = s.get(Lead, p.lead_id)
    res = ctx.adapters.esign.prepare(
        contract_pdf=proposals.md_to_pdf(c.body_md, "Contract", ctx.settings.page_size),
        title=f"{lead.contact.company.name if lead.contact.company else lead.contact.email} {p.title}",
        signers=[{"name": f"{lead.contact.first_name} {lead.contact.last_name}".strip(), "email": lead.contact.email}],
        open_items=proposals.contract_open_items(c.body_md), folder_key=f"c{c.id}")  # the contract id keeps two folders from ever sharing a name
    c.status, c.package_path = "handed_off", res.package_path
    record_audit(s, u["user"], "contract.handed_off", f"contract:{c.id}", {"sent": False})
    return {"status": c.status, "package_path": "(folder on the server)" if res.package_path else "", "instructions": res.instructions, "sent": res.sent}
