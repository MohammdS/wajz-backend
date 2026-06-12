from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

CATEGORIES = [
    "World",
    "Middle East",
    "Local / Regional",
    "Technology",
    "Economy",
    "Science",
    "Health",
    "Sports",
    "Culture",
    "Politics",
]

REGIONS = [
    "World",
    "Middle East",
    "Israel / Palestine",
    "United States",
    "Europe",
    "Technology Global",
]

LANGUAGES = ["en", "ar", "he"]
BRIEFING_LENGTHS = ["5_minutes", "10_minutes", "20_minutes"]
EXPLANATION_LEVELS = ["brief", "standard", "beginner_friendly"]
NOTIFICATION_PREFERENCES = [
    "none",
    "daily_morning",
    "daily_evening",
    "major_confirmed_only",
]

CONFIDENCE_DISPLAY = {
    "confirmed_by_multiple_sources": "Confirmed by multiple sources",
    "developing": "Developing",
    "single_source": "Single-source report",
    "opinion_analysis": "Opinion / analysis",
    "correction_or_update": "Correction or update",
    "low_confidence": "Low confidence",
}


# ---------- Auth ----------

class DevLoginRequest(BaseModel):
    email: EmailStr
    display_name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Users / preferences ----------

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str | None
    preferred_language: str
    auth_provider: str


class PreferencesIn(BaseModel):
    preferred_language: str = Field(default="en")
    topics: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    briefing_length: str = Field(default="10_minutes")
    explanation_level: str = Field(default="standard")
    notification_preference: str = Field(default="daily_morning")


class PreferencesOut(PreferencesIn):
    model_config = ConfigDict(from_attributes=True)


# ---------- Sources ----------

class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    website_url: str | None
    country: str | None
    language: str
    reliability_level: str
    active: bool


class SourceCreate(BaseModel):
    name: str
    website_url: str | None = None
    rss_url: str
    country: str | None = None
    language: str = "en"
    reliability_level: str = "unknown"
    active: bool = True
    notes: str | None = None


class SourceUpdate(BaseModel):
    name: str | None = None
    website_url: str | None = None
    rss_url: str | None = None
    country: str | None = None
    language: str | None = None
    reliability_level: str | None = None
    active: bool | None = None
    notes: str | None = None


# ---------- Stories ----------

class StorySourceLink(BaseModel):
    name: str
    title: str
    url: str
    published_at: datetime | None


class SourceComparisonItem(BaseModel):
    source: str
    framing: str


class StoryListItem(BaseModel):
    id: str
    headline: str
    summary: str | None
    category: str | None
    region: str | None
    confidence_label: str
    confidence_display: str
    source_count: int
    sources: list[str]
    image_url: str | None = None
    last_updated_at: datetime
    saved: bool = False


class StoryDetail(BaseModel):
    id: str
    headline: str
    summary: str | None
    what_happened: str | None
    why_it_matters: str | None
    key_facts: list[str]
    unclear_points: list[str]
    category: str | None
    region: str | None
    confidence_label: str
    confidence_display: str
    importance_score: float
    sources: list[StorySourceLink]
    source_comparison: list[SourceComparisonItem]
    last_updated_at: datetime
    saved: bool = False


class StoryListResponse(BaseModel):
    items: list[StoryListItem]
    total: int
    limit: int
    offset: int


# ---------- Briefing ----------

class BriefingResponse(BaseModel):
    date: str
    briefing_length: str
    estimated_read_time_minutes: int
    greeting: str
    stories: list[StoryListItem]
    completion_message: str = "You are caught up."


# ---------- Saved ----------

class SavedStoryOut(BaseModel):
    saved_at: datetime
    story: StoryListItem
