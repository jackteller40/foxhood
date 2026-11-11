"""Authentication and invite-list behaviour over HTTP."""
from db.repo import AdminRepo
from tests.helpers import bearer, make_token, service_token


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json()["db"] == "ok"


async def test_missing_token(client):
    assert (await client.get("/me")).status_code == 401


async def test_bad_tokens_rejected(client, invited_user):
    _, email, sub = await invited_user()
    for token in (make_token(email, sub, secret="y" * 64),   # wrong secret
                  make_token(email, sub, exp_in=-10),        # expired
                  make_token(email, sub, aud="someone-else")):  # wrong audience
        assert (await client.get("/me", headers=bearer(token))).status_code == 401


async def test_not_invited(client):
    r = await client.get("/me", headers=bearer(make_token("stranger@example.com", "g-stranger")))
    assert r.status_code == 403


async def test_first_login_creates_user_and_accepts_invite(client, invited_user, session):
    headers, email, sub = await invited_user(name="Casey")
    r = await client.get("/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == email and r.json()["name"] == "Casey"

    session.expire_all()  # read fresh rows, not this session's cached copies
    admin = AdminRepo(session)
    assert (await admin.find_user(email)).google_sub == sub
    invite = next(i for i in await admin.list_invites() if i.email == email)
    assert invite.accepted_at is not None


async def test_revoked_user_loses_access_on_next_request(client, invited_user, session):
    headers, email, _ = await invited_user()
    assert (await client.get("/me", headers=headers)).status_code == 200
    await AdminRepo(session).revoke(email)
    assert (await client.get("/me", headers=headers)).status_code == 403


async def test_other_google_account_with_same_email_rejected(client, invited_user):
    headers, email, _ = await invited_user()
    assert (await client.get("/me", headers=headers)).status_code == 200  # links the real account
    r = await client.get("/me", headers=bearer(make_token(email, "g-someone-else")))
    assert r.status_code == 403


async def test_internal_sign_in_check(client, invited_user):
    _, email, sub = await invited_user()
    svc = bearer(service_token())
    ok = await client.post("/internal/auth/check", headers=svc, json={"email": email, "google_sub": sub})
    assert ok.json() == {"allowed": True, "reason": "ok"}
    no = await client.post("/internal/auth/check", headers=svc,
                           json={"email": "stranger@example.com", "google_sub": "g-x"})
    assert no.json() == {"allowed": False, "reason": "not_invited"}
    # a normal user token can't call internal endpoints
    user_token = bearer(make_token(email, sub))
    r = await client.post("/internal/auth/check", headers=user_token, json={"email": email, "google_sub": sub})
    assert r.status_code == 401