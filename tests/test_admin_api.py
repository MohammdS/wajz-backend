def test_admin_requires_token(client):
    assert client.post("/admin/sources", json={}).status_code == 401
    assert client.get("/admin/ai-runs").status_code == 401


def test_create_and_update_source(client, admin_headers):
    body = {
        "name": "Test Feed",
        "rss_url": "https://example.com/rss.xml",
        "language": "en",
        "reliability_level": "high",
    }
    created = client.post("/admin/sources", json=body, headers=admin_headers)
    assert created.status_code == 201
    source_id = created.json()["id"]

    # Duplicate name rejected
    assert client.post("/admin/sources", json=body, headers=admin_headers).status_code == 409

    updated = client.put(
        f"/admin/sources/{source_id}",
        json={"reliability_level": "medium", "active": False},
        headers=admin_headers,
    )
    assert updated.json()["reliability_level"] == "medium"
    assert updated.json()["active"] is False

    # Deactivated source no longer appears publicly
    names = {s["name"] for s in client.get("/sources").json()}
    assert "Test Feed" not in names


def test_processing_run_and_ai_runs(client, admin_headers, demo_data):
    result = client.post("/admin/processing/run", headers=admin_headers).json()
    assert result["processed"] == 0  # demo fixture already processed everything

    runs = client.get("/admin/ai-runs", headers=admin_headers).json()
    assert len(runs) >= 1
    assert all(r["status"] in ("success", "error", "pending", "skipped") for r in runs)


def test_translation_backfill(client, admin_headers, demo_data):
    result = client.post("/admin/translations/run", headers=admin_headers).json()
    assert result["stories_checked"] == 5
    assert result["stories_attempted"] == 0
    assert result["stories_completed"] == 0


def test_ingestion_runs_listing(client, admin_headers):
    assert client.get("/admin/ingestion-runs", headers=admin_headers).json() == []


def test_regular_user_cannot_access_admin(client, auth_headers):
    assert client.get("/admin/overview", headers=auth_headers).status_code == 403


def test_viewer_is_read_only(client, db):
    login = client.post("/auth/dev-login", json={"email": "viewer@wajz.app"}).json()
    from app.models import User

    user = db.query(User).filter(User.email == "viewer@wajz.app").one()
    user.admin_role = "viewer"
    db.commit()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    assert client.get("/admin/overview", headers=headers).status_code == 200
    response = client.post(
        "/admin/sources",
        headers=headers,
        json={"name": "Blocked", "rss_url": "https://example.com/feed"},
    )
    assert response.status_code == 403


def test_admin_write_creates_audit_log(client, admin_headers):
    response = client.post(
        "/admin/studio/manual",
        headers=admin_headers,
        json={"title": "Reviewed draft", "status": "draft"},
    )
    assert response.status_code == 200
    logs = client.get("/admin/audit-logs", headers=admin_headers).json()
    assert logs[0]["action"] == "studio.manual_story"
