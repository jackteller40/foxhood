import time

import jwt
from fastapi.testclient import TestClient

from app.main import app
from app.settings import settings

client = TestClient(app)


def make_token(email="test@example.com", secret=None, aud="foxhood-api", iss="foxhood-web", exp_in=300):
    now = int(time.time())
    claims = {"sub": email, "email": email, "name": "Test User", "iat": now, "exp": now + exp_in,
              "aud": aud, "iss": iss}
    return jwt.encode(claims, secret or settings.api_jwt_secret, algorithm="HS256")


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_me_requires_token():
    assert client.get("/me").status_code == 401


def test_me_valid_token():
    r = client.get("/me", headers=bearer(make_token()))
    assert r.status_code == 200
    assert r.json() == {"email": "test@example.com", "name": "Test User"}


def test_wrong_secret_rejected():
    assert client.get("/me", headers=bearer(make_token(secret="y" * 64))).status_code == 401


def test_expired_token_rejected():
    assert client.get("/me", headers=bearer(make_token(exp_in=-10))).status_code == 401


def test_wrong_audience_rejected():
    assert client.get("/me", headers=bearer(make_token(aud="someone-else"))).status_code == 401


def test_not_on_invite_list():
    assert client.get("/me", headers=bearer(make_token(email="stranger@example.com"))).status_code == 403