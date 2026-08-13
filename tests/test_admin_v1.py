import jwt

from app.config import get_settings
from app.models import AdminAuditLog, AdminJob, Article, OperationalSetting, User, utcnow
from app.services.admin_jobs import claim_next_job, execute_job


def _owner_headers(client):
    response = client.post("/auth/dev-login", json={"email": "owner@wajz.app"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_admin_v1_requires_exact_owner(client, auth_headers):
    assert client.get("/admin/v1/session").status_code == 401
    assert client.get("/admin/v1/session", headers=auth_headers).status_code == 403
    response = client.get("/admin/v1/session", headers=_owner_headers(client))
    assert response.status_code == 200
    assert response.json()["role"] == "owner"


def test_admin_owner_requires_aal2_when_enabled(client):
    headers = _owner_headers(client)
    settings = get_settings()
    original = settings.admin_require_mfa
    settings.admin_require_mfa = True
    try:
        assert client.get("/admin/v1/session", headers=headers).status_code == 403
        token = headers["Authorization"].removeprefix("Bearer ")
        claims = jwt.decode(token, options={"verify_signature": False})
        claims["aal"] = "aal2"
        aal2 = jwt.encode(claims, settings.secret_key, algorithm="HS256")
        response = client.get(
            "/admin/v1/session",
            headers={"Authorization": f"Bearer {aal2}"},
        )
        assert response.status_code == 200
    finally:
        settings.admin_require_mfa = original


def test_settings_update_is_typed_and_audited(client, db):
    headers = {**_owner_headers(client), "Idempotency-Key": "settings-test"}
    body = client.get("/admin/v1/settings", headers=headers).json()
    body["analytics_collection_enabled"] = True
    response = client.put("/admin/v1/settings", headers=headers, json=body)
    assert response.status_code == 200
    assert response.json()["analytics_collection_enabled"] is True
    assert db.get(OperationalSetting, "runtime_controls") is not None
    assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "settings.updated").count() == 1


def test_admin_mutations_require_idempotency_key(client):
    response = client.post("/admin/v1/translation/jobs", headers=_owner_headers(client))
    assert response.status_code == 400


def test_reprocessing_job_keeps_exact_article_scope(client, db, demo_data):
    headers = _owner_headers(client)
    selected, untouched = db.query(Article).order_by(Article.id).limit(2).all()
    for article in (selected, untouched):
        article.processing_status = "failed"
        article.status = "failed"
    db.commit()

    response = client.post(
        "/admin/v1/articles/reprocess-selected",
        headers={**headers, "Idempotency-Key": "scope-test"},
        json={"article_ids": [selected.id]},
    )
    assert response.status_code == 202
    job = db.query(AdminJob).one()
    assert job.arguments == {"article_ids": [selected.id]}
    db.expire_all()
    assert db.get(Article, selected.id).processing_status == "pending"
    assert db.get(Article, untouched.id).processing_status == "failed"


def test_admin_idempotency_reuses_job(client):
    headers = {**_owner_headers(client), "Idempotency-Key": "same-command"}
    first = client.post("/admin/v1/translation/jobs", headers=headers)
    second = client.post("/admin/v1/translation/jobs", headers=headers)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]


def test_admin_job_uses_bounded_backoff_then_fails(client, db):
    _owner_headers(client)
    owner = db.query(User).filter(User.email == "owner@wajz.app").one()
    job = AdminJob(job_type="unsupported", requested_by_id=owner.id)
    db.add(job)
    db.commit()

    for attempt in range(1, 4):
        if job.next_attempt_at is not None:
            job.next_attempt_at = utcnow()
            db.commit()
        claimed = claim_next_job(db)
        assert claimed is not None
        execute_job(db, claimed)
        db.refresh(job)
        assert job.attempts == attempt
        if attempt < 3:
            assert job.status == "queued"
            assert job.next_attempt_at is not None
        else:
            assert job.status == "failed"


def test_admin_job_can_be_cancelled(client):
    headers = {**_owner_headers(client), "Idempotency-Key": "cancel-job"}
    created = client.post("/admin/v1/translation/jobs", headers=headers)
    response = client.post(
        f"/admin/v1/jobs/{created.json()['id']}/cancel",
        headers={**headers, "Idempotency-Key": "cancel-request"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
