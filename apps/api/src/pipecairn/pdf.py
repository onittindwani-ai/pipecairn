"""A small, dependency free PDF writer for proposals and contracts: headings, paragraphs and bullet lists on Letter or A4 pages."""

from __future__ import annotations

import textwrap

PAGES = {"letter": (612, 792), "a4": (595, 842)}  # points
PAGE_W, PAGE_H, MARGIN = 612, 792, 64
STYLES = {"h1": ("F2", 20, 26, 62), "h2": ("F2", 14, 20, 74), "p": ("F1", 11, 15, 88), "li": ("F1", 11, 15, 82)}


def _esc(s: str) -> str:
    s = s.encode("cp1252", "replace").decode("cp1252")  # the font is WinAnsi: Western European letters, the euro sign and curly quotes work, other scripts become ?
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def parse_markdown(md: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            blocks.append(("p", " ".join(para)))
            para.clear()

    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            flush(); blocks.append(("h1", line[2:]))
        elif line.startswith("## "):
            flush(); blocks.append(("h2", line[3:]))
        elif line.startswith(("- ", "* ")):
            flush(); blocks.append(("li", line[2:]))
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
    flush()
    return blocks


def build_pdf(blocks: list[tuple[str, str]], title: str = "Document", page: str = "letter") -> bytes:
    page_w, page_h = PAGES.get(page, PAGES["letter"])
    pages: list[list[str]] = [[]]
    y = page_h - MARGIN
    for kind, text in blocks:
        font, size, lead, width = STYLES.get(kind, STYLES["p"])
        prefix = "- " if kind == "li" else ""
        lines = textwrap.wrap(prefix + text, width=width, subsequent_indent="  " if kind == "li" else "") or [""]
        gap = 8 if kind in {"h1", "h2"} else 4
        need = lead * len(lines) + gap
        if y - need < MARGIN:
            pages.append([])
            y = page_h - MARGIN
        y -= gap if kind in {"h2"} else 0
        for ln in lines:
            pages[-1].append(f"BT /{font} {size} Tf {MARGIN} {y:.0f} Td ({_esc(ln)}) Tj ET")
            y -= lead
        y -= 4 if kind not in {"h1", "h2"} else 6
    objs: list[bytes] = []
    n_pages = len(pages)
    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(n_pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    for i, cmds in enumerate(pages):
        stream = "\n".join(cmds).encode("cp1252", "replace")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {6 + 2 * i} 0 R >>".encode())
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    info = _esc(title)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info << /Title ({info}) >> >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
