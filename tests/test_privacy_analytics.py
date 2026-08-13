import uuid

from app.models import AnalyticsEvent, OperationalSetting, PrivacyAcknowledgement


def _installation(client):
    response = client.post("/analytics/installations")
    assert response.status_code == 201
    data = response.json()
    return {
        "X-Wajz-Installation-ID": data["installation_id"],
        "X-Wajz-Analytics-Key": data["write_key"],
    }


def _enable_analytics(db):
    db.add(
        OperationalSetting(
            key="runtime_controls",
            value={"analytics_collection_enabled": True},
        )
    )
    db.commit()


def test_current_policy_and_acknowledgement_gate_events(client, db):
    headers = _installation(client)
    policy = client.get("/privacy-policy/current?language=en").json()
    event = {
        "id": uuid.uuid4().hex,
        "session_id": "session_12345678",
        "name": "story_opened",
        "occurred_at": "2026-08-13T01:00:00Z",
        "entity_type": "story",
        "entity_id": "story-1",
        "properties": {"category": "Technology", "position": 1},
        "locale": "en",
        "platform": "web",
        "app_version": "0.1.0",
    }
    _enable_analytics(db)
    blocked = client.post("/analytics/events/batch", headers=headers, json={"events": [event]})
    assert blocked.status_code == 403
    accepted = client.put(
        "/privacy/acceptance",
        headers=headers,
        json={"policy_version": policy["version"], "locale": "en"},
    )
    assert accepted.status_code == 200
    recorded = client.post("/analytics/events/batch", headers=headers, json={"events": [event]})
    assert recorded.status_code == 200
    assert recorded.json()["accepted"] == 1
    assert db.query(AnalyticsEvent).one().user_id is None


def test_analytics_rejects_freeform_or_sensitive_properties(client, db):
    headers = _installation(client)
    policy = client.get("/privacy-policy/current").json()
    client.put(
        "/privacy/acceptance",
        headers=headers,
        json={"policy_version": policy["version"], "locale": "ar"},
    )
    _enable_analytics(db)
    response = client.post(
        "/analytics/events/batch",
        headers=headers,
        json={
            "events": [
                {
                    "id": uuid.uuid4().hex,
                    "session_id": "session_12345678",
                    "name": "screen_viewed",
                    "occurred_at": "2026-08-13T01:00:00Z",
                    "properties": {"email": "person@example.com"},
                }
            ]
        },
    )
    assert response.status_code == 422
    assert db.query(AnalyticsEvent).count() == 0


def test_withdrawal_and_deletion_remove_identifiable_rows(client, db):
    headers = _installation(client)
    policy = client.get("/privacy-policy/current").json()
    client.put(
        "/privacy/acceptance",
        headers=headers,
        json={"policy_version": policy["version"], "locale": "ar"},
    )
    assert client.post("/privacy/withdraw", headers=headers).status_code == 200
    row = db.query(PrivacyAcknowledgement).one()
    assert row.withdrawn_at is not None
    assert client.delete("/analytics/data", headers=headers).status_code == 200
    assert db.query(PrivacyAcknowledgement).count() == 0


def test_sign_in_links_only_future_events_and_account_deletion(client, db, auth_headers):
    first = _installation(client)
    second = _installation(client)
    policy = client.get("/privacy-policy/current?language=en").json()
    for headers in (first, {**second, **auth_headers}):
        assert (
            client.put(
                "/privacy/acceptance",
                headers=headers,
                json={"policy_version": policy["version"], "locale": "en"},
            ).status_code
            == 200
        )
    _enable_analytics(db)

    def event(name: str) -> dict:
        return {
            "id": uuid.uuid4().hex,
            "session_id": "session_12345678",
            "name": name,
            "occurred_at": "2026-08-13T01:00:00Z",
            "properties": {},
        }

    anonymous = event("session_started")
    linked_first = event("story_opened")
    linked_second = event("briefing_viewed")
    client.post("/analytics/events/batch", headers=first, json={"events": [anonymous]})
    client.post(
        "/analytics/events/batch",
        headers={**first, **auth_headers},
        json={"events": [linked_first]},
    )
    client.post(
        "/analytics/events/batch",
        headers={**second, **auth_headers},
        json={"events": [linked_second]},
    )
    db.expire_all()
    assert db.get(AnalyticsEvent, anonymous["id"]).user_id is None
    assert db.get(AnalyticsEvent, linked_first["id"]).user_id is not None

    response = client.delete("/analytics/data", headers={**second, **auth_headers})
    assert response.status_code == 200
    db.expire_all()
    assert db.get(AnalyticsEvent, anonymous["id"]) is not None
    assert db.get(AnalyticsEvent, linked_first["id"]) is None
    assert db.get(AnalyticsEvent, linked_second["id"]) is None
