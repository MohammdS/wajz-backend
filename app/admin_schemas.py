from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

AdminRole = Literal["viewer", "editor", "super_admin"]
StoryStatus = Literal["draft", "pending_review", "published", "archived", "rejected"]


class StoryEdit(BaseModel):
    headline: str | None = None
    summary: str | None = None
    what_happened: str | None = None
    why_it_matters: str | None = None
    key_facts: list[str] | None = None
    unclear_points: list[str] | None = None
    source_comparison: list[dict] | None = None
    category: str | None = None
    region: str | None = None
    language: str | None = None
    importance_score: float | None = Field(default=None, ge=0, le=1)
    confidence_label: str | None = None
    editor_notes: str | None = None


class StoryAction(BaseModel):
    action: Literal[
        "publish",
        "archive",
        "reject",
        "save_draft",
        "submit_review",
        "rerun_synthesis",
        "rerun_translation",
    ]
    language: str | None = None


class ArticleAction(BaseModel):
    action: Literal["reprocess", "ignore", "create_story", "attach"]
    story_id: str | None = None


class SourceInput(BaseModel):
    name: str
    rss_url: str
    website_url: str | None = None
    language: str = "en"
    country: str | None = None
    region: str | None = None
    category: str | None = None
    source_type: str = "rss"
    active: bool = True
    reliability_level: str = "unknown"
    reliability_notes: str | None = None
    notes: str | None = None


class SourcePatch(BaseModel):
    name: str | None = None
    rss_url: str | None = None
    website_url: str | None = None
    language: str | None = None
    country: str | None = None
    region: str | None = None
    category: str | None = None
    source_type: str | None = None
    active: bool | None = None
    reliability_level: str | None = None
    reliability_notes: str | None = None
    notes: str | None = None


class AdminUserPatch(BaseModel):
    admin_role: AdminRole | None = None
    account_status: Literal["active", "disabled"] | None = None


class IngestionRequest(BaseModel):
    source_ids: list[str] = Field(default_factory=list)
    category: str | None = None
    region: str | None = None


class ArticleBatchRequest(BaseModel):
    article_ids: list[str] = Field(min_length=1, max_length=100)


class UrlImport(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1, max_length=10)
    status: StoryStatus = "draft"


class ManualStory(BaseModel):
    title: str
    summary: str = ""
    full_synthesis: str = ""
    key_facts: list[str] = Field(default_factory=list)
    why_it_matters: str = ""
    category: str | None = None
    region: str | None = None
    language: str = "en"
    importance_score: float = Field(default=0.5, ge=0, le=1)
    confidence_label: str = "single_source"
    sources: list[str] = Field(default_factory=list)
    related_urls: list[str] = Field(default_factory=list)
    editor_notes: str | None = None
    status: StoryStatus = "draft"


class AIActionRequest(BaseModel):
    action: Literal[
        "generate_summary",
        "generate_key_facts",
        "generate_why_it_matters",
        "detect_uncertainty",
        "detect_opinion",
        "generate_source_comparison",
        "translate",
        "generate_arabic",
    ]
    title: str
    text: str
    target_language: str | None = None


class SettingPatch(BaseModel):
    value: dict[str, Any]
    description: str | None = None
