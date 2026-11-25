"""Sign in, demo shortcuts and the refusal to start on unsafe settings."""

import pytest
from fastapi.testclient import TestClient

from conftest import DATA, make_settings
from pipecairn.api import routes_auth
from pipecairn.api.app import create_app
from pipecairn.config import Settings
from pipecairn.demo import reset as demo_reset
from sendora_core.auth import hash_password
from sendora_core.settings import ConfigError

REAL_SECRET = "test-only-Rt7Kq2Vw9Xm4Zc8Lb3Nf6Hy1Js5Dp0Ga2Ue7Tq4Wi9"
PASSWORD = "a-long-test-password-1"


def real_settings(tmp_path, **kw):
    base = dict(demo_mode=False, mode="draft", session_secret=REAL_SECRET, owner_password_hash=hash_password(PASSWORD), seed_dir=str(DATA))
    base.update(kw)
    return make_settings(tmp_path, **base)


def test_login_key_ignores_spaces_and_capitals(tmp_path):
    c = TestClient(create_app(real_settings(tmp_path)), base_url="http://api.test")
    variants = ["owner@example.test", " owner@example.test", "owner@example.test ", "OWNER@example.test", "\towner@example.test", "owner@example.test\n"]
    codes = [c.post("/api/auth/login", json={"email": v, "password": "wrong-password"}).status_code for v in variants]
    assert codes[:5] == [401] * 5 and codes[5] == 429  # the sixth try is refused whatever padding it uses


def test_login_accepts_a_padded_email_with_the_right_password(tmp_path):
    c = TestClient(create_app(real_settings(tmp_path)), base_url="http://api.test")
    r = c.post("/api/auth/login", json={"email": "  Owner@Example.test ", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["user"] == "owner@example.test"


def test_login_refuses_oversize_fields(tmp_path):
    c = TestClient(create_app(real_settings(tmp_path)), base_url="http://api.test")
    assert c.post("/api/auth/login", json={"email": "a" * 300 + "@x.test", "password": "x"}).status_code == 422
    assert c.post("/api/auth/login", json={"email": "owner@example.test", "password": "x" * 2000}).status_code == 422


def test_each_address_has_its_own_wider_limit(tmp_path):
    c = TestClient(create_app(real_settings(tmp_path, login_burst=2)), base_url="http://api.test")
    # a new email every time never gets a fresh set of tries: the per address bucket (30) runs out
    codes = [c.post("/api/auth/login", json={"email": f"user{i}@x.test", "password": "x"}).status_code for i in range(40)]
    assert codes[0] == 401 and 429 in codes[30:]


def test_unknown_accounts_cost_the_same_work_as_wrong_passwords(tmp_path, monkeypatch):
    calls = []
    real = routes_auth.verify_password_or_dummy
    monkeypatch.setattr(routes_auth, "verify_password_or_dummy", lambda pw, h: (calls.append(h), real(pw, h))[1])
    c = TestClient(create_app(real_settings(tmp_path)), base_url="http://api.test")
    assert c.post("/api/auth/login", json={"email": "nobody@x.test", "password": "x"}).status_code == 401
    assert calls == [None]  # a hash check against a throw away hash was still done


def test_a_real_owner_password_switches_every_demo_shortcut_off_even_in_demo_mode(tmp_path):
    s = real_settings(tmp_path, demo_mode=True)
    assert s.demo_shortcuts is False
    c = TestClient(create_app(s), base_url="http://api.test")
    for email in ("approver@example.test", "viewer@example.test", "owner@example.test"):
        assert c.post("/api/auth/login", json={"email": email, "password": "demo-password-1"}).status_code == 401
    token = c.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}).json()["token"]
    c.headers["x-session"] = token
    assert c.post("/api/demo/reset").status_code == 404 and c.post("/api/demo/tick").status_code == 404
    assert any("owner password" in p for p in s.problems())


def test_the_demo_reset_refuses_when_called_directly_with_an_owner_password(tmp_path):
    ctx_app = create_app(real_settings(tmp_path, demo_mode=True))
    ctx = ctx_app.state.ctx
    with ctx.factory() as session, pytest.raises(PermissionError):
        demo_reset(session, ctx)


def test_demo_with_no_owner_password_keeps_working(tmp_path):
    c = TestClient(create_app(make_settings(tmp_path, seed_dir=str(DATA))), base_url="http://api.test")
    r = c.post("/api/auth/login", json={"email": "approver@example.test", "password": "demo-password-1"})
    assert r.status_code == 200 and r.json()["role"] == "approver"


def test_the_app_refuses_an_example_secret_outside_demo_mode(tmp_path):
    with pytest.raises(ConfigError):
        create_app(real_settings(tmp_path, session_secret="change-me-to-a-long-random-string"))


def test_live_mode_refuses_the_placeholder_sender_identity(tmp_path):
    with pytest.raises(ConfigError) as e:
        create_app(real_settings(tmp_path, mode="live"))
    assert "SENDER_NAME" in str(e.value) and "COMPANY_ADDRESS" in str(e.value)
    ok = real_settings(tmp_path, mode="live", sender_name="Sam Rivera", company_name="Rivera Works", company_address="12 Main Street, Springfield, IL 62701, USA")
    assert not [p for p in ok.runtime_errors()]
    create_app(ok)  # starts


def test_placeholders_are_listed_in_problems_in_draft_mode_and_not_in_demo(tmp_path):
    draft = real_settings(tmp_path)
    assert any("COMPANY_ADDRESS" in p for p in draft.problems())
    assert not any("COMPANY_ADDRESS" in p for p in make_settings(tmp_path).problems())


def test_a_bad_reply_to_is_a_problem(tmp_path):
    assert any("REPLY_TO" in p for p in real_settings(tmp_path, reply_to="not an address").problems())


def test_an_empty_line_in_the_env_file_means_not_set(tmp_path):
    f = tmp_path / "e.env"
    f.write_text("LLM_CALL_BUDGET=\nLLM_BUDGET_USD=\nCALCOM_EVENT_TYPE_ID=\nDEFAULT_TIMEZONE=\n")
    s = Settings(_env_file=str(f))
    assert s.llm_call_budget is None and s.calcom_event_type_id == 0


def test_guesses_spread_over_many_addresses_still_run_out(tmp_path):
    app = create_app(real_settings(tmp_path, login_burst=2))
    codes = []
    for i in range(30):
        c = TestClient(app, base_url="http://api.test", client=(f"203.0.113.{i + 1}", 50000 + i))  # a different visitor each time
        codes.append(c.post("/api/auth/login", json={"email": "owner@example.test", "password": "wrong-password"}).status_code)
    assert codes[0] == 401 and 429 in codes[20:]  # the per account limit (20 here) stops them even though no single address is busy
    other = TestClient(app, base_url="http://api.test", client=("198.51.100.5", 40000))
    assert other.post("/api/auth/login", json={"email": "someone.else@example.test", "password": "x"}).status_code == 401  # other accounts are not affected


def test_me_reports_demo_only_while_the_demo_routes_exist(tmp_path):
    for settings, expected in ((make_settings(tmp_path), True), (real_settings(tmp_path / "r", demo_mode=True), False)):
        if settings.owner_password_hash:
            (tmp_path / "r").mkdir(exist_ok=True)
        c = TestClient(create_app(settings), base_url="http://api.test")
        email, pw = ("owner@example.test", "demo-password-1") if expected else ("owner@example.test", PASSWORD)
        c.headers["x-session"] = c.post("/api/auth/login", json={"email": email, "password": pw}).json()["token"]
        assert c.get("/api/auth/me").json()["demo_mode"] is expected  # the demo strip must not show buttons that answer 404
