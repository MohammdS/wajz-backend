def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness_does_not_require_database(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_checks_database(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


def test_request_id_is_returned(client):
    response = client.get("/health/live", headers={"X-Request-ID": "probe-123"})
    assert response.headers["X-Request-ID"] == "probe-123"


def test_metrics_export_prometheus_format(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "wajz_http_requests_total" in response.text
