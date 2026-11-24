"""Lead scoring. The rubric is code, so the same lead always gets the same score. A model only writes the explanation."""

from __future__ import annotations

from dataclasses import dataclass, field

from pipecairn import model_tasks
from pipecairn.util import is_free_mail, is_role_based
from sendora_core.llm import LLM

TARGET_INDUSTRIES = ("home services", "dental", "legal", "real estate", "accounting")
ADJACENT_INDUSTRIES = ("fitness", "design", "solar")
SOURCE_POINTS = {"referral": 10, "form": 10, "webhook": 8, "crm": 6, "csv_list": 4, "scraped": 2}
MAX = {"title": 30, "size": 25, "industry": 20, "email": 15, "source": 10}


@dataclass(frozen=True)
class Features:
    title: str
    company_size: int
    industry: str
    email: str
    source: str


@dataclass
class ScoreResult:
    score: int
    breakdown: dict[str, int] = field(default_factory=dict)


def title_points(title: str) -> int:
    t = (title or "").lower()
    if any(w in t for w in ("intern", "student", "trainee")):
        return 0
    if any(w in t for w in ("founder", "owner", "ceo", "chief", "managing partner", "president")):
        return 30
    if any(w in t for w in ("vp", "vice president", "head of", "director", "partner")):
        return 22
    if "manager" in t or "lead" in t:
        return 12
    return 4


def size_points(n: int) -> int:
    if n <= 0:
        return 0
    if n == 1:
        return 4
    if n <= 10:
        return 14
    if n <= 200:
        return 25
    if n <= 1000:
        return 18
    return 10


def industry_points(industry: str, targets: tuple[str, ...] = TARGET_INDUSTRIES) -> int:
    i = (industry or "").lower()
    return 20 if i in targets else 10 if i in ADJACENT_INDUSTRIES else 0


def email_points(email: str) -> int:
    if is_role_based(email):
        return 0
    return 3 if is_free_mail(email) else 15


def score_lead(f: Features, targets: tuple[str, ...] = TARGET_INDUSTRIES) -> ScoreResult:
    parts = {
        "title": title_points(f.title), "size": size_points(f.company_size), "industry": industry_points(f.industry, targets),
        "email": email_points(f.email), "source": SOURCE_POINTS.get(f.source, 2),
    }
    return ScoreResult(score=min(100, sum(parts.values())), breakdown=parts)


def band(score: int) -> str:
    return "high" if score >= 70 else "medium" if score >= 40 else "low"


def explain_score(llm: LLM | None, f: Features, result: ScoreResult) -> str:
    """One or two plain sentences. The lead's own text goes in as untrusted data. The numbers always come from the rubric."""
    facts = f"title: {f.title}\nindustry: {f.industry}\ncompany size: {f.company_size}\nsource: {f.source}"
    return model_tasks.explain_score(llm, facts, result.score, result.breakdown)
