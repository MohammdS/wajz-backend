from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, status
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
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, display_name=display_name, auth_provider=provider)
        db.add(user)
        db.flush()
        db.add(UserPreferences(user_id=user.id))
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
    return user


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not x_admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin authorization required")
