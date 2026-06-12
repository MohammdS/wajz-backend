def test_admin_requires_token(client):
    assert client.post("/admin/sources", json={}).status_code == 403
    assert client.get("/admin/ai-runs").status_code == 403
    assert client.get("/admin/ai-runs", headers={"X-Admin-Token": "wrong"}).status_code == 403


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
    assert all(r["status"] in ("success", "error", "pending") for r in runs)


def test_ingestion_runs_listing(client, admin_headers):
    assert client.get("/admin/ingestion-runs", headers=admin_headers).json() == []
