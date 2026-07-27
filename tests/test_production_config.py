import pytest

from app.config import Settings


def test_production_configuration_rejects_development_defaults():
    settings = Settings(
        environment="production",
        auth_mode="dev",
        database_url="sqlite:///wajz.db",
        cors_origins="http://localhost:3000",
    )

    with pytest.raises(RuntimeError, match="Invalid production configuration"):
        settings.validate_runtime()


def test_production_configuration_accepts_hardened_values():
    settings = Settings(
        environment="production",
        auth_mode="supabase",
        secret_key="a" * 64,
        supabase_url="https://project.supabase.co",
        supabase_publishable_key="publishable-key",
        database_url="postgresql+psycopg2://wajz:secret@db/wajz",
        admin_emails="security@wajz.app",
        cors_origins="https://app.wajz.app,https://admin.wajz.app",
        metrics_token="metrics-secret",
        ai_provider="gemini",
        gemini_api_key="gemini-secret",
        content_languages="en,ar",
        translation_languages="ar",
    )

    settings.validate_runtime()


def test_production_template_placeholders_are_rejected():
    settings = Settings(_env_file=".env.production.example")

    with pytest.raises(RuntimeError, match="must be replaced"):
        settings.validate_runtime()
