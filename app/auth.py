from datetime import datetime, timedelta, timezone

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User, UserPreferences

bearer_scheme = HTTPBearer(auto_error=False)


def create_dev_token(user: User) -> str:
    settings = get_settings()
    payload = {
        "sub": user.id,
        "email": user.email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.token_expiry_hours),
        "iss": "wajz-dev",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def _decode_token(token: str) -> dict:
    settings = get_settings()
    if settings.auth_mode == "supabase":
        return _decode_supabase_token(token)
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=["HS256"],
        issuer="wajz-dev",
    )


def _decode_supabase_token(token: str) -> dict:
    settings = get_settings()
    base_url = settings.supabase_url.rstrip("/")
    if not base_url:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Auth misconfigured")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise jwt.InvalidTokenError("Invalid token header") from exc

    algorithm = header.get("alg")
    if algorithm in {"RS256", "ES256"} and header.get("kid"):
        signing_key = PyJWKClient(
            f"{base_url}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
            lifespan=600,
        ).get_signing_key_from_jwt(token)
        jwt.decode(
            token,
            signing_key.key,
            algorithms=[algorithm],
            audience=settings.supabase_audience,
            issuer=f"{base_url}/auth/v1",
            options={"require": ["exp", "sub", "role"]},
        )

    elif algorithm != "HS256":
        raise jwt.InvalidTokenError("Unsupported Supabase signing algorithm")

    if not settings.supabase_publishable_key:
        raise jwt.InvalidTokenError("Supabase publishable key is missing")

    # Confirm every token against Auth, including locally verified asymmetric
    # tokens. This closes the window where a banned or deleted Supabase user
    # could keep using an access token until its expiry. It also verifies
    # legacy HS256 tokens without sharing the project's JWT secret.
    try:
        response = httpx.get(
            f"{base_url}/auth/v1/user",
            headers={
                "apikey": settings.supabase_publishable_key,
                "Authorization": f"Bearer {token}",
            },
            timeout=5.0,
        )
        response.raise_for_status()
        user = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise jwt.InvalidTokenError("Supabase rejected the token") from exc
    banned_until = user.get("banned_until")
    try:
        is_banned = bool(
            banned_until
            and datetime.fromisoformat(str(banned_until).replace("Z", "+00:00"))
            > datetime.now(timezone.utc)
        )
    except ValueError:
        is_banned = True
    if not user.get("id") or not user.get("email") or is_banned:
        raise jwt.InvalidTokenError("Supabase user is disabled or incomplete")
    return {
        "sub": user["id"],
        "email": user["email"],
        "user_metadata": user.get("user_metadata") or {},
        "app_metadata": user.get("app_metadata") or {},
    }


def get_or_create_user(
    db: Session,
    email: str,
    display_name: str | None,
    provider: str,
    *,
    auth_subject: str | None = None,
) -> User:
    settings = get_settings()
    normalized_email = email.strip().lower()
    user = None
    if auth_subject:
        user = db.query(User).filter(User.auth_subject == auth_subject).first()
    if user is None:
        user = db.query(User).filter(User.email == normalized_email).first()
    if user is None:
        role = (
            "super_admin"
            if normalized_email in settings.bootstrap_admin_emails
            else None
        )
        user = User(
            email=normalized_email,
            display_name=display_name,
            auth_provider=provider,
            auth_subject=auth_subject,
            admin_role=role,
        )
        db.add(user)
        db.flush()
        db.add(UserPreferences(user_id=user.id))
        db.commit()
        db.refresh(user)
    else:
        changed = False
        if auth_subject and user.auth_subject is None:
            user.auth_subject = auth_subject
            changed = True
        if user.email != normalized_email:
            user.email = normalized_email
            changed = True
        if user.auth_provider != provider:
            user.auth_provider = provider
            changed = True
        if changed:
            db.commit()
            db.refresh(user)
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = _decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    settings = get_settings()
    if settings.auth_mode == "supabase":
        subject = payload.get("sub")
        email = payload.get("email")
        if not subject or not email:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Token missing identity claims",
            )
        metadata = payload.get("user_metadata") or {}
        app_metadata = payload.get("app_metadata") or {}
        user = get_or_create_user(
            db,
            email,
            metadata.get("full_name") or metadata.get("name"),
            app_metadata.get("provider") or "supabase",
            auth_subject=subject,
        )
    else:
        user = db.get(User, payload.get("sub", ""))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    if user.account_status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")
    user.last_active_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return user


ADMIN_ROLES = {"viewer", "editor", "super_admin"}
ROLE_LEVEL = {"viewer": 1, "editor": 2, "super_admin": 3}


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.admin_role not in ADMIN_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin authorization required")
    return user


def require_role(minimum_role: str):
    def dependency(user: User = Depends(require_admin)) -> User:
        if ROLE_LEVEL[user.admin_role or "viewer"] < ROLE_LEVEL[minimum_role]:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"{minimum_role} role required",
            )
        return user

    return dependency
