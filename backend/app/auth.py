"""Verify Supabase access tokens and resolve the caller's profile.

New Supabase projects sign JWTs with asymmetric keys published at the JWKS
endpoint; older projects use the shared HS256 secret. Both are supported.
"""
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import db
from .config import get_settings

ROLES = ("compliance_officer", "compliance_manager", "cco", "auditor")

_bearer = HTTPBearer(auto_error=False)


@dataclass
class User:
    id: str
    email: str
    role: str


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    url = f"{get_settings().supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise jwt.InvalidTokenError("HS256 token but SUPABASE_JWT_SECRET is not set")
            key = settings.supabase_jwt_secret
        else:
            key = _jwks_client().get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=[alg], audience="authenticated")
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to use the demo")
    claims = decode_token(creds.credentials)
    user_id, email = claims["sub"], claims.get("email", "")
    row = db.fetch_one(
        """
        insert into profiles (id, email) values (%s, %s)
        on conflict (id) do update set email = excluded.email
        returning role
        """,
        (user_id, email),
    )
    return User(id=user_id, email=email, role=row["role"])
