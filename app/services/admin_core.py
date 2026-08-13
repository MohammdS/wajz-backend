from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.models import AdminAuditLog, AdminJob, User
from app.observability import request_id_context


SENSITIVE_KEYS = {"token", "secret", "password", "write_key", "api_key", "raw_text"}


def require_mutation_idempotency(request: Request) -> None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 128:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A valid Idempotency-Key header is required",
        )


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]" if key.lower() in SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value[:100]]
    if isinstance(value, str):
        return value[:500]
    return value


def audit(
    db: Session,
    actor: User,
    action: str,
    target_type: str,
    target_id: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AdminAuditLog(
            actor_user_id=actor.id,
            actor_email=actor.email,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=_redact(details or {}),
            request_id=request_id_context.get(),
        )
    )


def enqueue_job(
    db: Session,
    actor: User,
    job_type: str,
    arguments: dict,
    idempotency_key: str | None,
) -> tuple[AdminJob, bool]:
    normalized_key = idempotency_key.strip()[:128] if idempotency_key else None
    if normalized_key:
        existing = db.query(AdminJob).filter(AdminJob.idempotency_key == normalized_key).first()
        if existing is not None:
            return existing, False
    job = AdminJob(
        job_type=job_type,
        requested_by_id=actor.id,
        arguments=arguments,
        idempotency_key=normalized_key,
    )
    db.add(job)
    db.flush()
    audit(db, actor, "job.queued", "admin_job", job.id, {"job_type": job_type})
    db.commit()
    db.refresh(job)
    return job, True


def job_dict(job: AdminJob) -> dict:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "arguments": job.arguments or {},
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "result": job.result or {},
        "error_message": job.error_message,
        "cancel_requested": job.cancel_requested,
        "next_attempt_at": job.next_attempt_at,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }
