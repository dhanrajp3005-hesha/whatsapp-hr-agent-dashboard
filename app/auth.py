from dataclasses import dataclass
from typing import Optional

from fastapi import Request, Response, HTTPException, status
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.config import SESSION_SECRET, SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS
from app.db import get_anon_client
from app.logger import logger


@dataclass
class CurrentUser:
    id: str
    email: Optional[str] = None


def _serializer() -> URLSafeTimedSerializer:
    if not SESSION_SECRET:
        raise RuntimeError("SESSION_SECRET is not set. Check your .env file.")
    return URLSafeTimedSerializer(SESSION_SECRET, salt="whatsapp-hr-agent-session")


def create_session_cookie(response: Response, access_token: str, refresh_token: str) -> None:
    payload = {"access_token": access_token, "refresh_token": refresh_token}
    token = _serializer().dumps(payload)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=True,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def _read_session_cookie(request: Request) -> Optional[dict]:
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        return None

    try:
        return _serializer().loads(raw, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def _extract_bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization")
    if not header or not header.lower().startswith("bearer "):
        return None
    return header.split(" ", 1)[1].strip()


def _verify_access_token(access_token: str) -> CurrentUser:
    """
    Verifies a Supabase access token by asking Supabase Auth itself
    (client.auth.get_user), rather than decoding the JWT locally. This
    costs one extra network round trip per request, but works
    regardless of whether the project uses the legacy shared HS256
    secret or the newer asymmetric JWT signing keys Supabase now
    defaults new projects to - there's no separate secret to configure
    or get wrong on our end.
    """

    res = get_anon_client().auth.get_user(access_token)

    if not res or not res.user:
        raise ValueError("Token did not resolve to a user")

    return CurrentUser(id=res.user.id, email=res.user.email)


def get_current_user(request: Request) -> CurrentUser:
    """
    FastAPI dependency resolving the authenticated user for a request.
    Checks the Authorization header first (JSON/API clients), then falls
    back to the signed session cookie set after browser login. Raises
    401 if neither is present or valid - callers use this to gate every
    dashboard/API route.
    """

    token = _extract_bearer_token(request)

    if not token:
        session = _read_session_cookie(request)
        if session:
            token = session.get("access_token")

    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    try:
        return _verify_access_token(token)
    except Exception as exc:
        logger.info("Rejected invalid/expired access token: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired") from exc


def get_current_user_optional(request: Request) -> Optional[CurrentUser]:
    try:
        return get_current_user(request)
    except HTTPException:
        return None
