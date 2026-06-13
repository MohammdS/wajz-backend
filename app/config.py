from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Wajz API"
    database_url: str = "sqlite:///./wajz.db"

    # Auth
    auth_mode: str = "dev"  # "dev" | "supabase"
    secret_key: str = "dev-secret-key-not-for-production"
    supabase_jwt_secret: str = ""
    token_expiry_hours: int = 24 * 30

    # Admin
    admin_token: str = "dev-admin-token"
    admin_emails: str = "admin@wajz.app"
    cors_origins: str = (
        "http://127.0.0.1:3000,http://localhost:3000,"
        "http://127.0.0.1:3002,http://localhost:3002"
    )

    @property
    def bootstrap_admin_emails(self) -> set[str]:
        return {
            email.strip().lower()
            for email in self.admin_emails.split(",")
            if email.strip()
        }

    # AI
    ai_provider: str = "auto"  # auto | anthropic | zai | heuristic
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-4-8"
    zai_api_key: str = ""
    zai_model: str = "glm-4.5-air"
    zai_base_url: str = "https://api.z.ai/api/paas/v4"
    content_languages: str = "en,ar"

    @property
    def supported_content_languages(self) -> list[str]:
        return list(dict.fromkeys(
            language.strip().lower()
            for language in self.content_languages.split(",")
            if language.strip()
        ))

    # Worker
    ingestion_interval_minutes: int = 30

    # Rate limiting
    rate_limit_public: int = 120
    rate_limit_auth: int = 20
    rate_limit_window_seconds: int = 60

    # Clustering
    cluster_similarity_threshold: float = 0.40
    cluster_window_hours: int = 72

    # Briefing story counts by length preference
    briefing_story_counts: dict[str, int] = {
        "5_minutes": 7,
        "10_minutes": 12,
        "20_minutes": 25,
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
