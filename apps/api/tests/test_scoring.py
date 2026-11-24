import random

from pipecairn import scoring
from pipecairn.scoring import Features, score_lead

PERFECT = Features("Founder", 50, "dental", "ava@x.example.test", "referral")
POOR = Features("Intern", 1, "retail", "x@gmail.example.test", "scraped")


def test_perfect_and_poor_bands():
    assert score_lead(PERFECT).score == 100
    assert score_lead(POOR).score <= 30


def test_score_is_consistent_and_bounded():
    r = random.Random(7)
    titles, inds = ["Founder", "Intern", "Director of Ops", "Office Manager", ""], ["dental", "retail", "fitness", ""]
    for _ in range(300):
        f = Features(r.choice(titles), r.choice([0, 1, 5, 50, 500, 5000]), r.choice(inds), r.choice(["a@x.test", "info@x.test", "a@gmail.com"]), r.choice(list(scoring.SOURCE_POINTS) + ["other"]))
        a, b = score_lead(f), score_lead(f)
        assert a == b and 0 <= a.score <= 100 and a.score == sum(a.breakdown.values())


def test_breakdown_never_exceeds_caps():
    res = score_lead(PERFECT)
    assert all(v <= scoring.MAX[k] for k, v in res.breakdown.items())
