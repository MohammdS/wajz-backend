from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Wajz API"
    database_url: str = "sqlite:///./wajz.db"

    # Auth
    auth_mode: str = "dev"  # "dev" | "supabase"
    secret_key: str = "dev-secret-key-not-for-production"
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_audience: str = "authenticated"
    # Legacy-only. Production verification uses JWKS or the Supabase Auth API.
    supabase_jwt_secret: str = ""
    token_expiry_hours: int = 24 * 30

    # Admin
    admin_emails: str = "admin@wajz.app"
    cors_origins: str = (
        "http://127.0.0.1:3000,http://localhost:3000,"
        "http://127.0.0.1:3002,http://localhost:3002"
    )

    # Observability. All external exporters are opt-in.
    environment: str = "development"
    release: str = "0.1.0"
    metrics_token: str = ""
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.0
    otel_exporter_otlp_endpoint: str = ""
    alert_webhook_url: str = ""
    alert_webhook_token: str = ""

    @property
    def bootstrap_admin_emails(self) -> set[str]:
        return {
            email.strip().lower()
            for email in self.admin_emails.split(",")
            if email.strip()
        }

    # AI
    ai_provider: str = "auto"  # auto | anthropic | gemini | zai | heuristic
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-4-8"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    zai_api_key: str = ""
    zai_model: str = "glm-4.5-air"
    zai_base_url: str = "https://api.z.ai/api/paas/v4"
    content_languages: str = "en,ar"
    translation_languages: str = "ar"
    translation_batch_size: int = 50

    @property
    def supported_content_languages(self) -> list[str]:
        return list(dict.fromkeys(
            language.strip().lower()
            for language in self.content_languages.split(",")
            if language.strip()
        ))

    @property
    def supported_translation_languages(self) -> list[str]:
        content_languages = set(self.supported_content_languages)
        return list(dict.fromkeys(
            language.strip().lower()
            for language in self.translation_languages.split(",")
            if language.strip().lower() in content_languages
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

    def validate_runtime(self) -> None:
        if self.environment.lower() != "production":
            return
        errors: list[str] = []
        placeholder_markers = (
            "replace-with",
            "your-project",
            "example.com",
            "change-me",
            "dev-secret",
        )

        def is_placeholder(value: str) -> bool:
            normalized = value.strip().lower()
            return not normalized or any(
                marker in normalized for marker in placeholder_markers
            )

        if self.auth_mode != "supabase":
            errors.append("AUTH_MODE must be supabase")
        if (
            not self.supabase_url.startswith("https://")
            or is_placeholder(self.supabase_url)
        ):
            errors.append("SUPABASE_URL must be a real HTTPS project URL")
        if is_placeholder(self.supabase_publishable_key):
            errors.append("SUPABASE_PUBLISHABLE_KEY must be replaced")
        if self.database_url.startswith("sqlite") or is_placeholder(self.database_url):
            errors.append("DATABASE_URL must use a production database")
        if len(self.secret_key) < 32 or is_placeholder(self.secret_key):
            errors.append("SECRET_KEY must be a unique value of at least 32 characters")
        origins = [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]
        if not origins or any(
            not origin.startswith("https://") or is_placeholder(origin)
            for origin in origins
        ):
            errors.append("CORS_ORIGINS must contain only real HTTPS origins")
        if (
            not self.bootstrap_admin_emails
            or self.bootstrap_admin_emails == {"admin@wajz.app"}
            or any(is_placeholder(email) for email in self.bootstrap_admin_emails)
        ):
            errors.append("ADMIN_EMAILS must contain a real bootstrap administrator")
        if is_placeholder(self.metrics_token):
            errors.append("METRICS_TOKEN must be replaced")
        if "ar" not in self.supported_content_languages:
            errors.append("CONTENT_LANGUAGES must include ar")
        if "ar" not in self.supported_translation_languages:
            errors.append("TRANSLATION_LANGUAGES must include ar")
        if self.ai_provider == "anthropic" and is_placeholder(self.anthropic_api_key):
            errors.append("ANTHROPIC_API_KEY must be replaced")
        if self.ai_provider == "gemini" and is_placeholder(self.gemini_api_key):
            errors.append("GEMINI_API_KEY must be replaced")
        if self.ai_provider == "zai" and is_placeholder(self.zai_api_key):
            errors.append("ZAI_API_KEY must be replaced")
        if errors:
            raise RuntimeError(
                "Invalid production configuration: " + "; ".join(errors)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
