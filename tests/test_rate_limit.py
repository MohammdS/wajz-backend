def test_dev_login_rate_limited(client):
    """RATE_LIMIT_AUTH=5 in the test environment."""
    body = {"email": "limited@wajz.app"}
    statuses = [client.post("/auth/dev-login", json=body).status_code for _ in range(6)]
    assert statuses[:5] == [200] * 5
    assert statuses[5] == 429
