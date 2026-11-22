from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from api import auth
from api.db import OAuthAccountRow, SessionRow, UserRow, session
from api.main import app

pytestmark = pytest.mark.anon  # real login flow: clients start unauthenticated

A = "/api/v1/auth"
PW = "correct horse battery"


@pytest.fixture
def client():
    return TestClient(app)


def _register(c, email="Ann@Example.com", pw=PW, **kw):
    return c.post(f"{A}/register", json={"email": email, "password": pw, **kw})


def test_register_logs_in_and_me_works(client):
    r = _register(client, display_name="Ann")
    assert r.status_code == 201
    assert r.json()["email"] == "ann@example.com"  # lowercased
    assert r.json()["display_name"] == "Ann"
    assert PW not in r.text and "argon2" not in r.text
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie
    assert client.get(f"{A}/me").json()["email"] == "ann@example.com"


def test_cookie_secure_when_configured(client, monkeypatch):
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    assert "secure" in _register(client, "s@example.com").headers["set-cookie"].lower()


def test_password_is_argon2_hashed_and_session_stored_hashed(client):
    r = _register(client, "h@example.com")
    token = client.cookies.get(auth.COOKIE)
    with session() as db:
        u = db.scalar(select(UserRow).where(UserRow.email == "h@example.com"))
        assert u.password_hash.startswith("$argon2")
        assert db.get(SessionRow, token) is None  # raw token is never the key
        assert db.get(SessionRow, auth._digest(token)).user_id == r.json()["id"]


@pytest.mark.parametrize(
    "email,pw", [("not-an-email", PW), ("a@example.com", "short"), ("a@b", PW)]
)
def test_register_validation(client, email, pw):
    assert _register(client, email, pw).status_code == 422


def test_duplicate_email_conflict_case_insensitive(client):
    assert _register(client, "d@example.com").status_code == 201
    assert _register(client, "D@EXAMPLE.COM").status_code == 409


def test_login_ok_and_generic_failure(client):
    _register(client, "l@example.com")
    c2 = TestClient(app)
    assert c2.post(f"{A}/login", json={"email": "L@example.com", "password": PW}).status_code == 200
    assert c2.get(f"{A}/me").status_code == 200
    bad_pw = TestClient(app).post(f"{A}/login", json={"email": "l@example.com", "password": "wrong-password"})
    unknown = TestClient(app).post(f"{A}/login", json={"email": "nobody@example.com", "password": PW})
    assert bad_pw.status_code == unknown.status_code == 401
    assert bad_pw.json() == unknown.json()  # no user enumeration


def test_oauth_only_account_cannot_password_login(client):
    with session() as db:
        db.add(UserRow(id="f" * 32, email="o@example.com", password_hash=None, display_name="o"))
        db.commit()
    r = client.post(f"{A}/login", json={"email": "o@example.com", "password": PW})
    assert r.status_code == 401 and r.json() == {"detail": "invalid email or password"}


def test_logout_revokes_session(client):
    _register(client, "x@example.com")
    token = client.cookies.get(auth.COOKIE)
    assert client.post(f"{A}/logout").status_code == 204
    assert client.get(f"{A}/me").status_code == 401
    stale = TestClient(app)  # replaying the old cookie must fail server-side
    stale.cookies.set(auth.COOKIE, token)
    assert stale.get(f"{A}/me").status_code == 401


def test_expired_session_rejected(client):
    _register(client, "e@example.com")
    with session() as db:
        db.execute(update(SessionRow).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
    assert client.get(f"{A}/me").status_code == 401


def test_session_lasts_30_days(client):
    _register(client, "t@example.com")
    with session() as db:
        row = db.get(SessionRow, auth._digest(client.cookies.get(auth.COOKIE)))
        assert timedelta(days=29, hours=23) < row.expires_at - datetime.now(UTC) <= timedelta(days=30)


def test_profile_name_and_password_change(client):
    _register(client, "p@example.com")
    other = TestClient(app)
    other.post(f"{A}/login", json={"email": "p@example.com", "password": PW})
    assert client.patch(f"{A}/profile", json={"display_name": " New "}).json()["display_name"] == "New"
    new = {"new_password": "another long one"}
    assert client.patch(f"{A}/profile", json=new).status_code == 400  # current password required
    assert client.patch(f"{A}/profile", json={**new, "current_password": "nope nope nope"}).status_code == 400
    assert client.patch(f"{A}/profile", json={**new, "current_password": PW}).status_code == 200
    assert client.patch(f"{A}/profile", json={"new_password": "tiny", "current_password": "another long one"}).status_code == 422
    assert other.get(f"{A}/me").status_code == 401  # other devices signed out
    assert client.get(f"{A}/me").status_code == 200
    fresh = TestClient(app)
    assert fresh.post(f"{A}/login", json={"email": "p@example.com", "password": PW}).status_code == 401
    assert fresh.post(f"{A}/login", json={"email": "p@example.com", "password": "another long one"}).status_code == 200


def test_profile_requires_auth(client):
    assert client.patch(f"{A}/profile", json={"display_name": "x"}).status_code == 401


def test_rate_limit_login_and_register(client, monkeypatch):
    monkeypatch.setenv("AUTH_RATE_LIMIT_PER_MIN", "3")
    codes = [client.post(f"{A}/login", json={"email": "z@example.com", "password": PW}).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]
    assert _register(client, "r@example.com").status_code == 429  # same IP, shared window


# ---- guard ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/v1/uploads"),
        ("post", "/api/v1/uploads/" + "a" * 32 + "/split"),
        ("post", "/api/v1/generations"),
        ("get", "/api/v1/generations/" + "a" * 32 + "/artifacts/glb"),
        ("post", "/api/v1/projects"),
        ("post", "/api/v1/projects/" + "a" * 32 + "/floors"),
        ("get", "/api/v1/projects/" + "a" * 32),
    ],
)
def test_existing_endpoints_require_login(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_health_and_auth_endpoints_stay_public(client):
    assert client.get("/health").status_code == 200
    assert client.get(f"{A}/providers").status_code == 200


def test_created_rows_record_owner(client):
    uid = _register(client, "own@example.com").json()["id"]
    pid = client.post("/api/v1/projects", json={"name": "House"}).json()["project_id"]
    from api.db import ProjectRow

    with session() as db:
        assert db.get(ProjectRow, pid).owner_id == uid


# ---- OAuth (provider exchange mocked; no network) ----------------------------------------


@pytest.fixture
def providers(monkeypatch):
    for p in ("GITHUB", "GOOGLE"):
        monkeypatch.setenv(f"{p}_CLIENT_ID", "id")
        monkeypatch.setenv(f"{p}_CLIENT_SECRET", "secret")


def _profile(monkeypatch, **kw):
    prof = auth.OAuthProfile(**{"provider_user_id": "123", "email": "g@example.com", "email_verified": True, "name": "Gee", **kw})

    async def fake(provider, request):
        return prof

    monkeypatch.setattr(auth, "fetch_profile", fake)


@pytest.mark.parametrize("provider", ["github", "google"])
def test_missing_provider_config_is_503(client, monkeypatch, provider):
    monkeypatch.delenv(f"{provider.upper()}_CLIENT_ID", raising=False)
    for path in (f"{A}/oauth/{provider}/login", f"{A}/oauth/{provider}/callback"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 503
        assert f"{provider.upper()}_CLIENT_ID" in r.json()["detail"]
    assert client.get(f"{A}/providers").json()[provider] is False


def test_unknown_provider_404(client):
    assert client.get(f"{A}/oauth/facebook/login", follow_redirects=False).status_code == 404


def test_providers_reports_configured(client, providers):
    assert client.get(f"{A}/providers").json() == {"github": True, "google": True}


def test_oauth_login_redirects_to_provider(client, providers, monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "http://localhost:3000")
    r = client.get(f"{A}/oauth/github/login?next=/viewer", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://github.com/login/oauth/authorize")
    assert "client_id=id" in loc
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A3000%2Fapi%2Fv1%2Fauth%2Foauth%2Fgithub%2Fcallback" in loc


def test_oauth_callback_creates_user_and_session(client, providers, monkeypatch):
    _profile(monkeypatch)
    r = client.get(f"{A}/oauth/google/callback", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/"
    me = client.get(f"{A}/me").json()
    assert me["email"] == "g@example.com" and me["has_password"] is False
    # same identity again -> same user, no duplicate
    c2 = TestClient(app)
    c2.get(f"{A}/oauth/google/callback", follow_redirects=False)
    assert c2.get(f"{A}/me").json()["id"] == me["id"]


def test_oauth_flow_keeps_auth_cookie(providers, monkeypatch):
    # regression: the OAuth-state middleware cookie once shared the name "session" and overwrote the login cookie
    _profile(monkeypatch)
    c = TestClient(app)
    c.get(f"{A}/oauth/google/login?next=/viewer", follow_redirects=False)  # puts "next" in the OAuth state
    r = c.get(f"{A}/oauth/google/callback", follow_redirects=False)
    names = [h.split("=")[0] for h in r.headers.get_list("set-cookie")]
    assert names.count(auth.COOKIE) == 1
    assert c.get(f"{A}/me").status_code == 200


def test_oauth_links_existing_oauth_only_user_by_verified_email(client, providers, monkeypatch):
    with session() as db:
        db.add(UserRow(id="a" * 32, email="link@example.com", password_hash=None, display_name="l"))
        db.commit()
    _profile(monkeypatch, provider_user_id="link-1", email="link@example.com")
    c2 = TestClient(app)
    c2.get(f"{A}/oauth/github/callback", follow_redirects=False)
    assert c2.get(f"{A}/me").json()["id"] == "a" * 32
    with session() as db:
        link = db.scalar(select(OAuthAccountRow).where(OAuthAccountRow.user_id == "a" * 32))
        assert (link.provider, link.provider_user_id) == ("github", "link-1")


def test_oauth_never_links_to_password_account(client, providers, monkeypatch):
    # register does not verify email, so linking would allow pre-account takeover
    uid = _register(client, "pw@example.com").json()["id"]
    _profile(monkeypatch, provider_user_id="pw-1", email="pw@example.com")
    c2 = TestClient(app)
    r = c2.get(f"{A}/oauth/github/callback", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login?error=email_exists"
    assert c2.get(f"{A}/me").status_code == 401
    with session() as db:
        assert db.scalar(select(OAuthAccountRow).where(OAuthAccountRow.user_id == uid)) is None
        assert len(db.scalars(select(UserRow).where(UserRow.email == "pw@example.com")).all()) == 1


def test_oauth_callback_with_bad_state_is_rejected(client, providers):
    with session() as db:
        before = len(db.scalars(select(UserRow)).all())
    # no login step first (no state in the session) and a forged state; no network is reached
    for qs in ("code=x&state=forged", "code=x"):
        r = client.get(f"{A}/oauth/github/callback?{qs}", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"].startswith("/login?error=")
    assert client.get(f"{A}/me").status_code == 401
    with session() as db:
        assert len(db.scalars(select(UserRow)).all()) == before


def test_oauth_callback_is_rate_limited(client, providers, monkeypatch):
    monkeypatch.setenv("AUTH_RATE_LIMIT_PER_MIN", "2")
    codes = [client.get(f"{A}/oauth/github/callback?code=x", follow_redirects=False).status_code for _ in range(3)]
    assert codes == [302, 302, 429]


def test_oauth_unverified_email_never_links(client, providers, monkeypatch):
    _register(client, "unv@example.com")
    _profile(monkeypatch, provider_user_id="unv-1", email="unv@example.com", email_verified=False)
    c2 = TestClient(app)
    r = c2.get(f"{A}/oauth/github/callback", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/login?error=")
    assert c2.get(f"{A}/me").status_code == 401


def test_oauth_provider_failure_redirects_to_login(client, providers, monkeypatch):
    async def boom(provider, request):
        raise RuntimeError("bad code")

    monkeypatch.setattr(auth, "fetch_profile", boom)
    r = client.get(f"{A}/oauth/github/callback", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/login?error=")


def test_safe_next_blocks_open_redirect():
    assert auth._safe_next("/viewer?x=1") == "/viewer?x=1"
    assert auth._safe_next("//evil.example") == "/"
    assert auth._safe_next("https://evil.example") == "/"
    assert auth._safe_next(None) == "/"
    assert auth._safe_next(r"/\evil.example") == "/"
    assert auth._safe_next("/%5Cevil.example") == "/"
