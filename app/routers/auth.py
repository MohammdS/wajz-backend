from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import create_dev_token, get_or_create_user
from app.config import get_settings
from app.database import get_db
from app.rate_limit import rate_limit
from app.schemas import DevLoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/dev-login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("auth", "rate_limit_auth"))],
)
def dev_login(body: DevLoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Issue a local JWT. Available only when AUTH_MODE=dev (never in production)."""
    settings = get_settings()
    if settings.auth_mode != "dev":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    user = get_or_create_user(db, body.email, body.display_name, "dev")
    return TokenResponse(access_token=create_dev_token(user))
