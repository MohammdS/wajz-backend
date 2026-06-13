from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
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
        if not settings.supabase_jwt_secret:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Auth misconfigured")
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])


def get_or_create_user(db: Session, email: str, display_name: str | None, provider: str) -> User:
    settings = get_settings()
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        role = "super_admin" if email.lower() in settings.bootstrap_admin_emails else None
        user = User(
            email=email,
            display_name=display_name,
            auth_provider=provider,
            admin_role=role,
        )
        db.add(user)
        db.flush()
        db.add(UserPreferences(user_id=user.id))
        db.commit()
        db.refresh(user)
    elif user.admin_role is None and email.lower() in settings.bootstrap_admin_emails:
        user.admin_role = "super_admin"
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
        # Supabase tokens identify users by sub (uuid) and carry the email claim.
        email = payload.get("email")
        if not email:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing email claim")
        return get_or_create_user(db, email, payload.get("user_metadata", {}).get("name"), "supabase")

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
