"""Message templates. One pass, no logic, unknown names are an error you can see in the preview."""

from __future__ import annotations

import re

from pipecairn.util import clean_header

VAR = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
KNOWN = {"first_name", "last_name", "company", "industry", "title", "sender_name"}


class TemplateError(ValueError):
    pass


def variables_in(template: str) -> set[str]:
    return set(VAR.findall(template))


def render(template: str, ctx: dict[str, str], *, header: bool = False) -> str:
    """Fill {{name}} fields in one pass. Values are never expanded again, so a contact named {{company}} stays literal."""
    unknown = variables_in(template) - set(ctx)
    if unknown:
        raise TemplateError(f"Unknown field(s): {', '.join(sorted(unknown))}. Known: {', '.join(sorted(ctx))}.")
    out = VAR.sub(lambda m: str(ctx[m.group(1)]), template)
    return clean_header(out) if header else out
