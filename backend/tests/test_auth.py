from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings
from app.models import CV, InterviewSession, Message, User
from tests.conftest import PASSWORD, authed, register

SETUP = {"role": "Python developer", "level": "junior"}


def test_register_login_and_me(anon):
    token = register(anon, "Ana@Example.com")
    me = authed(token).get("/users/me").json()
    assert me["email"] == "ana@example.com" and me["is_guest"] is False and me["is_admin"] is False

    res = anon.post("/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer" and body["user"]["email"] == "ana@example.com"
    exp = datetime.fromisoformat(body["expires_at"])
    assert timedelta(hours=23) < exp - datetime.now(UTC) <= timedelta(hours=24)  # NFR-05


def test_password_is_hashed_with_bcrypt(anon, db):
    register(anon)
    user = db.query(User).one()
    assert user.password_hash.startswith("$2") and PASSWORD not in user.password_hash


def test_duplicate_email_and_bad_login(anon):
    register(anon)
    assert anon.post("/auth/register", json={"email": "USER@example.com", "password": PASSWORD}).status_code == 409
    res = anon.post("/auth/login", json={"email": "user@example.com", "password": "wrong-pass1"})
    assert res.status_code == 401 and res.json()["error"] == "Incorrect email or password"
    assert anon.post("/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}).status_code == 401


def test_password_rules(anon):
    for pw in ("short1!", "onlyletters", "12345678", "a1" * 40):
        res = anon.post("/auth/register", json={"email": "p@example.com", "password": pw})
        assert res.status_code == 422, pw
    assert anon.post("/auth/register", json={"email": "not-an-email", "password": PASSWORD}).status_code == 422


def test_bad_and_expired_tokens(anon, db):
    assert anon.get("/users/me").status_code == 401
    assert authed("garbage").get("/users/me").status_code == 401
    register(anon)
    user = db.query(User).one()
    expired = jwt.encode({"sub": str(user.id), "exp": datetime.now(UTC) - timedelta(minutes=1)},
                         get_settings().jwt_secret, algorithm="HS256")
    res = authed(expired).get("/users/me")
    assert res.status_code == 401 and "expired" in res.json()["error"]
    wrong_key = jwt.encode({"sub": str(user.id), "exp": datetime.now(UTC) + timedelta(hours=1)}, "x" * 32,
                           algorithm="HS256")
    assert authed(wrong_key).get("/users/me").status_code == 401


def test_token_of_deleted_user_is_rejected(client):
    assert client.request("DELETE", "/users/me", json={"password": PASSWORD}).status_code == 204
    assert client.get("/users/me").status_code == 401


def test_admin_emails_become_admins(anon, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", ["Boss@Example.com"])
    token = register(anon, "boss@example.com")
    assert authed(token).get("/users/me").json()["is_admin"] is True


def test_production_requires_strong_jwt_secret(monkeypatch):
    import pytest

    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "change-me")
    try:
        with pytest.raises(RuntimeError):
            get_settings()
        monkeypatch.setenv("JWT_SECRET", "k" * 40)
        assert get_settings().environment == "production"
    finally:
        get_settings.cache_clear()


# ---------- guests (FR-02) ----------

def test_guest_gets_one_short_interview(guest):
    first = guest.post("/sessions", json=SETUP)
    assert first.status_code == 201
    assert first.json()["question_limit"] == get_settings().guest_question_limit
    second = guest.post("/sessions", json=SETUP)
    assert second.status_code == 403 and "account" in second.json()["error"]


def test_expired_guests_are_purged(anon, guest, db):
    sid = guest.post("/sessions", json=SETUP).json()["session_id"]
    g = db.query(User).filter_by(is_guest=True).one()
    g.created_at = datetime.now(UTC) - timedelta(hours=25)
    db.commit()
    anon.post("/auth/guest")  # creating a guest triggers the clean-up
    db.expire_all()
    assert db.get(InterviewSession, sid) is None
    assert db.query(Message).count() == 0
    assert db.query(User).filter_by(is_guest=True).count() == 1


# ---------- account deletion (FR-54, UC-04) ----------

def test_delete_account_removes_everything(client, db):
    from tests.conftest import make_pdf

    client.post("/cv", files={"file": ("cv.pdf", make_pdf("Jane Doe software engineer " * 5), "application/pdf")})
    sid = client.post("/sessions", json=SETUP).json()["session_id"]
    client.post(f"/sessions/{sid}/answer", json={"text": "answer"})

    res = client.request("DELETE", "/users/me", json={"password": "wrong-pass1"})
    assert res.status_code == 403
    assert client.request("DELETE", "/users/me", json={"password": PASSWORD}).status_code == 204

    db.expire_all()
    assert db.query(User).count() == 0
    assert db.query(CV).count() == 0
    assert db.query(InterviewSession).count() == 0
    assert db.query(Message).count() == 0


def test_guest_can_delete_without_password(guest, db):
    assert guest.request("DELETE", "/users/me", json={}).status_code == 204
    assert db.query(User).count() == 0


def test_my_sessions_lists_newest_first_with_scores(client):
    a = client.post("/sessions", json=SETUP).json()["session_id"]
    b = client.post("/sessions", json={**SETUP, "session_type": "hr"}).json()["session_id"]
    client.post(f"/sessions/{a}/answer", json={"text": "x"})
    client.post(f"/sessions/{a}/end")
    rows = client.get("/users/me/sessions").json()
    assert [r["id"] for r in rows] == [b, a]
    assert rows[0]["overall_score"] is None and rows[1]["overall_score"] == 7.0
    assert rows[0]["session_type"] == "hr"
