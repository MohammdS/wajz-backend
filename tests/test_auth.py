from types import SimpleNamespace

import jwt
import pytest

from app import auth
from app.models import User


def test_disabled_dev_user_cannot_receive_new_token(client, db):
    user = User(email="disabled@example.com", account_status="disabled")
    db.add(user)
    db.commit()

    response = client.post("/auth/dev-login", json={"email": user.email})

    assert response.status_code == 403
    assert response.json()["detail"] == "Account is disabled"


def test_disabled_supabase_user_is_rejected_after_valid_token(client, db, monkeypatch):
    user = User(
        email="disabled@example.com",
        auth_provider="google",
        auth_subject="supabase-user-id",
        account_status="disabled",
    )
    db.add(user)
    db.commit()

    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(
            auth_mode="supabase",
            bootstrap_admin_emails=set(),
        ),
    )
    monkeypatch.setattr(
        auth,
        "_decode_token",
        lambda _token: {
            "sub": "supabase-user-id",
            "email": "disabled@example.com",
            "user_metadata": {"full_name": "Disabled User"},
            "app_metadata": {"provider": "google"},
        },
    )

    response = client.get(
        "/me",
        headers={"Authorization": "Bearer valid-supabase-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Account is disabled"


def test_banned_supabase_user_is_rejected_upstream(monkeypatch):
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(
            supabase_url="https://project.supabase.co",
            supabase_publishable_key="publishable-key",
            supabase_audience="authenticated",
        ),
    )
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "id": "supabase-user-id",
            "email": "disabled@example.com",
            "banned_until": "2099-01-01T00:00:00Z",
        },
    )
    monkeypatch.setattr(auth.httpx, "get", lambda *args, **kwargs: response)
    token = jwt.encode(
        {"sub": "supabase-user-id"},
        "legacy-test-secret-at-least-32-characters",
        algorithm="HS256",
    )

    with pytest.raises(jwt.InvalidTokenError, match="disabled"):
        auth._decode_supabase_token(token)


def test_asymmetric_supabase_token_is_also_checked_upstream(monkeypatch):
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(
            supabase_url="https://project.supabase.co",
            supabase_publishable_key="publishable-key",
            supabase_audience="authenticated",
        ),
    )
    monkeypatch.setattr(
        auth.jwt,
        "get_unverified_header",
        lambda _token: {"alg": "RS256", "kid": "signing-key"},
    )
    signing_key = SimpleNamespace(key=object())
    monkeypatch.setattr(
        auth,
        "PyJWKClient",
        lambda *args, **kwargs: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: signing_key
        ),
    )
    monkeypatch.setattr(auth.jwt, "decode", lambda *args, **kwargs: {"sub": "verified"})
    captured = {}

    def get_user(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "id": "supabase-user-id",
                "email": "active@example.com",
                "user_metadata": {},
                "app_metadata": {"provider": "google"},
            },
        )

    monkeypatch.setattr(auth.httpx, "get", get_user)

    payload = auth._decode_supabase_token("asymmetric-token")

    assert payload["sub"] == "supabase-user-id"
    assert captured["url"].endswith("/auth/v1/user")
    assert captured["headers"]["Authorization"] == "Bearer asymmetric-token"


def test_supabase_identity_uses_subject_and_updates_email(client, db, monkeypatch):
    user = User(
        email="old@example.com",
        auth_provider="supabase",
        auth_subject="supabase-user-id",
    )
    db.add(user)
    db.commit()

    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(
            auth_mode="supabase",
            bootstrap_admin_emails=set(),
        ),
    )
    monkeypatch.setattr(
        auth,
        "_decode_token",
        lambda _token: {
            "sub": "supabase-user-id",
            "email": "new@example.com",
            "user_metadata": {},
            "app_metadata": {"provider": "email"},
        },
    )

    response = client.get(
        "/me",
        headers={"Authorization": "Bearer valid-supabase-token"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == user.id
    assert response.json()["email"] == "new@example.com"
