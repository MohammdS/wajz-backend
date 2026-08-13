import hashlib
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import bearer_scheme, get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import (
    AnalyticsEvent,
    AnalyticsInstallation,
    PrivacyAcknowledgement,
    User,
    utcnow,
)
from app.privacy_schemas import (
    AnalyticsBatchIn,
    AnalyticsBatchOut,
    InstallationResponse,
    PrivacyAcceptanceIn,
    PrivacyPolicyResponse,
)
from app.rate_limit import rate_limit
from app.services.operational_settings import get_runtime_controls

router = APIRouter(
    tags=["privacy and analytics"],
    dependencies=[Depends(rate_limit("analytics", "rate_limit_analytics"))],
)
CONTENT_ROOT = Path(__file__).resolve().parents[1] / "content" / "privacy"


def _secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _installation(
    installation_id: str = Header(alias="X-Wajz-Installation-ID"),
    write_key: str = Header(alias="X-Wajz-Analytics-Key"),
    db: Session = Depends(get_db),
) -> AnalyticsInstallation:
    installation = db.get(AnalyticsInstallation, installation_id)
    if (
        installation is None
        or installation.disabled_at is not None
        or not secrets.compare_digest(installation.secret_hash, _secret_hash(write_key))
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid analytics installation")
    installation.last_seen_at = utcnow()
    return installation


def _optional_user(
    credentials: HTTPAuthorizationCredentials | None,
    db: Session,
) -> User | None:
    if credentials is None:
        return None
    return get_current_user(credentials, db)


@router.get("/privacy-policy/current", response_model=PrivacyPolicyResponse)
def current_policy(
    language: str = Query(default="ar", pattern="^(ar|en)$"),
) -> PrivacyPolicyResponse:
    version = get_settings().privacy_policy_version
    path = CONTENT_ROOT / f"{version}.{language}.md"
    if not path.is_file():
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Privacy policy unavailable")
    return PrivacyPolicyResponse(
        version=version,
        language=language,
        title="إشعار الخصوصية" if language == "ar" else "Privacy Notice",
        markdown=path.read_text(encoding="utf-8"),
    )


@router.post(
    "/analytics/installations",
    response_model=InstallationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_installation(db: Session = Depends(get_db)) -> InstallationResponse:
    write_key = secrets.token_urlsafe(32)
    installation = AnalyticsInstallation(secret_hash=_secret_hash(write_key))
    db.add(installation)
    db.commit()
    return InstallationResponse(installation_id=installation.id, write_key=write_key)


@router.put("/privacy/acceptance")
def accept_policy(
    body: PrivacyAcceptanceIn,
    installation: AnalyticsInstallation = Depends(_installation),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    if body.policy_version != settings.privacy_policy_version:
        raise HTTPException(status.HTTP_409_CONFLICT, "A newer privacy policy is required")
    user = _optional_user(credentials, db)
    active = (
        db.query(PrivacyAcknowledgement)
        .filter(
            PrivacyAcknowledgement.installation_id == installation.id,
            PrivacyAcknowledgement.policy_version == body.policy_version,
            PrivacyAcknowledgement.withdrawn_at.is_(None),
        )
        .first()
    )
    if active is None:
        active = PrivacyAcknowledgement(
            installation_id=installation.id,
            user_id=user.id if user else None,
            policy_version=body.policy_version,
            locale=body.locale,
        )
        db.add(active)
    elif user is not None and active.user_id is None:
        active.user_id = user.id
    db.commit()
    return {"accepted": True, "policy_version": body.policy_version}


@router.post("/privacy/withdraw")
def withdraw_policy(
    installation: AnalyticsInstallation = Depends(_installation),
    db: Session = Depends(get_db),
) -> dict:
    rows = (
        db.query(PrivacyAcknowledgement)
        .filter(
            PrivacyAcknowledgement.installation_id == installation.id,
            PrivacyAcknowledgement.withdrawn_at.is_(None),
        )
        .all()
    )
    now = utcnow()
    for row in rows:
        row.withdrawn_at = now
    db.commit()
    return {"accepted": False}


@router.delete("/analytics/data")
def delete_analytics_data(
    installation: AnalyticsInstallation = Depends(_installation),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> dict:
    user = _optional_user(credentials, db)
    event_scope = AnalyticsEvent.installation_id == installation.id
    acknowledgement_scope = PrivacyAcknowledgement.installation_id == installation.id
    if user is not None:
        event_scope = or_(event_scope, AnalyticsEvent.user_id == user.id)
        acknowledgement_scope = or_(
            acknowledgement_scope,
            PrivacyAcknowledgement.user_id == user.id,
        )
    db.query(AnalyticsEvent).filter(event_scope).delete(synchronize_session=False)
    db.query(PrivacyAcknowledgement).filter(acknowledgement_scope).delete(synchronize_session=False)
    installation.disabled_at = utcnow()
    db.commit()
    return {"deleted": True}


@router.post("/analytics/events/batch", response_model=AnalyticsBatchOut)
def record_events(
    body: AnalyticsBatchIn,
    installation: AnalyticsInstallation = Depends(_installation),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AnalyticsBatchOut:
    if not get_runtime_controls(db).analytics_collection_enabled:
        db.commit()
        return AnalyticsBatchOut(accepted=0, collection_enabled=False)
    acknowledged = (
        db.query(PrivacyAcknowledgement.id)
        .filter(
            PrivacyAcknowledgement.installation_id == installation.id,
            PrivacyAcknowledgement.policy_version == get_settings().privacy_policy_version,
            PrivacyAcknowledgement.withdrawn_at.is_(None),
        )
        .first()
    )
    if acknowledged is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Privacy acknowledgement required")
    user = _optional_user(credentials, db)
    accepted = 0
    duplicates = 0
    for item in body.events:
        if db.get(AnalyticsEvent, item.id) is not None:
            duplicates += 1
            continue
        db.add(
            AnalyticsEvent(
                id=item.id.lower(),
                installation_id=installation.id,
                user_id=user.id if user else None,
                session_id=item.session_id,
                name=item.name,
                occurred_at=item.occurred_at.replace(tzinfo=None),
                entity_type=item.entity_type,
                entity_id=item.entity_id,
                properties=item.properties,
                locale=item.locale,
                platform=item.platform,
                app_version=item.app_version,
            )
        )
        accepted += 1
    db.commit()
    return AnalyticsBatchOut(
        accepted=accepted,
        duplicates=duplicates,
        collection_enabled=True,
    )
