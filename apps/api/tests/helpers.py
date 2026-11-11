import time

import jwt


def make_token(email: str | None, sub: str, *, aud: str = "foxhood-api", secret: str | None = None,
               exp_in: int = 300, name: str = "Test User") -> str:
    from app.settings import settings
    now = int(time.time())
    claims = {"sub": sub, "iat": now, "exp": now + exp_in, "aud": aud, "iss": "foxhood-web", "name": name}
    if email:
        claims["email"] = email
    return jwt.encode(claims, secret or settings.api_jwt_secret, algorithm="HS256")


def service_token(**kwargs) -> str:
    return make_token(None, "foxhood-web", aud="foxhood-internal", **kwargs)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}