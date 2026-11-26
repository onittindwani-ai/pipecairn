"""Proposal and contract generation from templates and call notes. No model writes any promise or price: people do."""

from __future__ import annotations

import re

from pipecairn.pdf import build_pdf, parse_markdown

LEGAL_BANNER = "Template text. It is not legal advice. Have a lawyer in your country review it before anyone signs."


def money(cents: int, symbol: str = "$") -> str:
    return f"{symbol}{cents / 100:,.2f}"


def notes_to_bullets(notes: str, limit: int = 8) -> list[str]:
    lines = [re.sub(r"^[\-*\d.)\s]+", "", ln).strip() for ln in notes.splitlines()]
    return [ln for ln in lines if ln][:limit]


def build_proposal_md(*, title: str, client_name: str, client_company: str, scope: list[str], price_cents: int, call_notes: str, your_company: str = "Your Company", valid_days: int = 14, currency: str = "$") -> str:
    bullets = notes_to_bullets(call_notes)
    parts = [f"# {title}", f"Prepared for {client_name}, {client_company}. From {your_company}.", "## What we heard on the call"]
    parts += [f"- {b}" for b in bullets] or ["- (Add your call notes to fill this section.)"]
    parts += ["## What we will do"] + [f"- {s}" for s in scope if s.strip()] if scope else ["## What we will do", "- (Choose the scope items.)"]
    parts += ["## Investment", f"The fixed fee for this scope is {money(price_cents, currency)}. This proposal is valid for {valid_days} days.", "## Next step",
              "Reply to this message to accept. We will then send the agreement for signature."]
    return "\n".join(parts)


def build_contract_md(*, proposal_title: str, client_name: str, client_company: str, scope: list[str], price_cents: int, your_company: str = "Your Company", currency: str = "$", notice_days: int = 14) -> str:
    parts = [f"# Services agreement: {proposal_title}", f"Note: {LEGAL_BANNER}",
             "## Parties", f"This agreement is between {your_company} (the Provider) and {client_company}, represented by {client_name} (the Client).",
             "## Services"] + [f"- {s}" for s in scope if s.strip()] + [
             "## Fees", f"The Client pays a fixed fee of {money(price_cents, currency)}. Payment terms: [[Payment terms: to be agreed before sending]].",
             "## Term", f"Start date: [[Start date: to be agreed]]. Either party may end the agreement with {notice_days} days written notice. Work done up to that point is paid for.",
             "## Confidentiality", "Each party keeps the other's non public business information private and uses it only for this agreement.",
             "## Limits", "[[Liability limit and governing law: have a lawyer choose these for your country.]]",
             "## Signatures", "Provider: ____________________  Date: ________", "Client: ____________________  Date: ________"]
    return "\n".join(parts)


def md_to_pdf(md: str, title: str, page: str = "letter") -> bytes:
    return build_pdf(parse_markdown(md), title, page)


def contract_open_items(md: str) -> list[str]:
    return re.findall(r"\[\[(.*?)\]\]", md)
