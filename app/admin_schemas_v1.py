from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

from app.services.operational_settings import RuntimeControls


class StoryPatch(BaseModel):
    headline: str | None = Field(default=None, min_length=1, max_length=500)
    summary: str | None = None
    what_happened: str | None = None
    why_it_matters: str | None = None
    key_facts: list[str] | None = None
    unclear_points: list[str] | None = None
    source_comparison: list[dict] | None = None
    category: str | None = None
    region: str | None = None
    importance_score: float | None = Field(default=None, ge=0, le=1)
    confidence_label: str | None = None
    editor_notes: str | None = None


class StoryAction(BaseModel):
    action: Literal["publish", "archive", "reject", "submit_review"]


class TopicTranslationIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=2000)


class OngoingTopicIn(BaseModel):
    category: str | None = None
    priority: int = Field(default=0, ge=-100, le=100)
    expires_at: datetime | None = None
    translations: dict[Literal["ar", "en"], TopicTranslationIn]


class OngoingTopicAction(BaseModel):
    action: Literal["publish", "archive", "draft"]


class TopicStoryIn(BaseModel):
    story_id: str


class ArticleAction(BaseModel):
    action: Literal["ignore", "reprocess", "create_story", "attach"]
    story_id: str | None = None


class ArticleBatchIn(BaseModel):
    article_ids: list[str] = Field(min_length=1, max_length=100)


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    rss_url: HttpUrl
    website_url: HttpUrl | None = None
    language: Literal["ar", "en"] = "en"
    country: str | None = Field(default=None, max_length=64)
    region: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=32)
    reliability_level: Literal["high", "medium", "low", "unknown"] = "unknown"
    reliability_notes: str | None = None
    notes: str | None = None
    active: bool = True


class SourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    rss_url: HttpUrl | None = None
    website_url: HttpUrl | None = None
    language: Literal["ar", "en"] | None = None
    country: str | None = Field(default=None, max_length=64)
    region: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=32)
    reliability_level: Literal["high", "medium", "low", "unknown"] | None = None
    reliability_notes: str | None = None
    notes: str | None = None
    active: bool | None = None


class IngestionJobIn(BaseModel):
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    category: str | None = None
    region: str | None = None


class UserStatusPatch(BaseModel):
    account_status: Literal["active", "disabled"]


class SettingsPatch(RuntimeControls):
    pass


class ManualStoryIn(BaseModel):
    headline: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=5000)
    what_happened: str = Field(default="", max_length=10000)
    why_it_matters: str = Field(default="", max_length=10000)
    key_facts: list[str] = Field(default_factory=list, max_length=30)
    category: str | None = None
    region: str | None = None
    language: Literal["ar", "en"] = "ar"
    editor_notes: str | None = None


class UrlImportIn(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1, max_length=10)


class JobOut(BaseModel):
    id: str
    job_type: str
    status: str
    arguments: dict[str, Any]
    progress_current: int
    progress_total: int
    attempts: int
    max_attempts: int
    result: dict[str, Any]
    error_message: str | None
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
