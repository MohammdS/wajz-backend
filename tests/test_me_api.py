def test_me_requires_auth(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me/preferences").status_code == 401
    assert client.get("/me/briefing/today").status_code == 401


def test_me_profile(client, auth_headers):
    data = client.get("/me", headers=auth_headers).json()
    assert data["email"] == "tester@wajz.app"
    assert data["display_name"] == "Tester"


def test_preferences_roundtrip(client, auth_headers):
    defaults = client.get("/me/preferences", headers=auth_headers).json()
    assert defaults["briefing_length"] == "10_minutes"
    assert defaults["onboarding_completed"] is False

    payload = {
        "preferred_language": "en",
        "topics": ["Technology", "Economy"],
        "regions": ["World", "Middle East"],
        "briefing_length": "5_minutes",
        "explanation_level": "beginner_friendly",
        "notification_preference": "daily_evening",
        "onboarding_completed": True,
    }
    updated = client.put("/me/preferences", json=payload, headers=auth_headers).json()
    assert updated["topics"] == ["Technology", "Economy"]
    assert updated["briefing_length"] == "5_minutes"
    assert updated["onboarding_completed"] is True

    again = client.get("/me/preferences", headers=auth_headers).json()
    assert again == updated


def test_preferences_validation(client, auth_headers):
    bad = {
        "preferred_language": "en",
        "topics": ["NotACategory"],
        "regions": [],
        "briefing_length": "10_minutes",
        "explanation_level": "standard",
        "notification_preference": "daily_morning",
    }
    assert client.put("/me/preferences", json=bad, headers=auth_headers).status_code == 422

    bad_length = dict(bad, topics=[], briefing_length="2_hours")
    assert client.put("/me/preferences", json=bad_length, headers=auth_headers).status_code == 422


def test_briefing_today(client, auth_headers, demo_data):
    data = client.get("/me/briefing/today", headers=auth_headers).json()
    assert data["briefing_length"] == "10_minutes"
    assert data["estimated_read_time_minutes"] == 10
    assert data["completion_message"] == "You are caught up."
    assert len(data["stories"]) >= 1
    # Requesting again returns the same briefing (stable for the day).
    again = client.get("/me/briefing/today", headers=auth_headers).json()
    assert [s["id"] for s in again["stories"]] == [s["id"] for s in data["stories"]]


def test_briefing_respects_length_change(client, auth_headers, demo_data):
    first = client.get("/me/briefing/today", headers=auth_headers).json()
    payload = {
        "preferred_language": "en",
        "topics": [],
        "regions": [],
        "briefing_length": "5_minutes",
        "explanation_level": "standard",
        "notification_preference": "daily_morning",
    }
    client.put("/me/preferences", json=payload, headers=auth_headers)
    second = client.get("/me/briefing/today", headers=auth_headers).json()
    assert second["briefing_length"] == "5_minutes"
    assert len(second["stories"]) <= max(len(first["stories"]), 7)


def test_briefing_uses_preferred_content_language(client, auth_headers, demo_data):
    payload = {
        "preferred_language": "ar",
        "topics": [],
        "regions": [],
        "briefing_length": "10_minutes",
        "explanation_level": "standard",
        "notification_preference": "daily_morning",
    }
    client.put("/me/preferences", json=payload, headers=auth_headers)
    stories = client.get("/me/briefing/today", headers=auth_headers).json()["stories"]
    assert any(story["content_language"] == "ar" for story in stories)


def test_saved_stories_flow(client, auth_headers, demo_data):
    story_id = client.get("/stories").json()["items"][0]["id"]

    assert client.get("/me/saved-stories", headers=auth_headers).json() == []

    response = client.post(f"/me/saved-stories/{story_id}", headers=auth_headers)
    assert response.status_code == 201

    saved = client.get("/me/saved-stories", headers=auth_headers).json()
    assert len(saved) == 1
    assert saved[0]["story"]["id"] == story_id
    assert saved[0]["story"]["saved"] is True

    # The saved flag shows up on public story endpoints when authenticated.
    detail = client.get(f"/stories/{story_id}", headers=auth_headers).json()
    assert detail["saved"] is True

    client.delete(f"/me/saved-stories/{story_id}", headers=auth_headers)
    assert client.get("/me/saved-stories", headers=auth_headers).json() == []


def test_save_unknown_story_404(client, auth_headers):
    assert client.post("/me/saved-stories/nope", headers=auth_headers).status_code == 404


def test_saved_stories_are_per_user(client, auth_headers, demo_data):
    story_id = client.get("/stories").json()["items"][0]["id"]
    client.post(f"/me/saved-stories/{story_id}", headers=auth_headers)

    other = client.post("/auth/dev-login", json={"email": "other@wajz.app"}).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get("/me/saved-stories", headers=other_headers).json() == []
