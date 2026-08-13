from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class InstallationResponse(BaseModel):
    installation_id: str
    write_key: str


class PrivacyPolicyResponse(BaseModel):
    version: str
    language: Literal["ar", "en"]
    title: str
    markdown: str


class PrivacyAcceptanceIn(BaseModel):
    policy_version: str = Field(min_length=1, max_length=32)
    locale: Literal["ar", "en"] = "ar"


class AnalyticsEventIn(BaseModel):
    id: str = Field(pattern=r"^[a-fA-F0-9]{32}$")
    session_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")
    name: Literal[
        "session_started",
        "screen_viewed",
        "onboarding_started",
        "onboarding_completed",
        "authentication_completed",
        "story_impression",
        "story_opened",
        "story_saved",
        "source_link_clicked",
        "briefing_viewed",
        "briefing_completed",
        "ongoing_topic_viewed",
        "filter_selected",
    ]
    occurred_at: datetime
    entity_type: Literal["story", "source", "ongoing_topic", "briefing"] | None = None
    entity_id: str | None = Field(default=None, max_length=64)
    properties: dict[str, Any] = Field(default_factory=dict)
    locale: Literal["ar", "en"] | None = None
    platform: Literal["web", "android", "ios", "windows", "macos", "linux"] | None = None
    app_version: str | None = Field(default=None, max_length=24)

    @field_validator("properties")
    @classmethod
    def validate_properties(cls, value: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "screen",
            "action",
            "category",
            "region",
            "language",
            "result",
            "position",
            "briefing_length",
        }
        if set(value) - allowed:
            raise ValueError("Unsupported analytics properties")
        if len(value) > 8:
            raise ValueError("Too many analytics properties")
        for item in value.values():
            if not isinstance(item, (str, int, float, bool)) or len(str(item)) > 80:
                raise ValueError("Invalid analytics property value")
        return value


class AnalyticsBatchIn(BaseModel):
    events: list[AnalyticsEventIn] = Field(min_length=1, max_length=50)


class AnalyticsBatchOut(BaseModel):
    accepted: int
    duplicates: int = 0
    collection_enabled: bool
