from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.admin_schemas_v1 import IngestionJobIn, SettingsPatch, UserStatusPatch
from app.auth import require_owner
from app.database import get_db
from app.models import (
    AIRun,
    AdminAuditLog,
    AdminJob,
    IngestionRun,
    OpenedStory,
    SavedStory,
    User,
)
from app.rate_limit import rate_limit
from app.services.admin_core import (
    audit,
    enqueue_job,
    job_dict,
    require_mutation_idempotency,
)
from app.services.operational_settings import (
    get_runtime_controls,
    update_runtime_controls,
)

router = APIRouter(
    prefix="/admin/v1",
    tags=["admin operations"],
    dependencies=[
        Depends(rate_limit("admin", "rate_limit_admin")),
        Depends(require_mutation_idempotency),
    ],
)


@router.get("/session")
def session(actor: User = Depends(require_owner)) -> dict:
    return {
        "id": actor.id,
        "email": actor.email,
        "display_name": actor.display_name,
        "role": "owner",
    }


@router.post("/ingestion/jobs", status_code=status.HTTP_202_ACCEPTED)
def queue_ingestion(
    body: IngestionJobIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    job, _ = enqueue_job(db, actor, "ingest_sources", body.model_dump(), idempotency_key)
    return job_dict(job)


@router.post("/translation/jobs", status_code=status.HTTP_202_ACCEPTED)
def queue_translations(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    job, _ = enqueue_job(db, actor, "translate_stories", {}, idempotency_key)
    return job_dict(job)


@router.get("/jobs")
def list_jobs(
    job_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(AdminJob).order_by(AdminJob.created_at.desc())
    if job_status:
        query = query.filter(AdminJob.status == job_status)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return {
        "items": [job_dict(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(AdminJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if job.status not in {"queued", "running"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only active jobs can be cancelled")
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
    audit(db, actor, "job.cancel_requested", "admin_job", job.id)
    db.commit()
    return job_dict(job)


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_job(
    job_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    source = db.get(AdminJob, job_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if source.status not in {"failed", "cancelled"}:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only failed or cancelled jobs can be retried"
        )
    job, _ = enqueue_job(db, actor, source.job_type, source.arguments, idempotency_key)
    return job_dict(job)


@router.get("/ingestion-runs")
def ingestion_runs(
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {
            "id": run.id,
            "status": run.status,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "sources_total": run.sources_total,
            "sources_failed": run.sources_failed,
            "articles_fetched": run.articles_fetched,
            "error_message": run.error_message,
        }
        for run in db.query(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)
    ]


@router.get("/ai-runs")
def ai_runs(
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {
            "id": run.id,
            "task_type": run.task_type,
            "status": run.status,
            "model_name": run.model_name,
            "input_reference_type": run.input_reference_type,
            "input_reference_id": run.input_reference_id,
            "created_at": run.created_at,
            "completed_at": run.completed_at,
            "error_message": run.error_message,
        }
        for run in db.query(AIRun).order_by(AIRun.created_at.desc()).limit(limit)
    ]


@router.get("/users")
def list_users(
    search: str | None = None,
    account_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(User).order_by(User.created_at.desc())
    if search:
        query = query.filter(
            or_(User.email.ilike(f"%{search}%"), User.display_name.ilike(f"%{search}%"))
        )
    if account_status:
        query = query.filter(User.account_status == account_status)
    total = query.count()
    users = query.offset(offset).limit(limit).all()
    items = []
    for user in users:
        items.append(
            {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "preferred_language": user.preferred_language,
                "account_status": user.account_status,
                "created_at": user.created_at,
                "last_active_at": user.last_active_at,
                "saved_count": db.query(func.count(SavedStory.story_id))
                .filter(SavedStory.user_id == user.id)
                .scalar()
                or 0,
                "opened_count": db.query(func.count(OpenedStory.story_id))
                .filter(OpenedStory.user_id == user.id)
                .scalar()
                or 0,
            }
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.patch("/users/{user_id}")
def update_user_status(
    user_id: str,
    body: UserStatusPatch,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == actor.id and body.account_status == "disabled":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The owner cannot disable their own account"
        )
    user.account_status = body.account_status
    audit(
        db, actor, "user.status_updated", "user", user.id, {"account_status": body.account_status}
    )
    db.commit()
    return {"id": user.id, "account_status": user.account_status}


@router.get("/settings")
def get_settings(
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    return get_runtime_controls(db).model_dump()


@router.put("/settings")
def update_settings(
    body: SettingsPatch,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    row = update_runtime_controls(db, body, actor)
    audit(
        db, actor, "settings.updated", "operational_settings", row.key, {"revision": row.revision}
    )
    db.commit()
    return {**body.model_dump(), "revision": row.revision}


@router.get("/audit-logs")
def audit_logs(
    action: str | None = None,
    target_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(AdminAuditLog).order_by(AdminAuditLog.created_at.desc())
    if action:
        query = query.filter(AdminAuditLog.action == action)
    if target_type:
        query = query.filter(AdminAuditLog.target_type == target_type)
    total = query.count()
    rows = query.offset(offset).limit(limit).all()
    return {
        "items": [
            {
                "id": row.id,
                "actor_email": row.actor_email,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "details": row.details,
                "request_id": row.request_id,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
