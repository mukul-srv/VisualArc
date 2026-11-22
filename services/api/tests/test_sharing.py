"""Sharing: role matrix, collaborator cap, pending-invite conversion, revocable view-only link."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.access import MAX_COLLABORATORS
from api.main import app

INPUT = Path(__file__).resolve().parents[3] / "fixtures" / "input"
P = "/api/v1/projects"
H = {"wall_height": 3000, "ceiling_height": 3000}


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("API_DATA_DIR", str(tmp_path))
    return TestClient(app)


@pytest.fixture
def owner(tmp_path, monkeypatch):
    return _client(tmp_path, monkeypatch)


def _user(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    return c, c.get("/api/v1/auth/me").json()["email"]


def _anon(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.cookies.clear()
    return c


def _floor(c, pid, name, elev):
    up = c.post("/api/v1/uploads", content=(INPUT / "fixture_a.dxf").read_bytes()).json()["upload_id"]
    return c.post(f"{P}/{pid}/floors", json={"upload_id": up, "floor_name": name, "elevation": elev, **H})


@pytest.fixture
def proj(owner):
    pid = owner.post(P, json={"name": "House"}).json()["project_id"]
    assert _floor(owner, pid, "Ground", 0).status_code == 201
    return pid


def _gid(c, pid):
    return c.get(f"{P}/{pid}").json()["floors"][0]["generation_id"]


def _grant(owner, pid, email, role):
    return owner.put(f"{P}/{pid}/access", json={"email": email, "role": role})


def test_role_matrix(proj, owner, tmp_path, monkeypatch):
    viewer, ve = _user(tmp_path, monkeypatch)
    editor, ee = _user(tmp_path, monkeypatch)
    stranger, _ = _user(tmp_path, monkeypatch)
    anon = _anon(tmp_path, monkeypatch)
    assert _grant(owner, proj, ve, "viewer").status_code == 200
    assert _grant(owner, proj, ee, "editor").status_code == 200
    gid = _gid(owner, proj)
    art = f"/api/v1/generations/{gid}/artifacts/glb"

    for c, role in ((owner, "owner"), (editor, "editor"), (viewer, "viewer")):
        r = c.get(f"{P}/{proj}")
        assert r.status_code == 200 and r.json()["role"] == role
        assert c.get(art).status_code == 200
        assert c.get(f"{P}/{proj}/versions").status_code == 200
        assert any(p["id"] == proj and p["role"] == role for p in c.get(P).json())
    for c in (stranger, anon):
        assert c.get(f"{P}/{proj}").status_code in (401, 404)
        assert c.get(art).status_code in (401, 404)
    assert stranger.get(f"{P}/{proj}").status_code == 404 and anon.get(f"{P}/{proj}").status_code == 401

    # mutations: editor yes, viewer no
    assert viewer.patch(f"{P}/{proj}", json={"name": "X"}).status_code == 404
    assert _floor(viewer, proj, "Up", 3000).status_code == 404
    assert viewer.post(f"{P}/{proj}/versions/1/restore").status_code == 404
    assert editor.patch(f"{P}/{proj}", json={"name": "Renamed"}).status_code == 200
    assert _floor(editor, proj, "Up", 3000).status_code == 201
    assert editor.post(f"{P}/{proj}/versions/1/restore").status_code == 201
    # owner only: delete, sharing
    for c in (editor, viewer, stranger):
        assert c.delete(f"{P}/{proj}").status_code == 404
        assert c.get(f"{P}/{proj}/access").status_code == 404
        assert _grant(c, proj, "x@example.com", "viewer").status_code == 404
        assert c.post(f"{P}/{proj}/link").status_code == 404
    assert owner.delete(f"{P}/{proj}").status_code == 204
    assert viewer.get(f"{P}/{proj}").status_code == 404


def test_link_read_only_and_revoke(proj, owner, tmp_path, monkeypatch):
    anon = _anon(tmp_path, monkeypatch)
    other = _client(tmp_path, monkeypatch)  # signed in, no grant
    pid2 = owner.post(P, json={"name": "Other"}).json()["project_id"]
    tok = owner.post(f"{P}/{proj}/link").json()["token"]
    assert owner.post(f"{P}/{proj}/link").json()["token"] == tok
    gid = _gid(owner, proj)
    for c in (anon, other):
        r = c.get(f"{P}/{proj}", params={"share": tok})
        assert r.status_code == 200 and r.json()["role"] == "viewer"
        assert c.get(f"/api/v1/generations/{gid}/artifacts/glb", params={"share": tok}).status_code == 200
        assert c.get(f"/api/v1/generations/{gid}/artifacts/meta", params={"share": tok}).status_code == 200
        assert c.get(f"{P}/{pid2}", params={"share": tok}).status_code in (401, 404)  # other project
    # no mutation or sharing management through the link
    assert anon.patch(f"{P}/{proj}", json={"name": "X"}, params={"share": tok}).status_code == 401
    assert other.patch(f"{P}/{proj}", json={"name": "X"}, params={"share": tok}).status_code == 404
    assert other.get(f"{P}/{proj}/access", params={"share": tok}).status_code == 404
    assert anon.get(f"{P}/{proj}", params={"share": "bogus"}).status_code == 404

    assert owner.delete(f"{P}/{proj}/link").status_code == 204
    for c in (anon, other):
        assert c.get(f"{P}/{proj}", params={"share": tok}).status_code == 404
        assert c.get(f"/api/v1/generations/{gid}/artifacts/glb", params={"share": tok}).status_code == 404


def test_role_change_and_remove(proj, owner, tmp_path, monkeypatch):
    c, email = _user(tmp_path, monkeypatch)
    _grant(owner, proj, email, "viewer")
    assert c.patch(f"{P}/{proj}", json={"name": "X"}).status_code == 404
    v = _grant(owner, proj, email.upper(), "editor").json()
    assert [x["role"] for x in v["collaborators"]] == ["editor"]
    assert c.patch(f"{P}/{proj}", json={"name": "X"}).status_code == 200
    assert owner.delete(f"{P}/{proj}/access", params={"email": email}).json()["collaborators"] == []
    assert c.get(f"{P}/{proj}").status_code == 404
    assert owner.delete(f"{P}/{proj}/access", params={"email": email}).status_code == 404
    assert _grant(owner, proj, "owner-self@example.com", "viewer").status_code == 200
    me = owner.get("/api/v1/auth/me").json()["email"]
    assert _grant(owner, proj, me, "viewer").status_code == 422


def test_cap_counts_grants_and_invites(proj, owner, tmp_path, monkeypatch):
    _, real = _user(tmp_path, monkeypatch)
    _grant(owner, proj, real, "viewer")
    for i in range(MAX_COLLABORATORS - 1):
        assert _grant(owner, proj, f"p{i}@example.com", "viewer").status_code == 200
    r = _grant(owner, proj, "one-too-many@example.com", "viewer")
    assert r.status_code == 422 and str(MAX_COLLABORATORS) in r.json()["detail"]
    # changing an existing role is not a new slot
    assert _grant(owner, proj, "p0@example.com", "editor").status_code == 200
    owner.delete(f"{P}/{proj}/access", params={"email": "p0@example.com"})
    assert _grant(owner, proj, "one-too-many@example.com", "viewer").status_code == 200


def test_password_register_does_not_claim_invite(proj, owner, tmp_path, monkeypatch):
    email = "newcomer@example.com"
    _grant(owner, proj, email, "editor")
    c = _anon(tmp_path, monkeypatch)
    assert c.post("/api/v1/auth/register", json={"email": email, "password": "correct horse 1"}).status_code == 201
    assert c.get(f"{P}/{proj}").status_code == 404  # unverified email: no access
    v = owner.get(f"{P}/{proj}/access").json()
    assert v["invites"] == [{"email": email, "role": "editor"}] and v["collaborators"] == []
    # owner invites again after registration: real grant, stale invite gone
    v = _grant(owner, proj, email, "viewer").json()
    assert v["invites"] == [] and [x["email"] for x in v["collaborators"]] == [email]
    assert c.get(f"{P}/{proj}").json()["role"] == "viewer"


def test_removed_editor_loses_artifacts_of_own_floors(proj, owner, tmp_path, monkeypatch):
    editor, ee = _user(tmp_path, monkeypatch)
    _grant(owner, proj, ee, "editor")
    assert _floor(editor, proj, "Up", 3000).status_code == 201
    mine = next(f for f in editor.get(f"{P}/{proj}").json()["floors"] if f["name"] == "Up")["generation_id"]
    art = f"/api/v1/generations/{mine}/artifacts/glb"
    assert editor.get(art).status_code == 200
    owner.delete(f"{P}/{proj}/access", params={"email": ee})
    assert editor.get(art).status_code == 404 and owner.get(art).status_code == 200


def test_pending_invite_converts_on_oauth_first_login(proj, owner):
    from api.auth import OAuthProfile, user_for_profile

    email = "oauth-new@example.com"
    _grant(owner, proj, email, "viewer")
    user = user_for_profile("github", OAuthProfile("gh-1", email, True, "N"))
    assert not isinstance(user, str)
    v = owner.get(f"{P}/{proj}/access").json()
    assert v["invites"] == [] and v["collaborators"][0]["user_id"] == user.id
