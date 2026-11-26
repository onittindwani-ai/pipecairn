import json

import pytest
from sqlalchemy import select

from pipecairn import jobs
from pipecairn.adapters.base import InboundEmail
from pipecairn.adapters.seed import push_inbound_email
from pipecairn.context import Ctx
from pipecairn.models import Lead, Message, Reply, State
from pipecairn.worker import run_once
from support import DATA, make_settings
from sendora_core.jobs import Worker
from sendora_core.models import Job


@pytest.fixture
def ctx(factory, settings, seeded):
    settings.seed_dir = str(DATA)
    return Ctx(settings, factory)


def test_worker_runs_every_job_kind_and_does_not_double_schedule(ctx):
    w = Worker(ctx.factory, jobs.make_handlers(ctx))
    n = run_once(ctx, w)
    with ctx.factory() as s:
        kinds = {j.kind: j.status for j in s.scalars(select(Job))}
    assert set(kinds) == set(jobs.INTERVALS) and set(kinds.values()) == {"done"} and n == 6
    assert run_once(ctx, w) == 0  # intervals have not passed, so nothing is queued twice


def test_reply_poll_captures_and_crm_sync_respects_draft_mode(tmp_path, factory, seeded):
    s_draft = make_settings(tmp_path, mode="draft", seed_dir=str(DATA))
    ctx = Ctx(s_draft, factory)
    with factory() as s:
        jobs.job_enrich(s, ctx), jobs.job_score(s, ctx)
        lead = s.scalars(select(Lead).where(Lead.status == "enrolled")).first()
        push_inbound_email(s_draft, InboundEmail("e1", lead.contact.email, "x@y.test", "Re", "Not now, try me in January"))
        s.commit()
        assert jobs.job_reply_poll(s, ctx)["captured"] == 1
        res = jobs.job_crm_sync(s, ctx)
        assert res["synced"] == 0 and res["skipped_by_safety"] == 1  # draft mode writes nothing to a CRM
        s.commit()
        assert s.scalars(select(Reply)).first().intent == "not_now"


def test_crm_sync_in_live_mode_marks_leads(ctx):
    with ctx.factory() as s:
        jobs.job_score(s, ctx)
        r = jobs.job_crm_sync(s, ctx)
        s.commit()
        assert r["synced"] > 50 and s.scalars(select(Lead).where(Lead.crm_id != "")).first()


def test_report_job_writes_a_report(ctx):
    with ctx.factory() as s:
        jobs.job_report(s, ctx)
        s.commit()
        assert "# Weekly report" in s.get(State, "weekly_report").value
