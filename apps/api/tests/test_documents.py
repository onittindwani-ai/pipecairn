import re

import pytest

from pipecairn import proposals
from pipecairn.handoff import BreezedocHandoff
from pipecairn.pdf import build_pdf, parse_markdown


def check_pdf(b: bytes):
    assert b.startswith(b"%PDF-1.4") and b.rstrip().endswith(b"%%EOF")
    xref = int(re.search(rb"startxref\n(\d+)", b).group(1))
    assert b[xref:xref + 4] == b"xref"
    n = int(re.search(rb"xref\n0 (\d+)", b).group(1))
    offs = [int(x) for x in re.findall(rb"(\d{10}) 00000 n", b[xref:])]
    assert len(offs) == n - 1
    for i, off in enumerate(offs, 1):
        assert b[off:].startswith(f"{i} 0 obj".encode())
    return b.count(b"/Type /Page ") if b"/Type /Page " in b else b.count(b"/Type /Page")


def test_pdf_is_structurally_valid_and_paginates():
    long = "\n\n".join(f"Paragraph {i} " + "word " * 80 for i in range(40))
    b = build_pdf(parse_markdown("# Title\n## Part\n- item (with brackets)\n" + long), "T")
    assert check_pdf(b) >= 3
    assert b"\\(with brackets\\)" in b


def test_pdf_handles_non_latin_text():
    check_pdf(build_pdf([("p", "Cafe ☃ 中文")]))


def test_proposal_and_contract_content():
    md = proposals.build_proposal_md(title="Faster replies", client_name="Ava Alder", client_company="Acme Dental", scope=["Set up the system", "Train the team"], price_cents=450000, call_notes="- loses leads after hours\n- wants texts too")
    assert "$4,500.00" in md and "loses leads after hours" in md and "Train the team" in md
    c = proposals.build_contract_md(proposal_title="Faster replies", client_name="Ava Alder", client_company="Acme Dental", scope=["Set up the system"], price_cents=450000)
    assert "not legal advice" in c and len(proposals.contract_open_items(c)) >= 3
    check_pdf(proposals.md_to_pdf(c, "Contract"))


def test_handoff_package_contents_and_path_safety(tmp_path, settings):
    h = BreezedocHandoff(settings, tmp_path)
    r = h.prepare(contract_pdf=b"%PDF-1.4 x", title="Acme / Faster replies ../../etc", signers=[{"name": "Ava", "email": "ava@x.example.test"}], open_items=["Payment terms"])
    from pathlib import Path

    p = Path(r.package_path)
    assert p.parent == tmp_path.resolve() and {f.name for f in p.iterdir()} == {"contract.pdf", "signers.csv", "OPEN-ITEMS.txt", "INSTRUCTIONS.txt"}
    assert not r.sent and "UNVERIFIED" in r.instructions
    assert "ava@x.example.test" in (p / "signers.csv").read_text()
