"""The in app kill switch, alembic and the worker settings, output files, and that the docs and .env.example list every setting."""

import re
import stat
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from support import DATA, Adapters, make_settings
from pipecairn import worker
from pipecairn.adapters.base import PersonRecord
from pipecairn.adapters.seed import SeedCrm
from pipecairn.api.app import create_app
from pipecairn.config import Settings
from pipecairn.context import Ctx, set_state
from pipecairn.dburl import resolve_url
from pipecairn.handoff import BreezedocHandoff
from pipecairn.jobs import job_crm_sync
from pipecairn.models import Contract, Lead
from pipecairn.util import csv_safe
from sendora_core.db import Base, make_engine, make_session_factory

ROOT = Path(__file__).resolve().parents[3]


class RecordingCrm(SeedCrm):
    def __init__(self, settings):
        super().__init__(settings)
        self.writes: list[str] = []

    def upsert_person(self, person: PersonRecord) -> str:
        ref = super().upsert_person(person)  # the adapter's own guard still reads the environment settings (MODE=live here)
        self.writes.append(person.email)
        return ref


def test_the_in_app_kill_switch_and_force_draft_stop_crm_writes_even_with_mode_live(tmp_path):
    s = make_settings(tmp_path, mode="live")
    engine = make_engine(s.database_url)
    Base.metadata.create_all(engine)
    ctx = Ctx(s, make_session_factory(engine))
    crm = RecordingCrm(s)
    ctx.adapters = Adapters(s)
    ctx.adapters.crm = crm
    from pipecairn import intake
    from pipecairn.seeding import load_seed, read_seed
    from support import NOW

    with ctx.factory() as db:
        load_seed(db, read_seed(DATA), NOW)
        intake.enrich_pending(db, {})
        intake.score_pending(db, None)
        db.commit()
        assert db.scalars(select(Lead).where(Lead.score.is_not(None))).first() is not None
        for key in ("kill_switch", "force_draft"):
            set_state(db, key, "1")
            db.commit()
            out = job_crm_sync(db, ctx)
            assert crm.writes == [] and out["synced"] == 0 and out["skipped_by_safety"] == 1, key
            set_state(db, key, "0")
            db.commit()
        out = job_crm_sync(db, ctx)  # both switches off: the same job now writes, so the test above proves something
        assert out["synced"] > 0 and len(crm.writes) == out["synced"]


def test_alembic_reads_the_same_settings_as_the_app(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENV_FILE", raising=False)
    assert resolve_url("sqlite:///x.db") == "sqlite:///x.db"  # -x url=... wins
    f = tmp_path / "prod.env"
    f.write_text("DATABASE_URL=postgresql+psycopg://u:p@db:5432/pipecairn\n")
    assert resolve_url(None, str(f)) == "postgresql+psycopg://u:p@db:5432/pipecairn"
    monkeypatch.setenv("ENV_FILE", str(f))
    assert resolve_url() == "postgresql+psycopg://u:p@db:5432/pipecairn"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///from-env.db")
    assert resolve_url() == "sqlite:///from-env.db"
    monkeypatch.delenv("DATABASE_URL")
    empty = tmp_path / "empty.env"
    empty.write_text("APP_NAME=x\n")
    with pytest.raises(RuntimeError) as e:
        resolve_url(None, str(empty))
    assert "DATABASE_URL is not set" in str(e.value)


def test_the_worker_reads_env_file_like_the_api(tmp_path, monkeypatch):
    f = tmp_path / "w.env"
    f.write_text("APP_NAME=from-the-worker-file\nLOG_LEVEL=WARNING\n")
    monkeypatch.setenv("ENV_FILE", str(f))
    monkeypatch.delenv("APP_NAME", raising=False)
    s = worker.load_settings()
    assert s.app_name == "from-the-worker-file" and s.log_level == "WARNING"


def test_the_worker_refuses_the_same_unsafe_settings_as_the_api(tmp_path, monkeypatch):
    f = tmp_path / "w.env"
    f.write_text("DEMO_MODE=false\nSESSION_SECRET=change-me-to-a-long-random-string\n")
    monkeypatch.setenv("ENV_FILE", str(f))
    monkeypatch.setattr(worker, "make_engine", lambda *_: pytest.fail("started the database before checking the settings"))
    from sendora_core.settings import ConfigError

    with pytest.raises(ConfigError):
        worker.main()


def test_spreadsheet_formulas_are_made_plain_text():
    assert csv_safe("=HYPERLINK(\"http://x\")") == "'=HYPERLINK(\"http://x\")"
    for first in "+-@\t\r":
        assert csv_safe(first + "x").startswith("'")
    assert csv_safe("Ava Alder") == "Ava Alder" and csv_safe(None) == "" and csv_safe(5) == "5"


def test_handoff_folders_never_collide_and_cells_are_neutralised(tmp_path, settings):
    h = BreezedocHandoff(settings, tmp_path)
    a = h.prepare(contract_pdf=b"A", title="Acme Faster replies", signers=[{"name": '=HYPERLINK("http://evil.example.test","x")', "email": "+a@x.example.test"}], folder_key="c1")
    b = h.prepare(contract_pdf=b"B", title="Acme Faster replies", signers=[{"name": "Bo", "email": "bo@x.example.test"}], folder_key="c2")
    assert a.package_path != b.package_path
    assert (Path(a.package_path) / "contract.pdf").read_bytes() == b"A" and (Path(b.package_path) / "contract.pdf").read_bytes() == b"B"
    csv_text = (Path(a.package_path) / "signers.csv").read_text()
    assert "'=HYPERLINK" in csv_text and ",'+a@x.example.test" in csv_text
    evil = h.prepare(contract_pdf=b"C", title="../../etc/passwd", signers=[], folder_key="../..")
    assert Path(evil.package_path).parent == tmp_path.resolve()


def proposal_flow(tmp_path, **kw):
    tmp_path.mkdir(parents=True, exist_ok=True)
    s = make_settings(tmp_path, seed_dir=str(DATA), **kw)
    c = TestClient(create_app(s), base_url="http://api.test")
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    assert c.post("/api/demo/reset").status_code == 200
    c.post("/api/demo/tick")
    lead = c.get("/api/leads?limit=1").json()["rows"][0]
    p = c.post("/api/proposals", json={"lead_id": lead["id"], "title": "Faster replies", "scope": ["Set up"], "price_cents": 100000, "call_notes": "slow"}).json()
    cid = c.post(f"/api/proposals/{p['id']}/contract").json()["id"]
    return c, cid, p


def test_esign_adapter_setting_is_honoured_and_folders_carry_the_contract_id(tmp_path):
    c, cid, _ = proposal_flow(tmp_path / "a", esign_adapter="seed")
    h = c.post(f"/api/contracts/{cid}/handoff").json()
    assert h["package_path"] == "" and "UNVERIFIED" in h["instructions"]  # the offline adapter writes no folder
    c2, cid2, _ = proposal_flow(tmp_path / "b", esign_adapter="breezedoc_handoff")
    h2 = c2.post(f"/api/contracts/{cid2}/handoff").json()
    assert h2["package_path"] == "(folder on the server)"
    folders = [p.name for p in (tmp_path / "b" / "handoff").iterdir() if p.is_dir()]
    assert len(folders) == 1 and folders[0].startswith(f"c{cid2}-")


def test_proposals_use_the_company_name_and_currency_from_settings(tmp_path):
    c, _, p = proposal_flow(tmp_path, company_name="Rivera Works", currency_symbol="EUR", proposal_valid_days=21)
    assert "From Rivera Works" in p["body_md"] and "EUR1,000.00" in p["body_md"] and "valid for 21 days" in p["body_md"]


# ---- the docs and .env.example list every setting ----

def example_names() -> set[str]:
    return {m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", (ROOT / ".env.example").read_text(), re.M)}


def test_env_example_lists_every_setting():
    from sendora_core.settings import BaseAppSettings

    names = {n.upper() for n in Settings.model_fields} | {n.upper() for n in BaseAppSettings.model_fields}
    missing = sorted(names - example_names())
    assert not missing, f"add these to .env.example: {missing}"


def test_the_environment_variables_doc_lists_every_setting():
    doc = (ROOT / "docs" / "04-ENVIRONMENT-VARIABLES.md").read_text()
    listed = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", doc))
    missing = sorted({n.upper() for n in Settings.model_fields} - listed)
    assert not missing, f"add these to docs/04-ENVIRONMENT-VARIABLES.md: {missing}"


def test_env_example_loads_as_it_is():
    s = Settings(_env_file=str(ROOT / ".env.example"))
    assert s.demo_mode is False and s.llm_call_budget is None and s.company_name == "Your Company"


# ---- the backup script ----

def fake_docker(tmp_path, dump: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    d = bin_dir / "docker"
    d.write_text("#!/bin/sh\ncase \"$*\" in\n  *pg_dump*) printf '%s' \"$FAKE_DUMP\" ;;\n  *tar*) printf 'tarbytes' ;;\nesac\n")
    d.chmod(d.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def run_backup(tmp_path, dump):
    out = tmp_path / "out"
    env = {"PATH": f"{fake_docker(tmp_path, dump)}:/usr/bin:/bin", "BACKUP_DIR": str(out), "FAKE_DUMP": dump, "HOME": str(tmp_path)}
    r = subprocess.run(["sh", str(ROOT / "deploy" / "hetzner" / "backup.sh")], cwd="/", env=env, capture_output=True, text=True)  # cwd is not the repo, as under cron
    return r, out


def test_backup_works_from_any_folder_and_keeps_the_dump(tmp_path):
    r, out = run_backup(tmp_path, "PGDMPdata")
    assert r.returncode == 0, r.stderr
    assert [p.read_text() for p in out.glob("pipecairn-*.dump")] == ["PGDMPdata"] and list(out.glob("handoff-*.tar"))
    assert not list(out.glob("*.partial"))


def test_backup_never_keeps_an_empty_dump(tmp_path):
    r, out = run_backup(tmp_path, "")
    assert r.returncode == 1 and "empty" in r.stderr
    assert not list(out.glob("*.dump")) and not list(out.glob("*.partial"))


def test_private_base_urls_need_the_owner_opt_in_and_plain_http_stays_off_the_internet(monkeypatch):
    import socket

    from pipecairn.adapters import base
    from sendora_core.adapters import AdapterError

    def resolves_to(*addrs):
        monkeypatch.setattr(base.socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 0, 0, "", (ip, 0)) for ip in addrs])

    resolves_to("10.0.0.5")
    with pytest.raises(AdapterError):
        base.safe_base_url("https://twenty.internal.example.test")  # refused by default
    assert base.safe_base_url("https://twenty.internal.example.test/", allow_private=True) == "https://twenty.internal.example.test"
    assert base.safe_base_url("http://twenty.internal.example.test", allow_private=True) == "http://twenty.internal.example.test"  # plain http on a private network
    resolves_to("93.184.216.34")
    assert base.safe_base_url("https://api.example.test", allow_private=True)  # the opt in does not break public addresses
    with pytest.raises(AdapterError):
        base.safe_base_url("http://api.example.test", allow_private=True)  # but plain http to the internet is still refused
    resolves_to("93.184.216.34", "10.0.0.5")
    with pytest.raises(AdapterError):
        base.safe_base_url("http://mixed.example.test", allow_private=True)
    s = Settings(_env_file=None, allow_private_base_urls=True)
    assert s.allow_private_base_urls is True


def test_a_domain_suppression_cannot_be_a_wildcard(session):
    from pipecairn.suppression import suppress_everywhere

    for bad in ("_.com", "%.com", "%", "a b.com", "-x.com"):
        with pytest.raises(ValueError):
            suppress_everywhere(session, "domain", bad, "test", "test")


# ---- the data folder comes from SEED_DIR, never from where the package happens to be installed ----

def installed_like(tmp_path, monkeypatch):
    """Like the Docker image: a copy of the data in its own folder, and nothing next to the code."""
    import shutil

    from pipecairn import seeding

    data = tmp_path / "app-data"
    data.mkdir()
    shutil.copy(DATA / "seed.json", data / "seed.json")
    monkeypatch.setattr(seeding, "REPO_DATA", tmp_path / "does-not-exist")
    monkeypatch.setattr(seeding, "DEFAULT_DATA", tmp_path / "does-not-exist")
    import pipecairn.api.app as app_module

    monkeypatch.setattr(app_module, "REPO_DATA", tmp_path / "does-not-exist")
    return data


def test_the_demo_runs_from_seed_dir_when_the_fallback_folder_is_missing(tmp_path, monkeypatch):
    data = installed_like(tmp_path, monkeypatch)
    s = make_settings(tmp_path, seed_dir=str(data))
    c = TestClient(create_app(s), base_url="http://api.test")
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    assert c.post("/api/demo/reset").json()["leads_imported"] > 100
    assert c.post("/api/demo/tick").status_code == 200  # the scripted replies read the same folder
    c.post("/api/demo/advance", json={"hours": 30})
    assert c.post("/api/demo/tick").status_code == 200


def test_a_missing_data_folder_is_a_plain_error_and_erases_nothing(tmp_path, monkeypatch):
    installed_like(tmp_path, monkeypatch)
    c = TestClient(create_app(make_settings(tmp_path, seed_dir="")), base_url="http://api.test")  # no SEED_DIR and no fallback
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    r = c.post("/api/demo/reset")
    assert r.status_code == 503 and "SEED_DIR" in r.json()["error"]["message"]
    assert c.post("/api/demo/tick").status_code == 200  # no scripted replies, but no crash either


def test_the_app_starts_with_demo_mode_and_no_data_folder_at_all(tmp_path, monkeypatch):
    installed_like(tmp_path, monkeypatch)
    app = create_app(make_settings(tmp_path))
    assert TestClient(app).get("/health").status_code == 200
