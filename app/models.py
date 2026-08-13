import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    preferred_language: Mapped[str] = mapped_column(String(8), default="en")
    auth_provider: Mapped[str] = mapped_column(String(32), default="dev")
    auth_subject: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    account_status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime)

    preferences: Mapped["UserPreferences | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class UserPreferences(Base, TimestampMixin):
    __tablename__ = "user_preferences"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    regions: Mapped[list] = mapped_column(JSON, default=list)
    briefing_length: Mapped[str] = mapped_column(String(16), default="10_minutes")
    explanation_level: Mapped[str] = mapped_column(String(24), default="standard")
    notification_preference: Mapped[str] = mapped_column(String(32), default="daily_morning")
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="preferences")


class Source(Base, TimestampMixin):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    website_url: Mapped[str | None] = mapped_column(String(512))
    rss_url: Mapped[str] = mapped_column(String(512))
    country: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(8), default="en")
    reliability_level: Mapped[str] = mapped_column(
        String(16), default="unknown"
    )  # high|medium|low|unknown
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(64), index=True)
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    source_type: Mapped[str] = mapped_column(String(24), default="rss")
    last_successful_fetch: Mapped[datetime | None] = mapped_column(DateTime)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    reliability_notes: Mapped[str | None] = mapped_column(Text)

    articles: Mapped[list["Article"]] = relationship(back_populates="source")


class Article(Base, TimestampMixin):
    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    author: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    language: Mapped[str | None] = mapped_column(String(8))
    raw_text: Mapped[str | None] = mapped_column(Text)
    cleaned_text: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    key_facts: Mapped[list] = mapped_column(JSON, default=list)
    why_it_matters: Mapped[str | None] = mapped_column(Text)
    unclear_points: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    region: Mapped[str | None] = mapped_column(String(64), index=True)
    topic_tags: Mapped[list] = mapped_column(JSON, default=list)
    entities: Mapped[list] = mapped_column(JSON, default=list)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    image_url: Mapped[str | None] = mapped_column(String(1024))
    is_opinion: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_status: Mapped[str] = mapped_column(
        String(16), default="pending", index=True
    )  # pending|processed|failed
    status: Mapped[str] = mapped_column(String(16), default="collected", index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    ingestion_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("ingestion_runs.id"), index=True
    )

    source: Mapped[Source] = relationship(back_populates="articles")


class Story(Base, TimestampMixin):
    __tablename__ = "stories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    headline: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    what_happened: Mapped[str | None] = mapped_column(Text)
    why_it_matters: Mapped[str | None] = mapped_column(Text)
    key_facts: Mapped[list] = mapped_column(JSON, default=list)
    unclear_points: Mapped[list] = mapped_column(JSON, default=list)
    source_comparison: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    region: Mapped[str | None] = mapped_column(String(64), index=True)
    confidence_label: Mapped[str] = mapped_column(String(40), default="single_source")
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    language: Mapped[str] = mapped_column(String(8), default="en")
    entities: Mapped[list] = mapped_column(JSON, default=list)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending_review", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    editor_notes: Mapped[str | None] = mapped_column(Text)
    published_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))

    articles: Mapped[list["StoryArticle"]] = relationship(
        back_populates="story", cascade="all, delete-orphan"
    )
    translations: Mapped[list["StoryTranslation"]] = relationship(
        back_populates="story", cascade="all, delete-orphan"
    )


class StoryTranslation(Base, TimestampMixin):
    __tablename__ = "story_translations"
    __table_args__ = (
        UniqueConstraint("story_id", "language", name="uq_story_translation_language"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    language: Mapped[str] = mapped_column(String(8), index=True)
    headline: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    what_happened: Mapped[str | None] = mapped_column(Text)
    why_it_matters: Mapped[str | None] = mapped_column(Text)
    key_facts: Mapped[list] = mapped_column(JSON, default=list)
    unclear_points: Mapped[list] = mapped_column(JSON, default=list)
    source_comparison: Mapped[list] = mapped_column(JSON, default=list)
    provider: Mapped[str | None] = mapped_column(String(64))

    story: Mapped[Story] = relationship(back_populates="translations")


class OngoingTopic(Base, TimestampMixin):
    __tablename__ = "ongoing_topics"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    published_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))

    translations: Mapped[list["OngoingTopicTranslation"]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )
    stories: Mapped[list["OngoingTopicStory"]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )


class OngoingTopicTranslation(Base, TimestampMixin):
    __tablename__ = "ongoing_topic_translations"
    __table_args__ = (
        UniqueConstraint("topic_id", "language", name="uq_ongoing_topic_translation_language"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    topic_id: Mapped[str] = mapped_column(ForeignKey("ongoing_topics.id"), index=True)
    language: Mapped[str] = mapped_column(String(8), index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)

    topic: Mapped[OngoingTopic] = relationship(back_populates="translations")


class OngoingTopicStory(Base):
    __tablename__ = "ongoing_topic_stories"

    topic_id: Mapped[str] = mapped_column(ForeignKey("ongoing_topics.id"), primary_key=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), primary_key=True, index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    added_by: Mapped[str] = mapped_column(String(16), default="manual")
    match_score: Mapped[float | None] = mapped_column(Float)
    match_reason: Mapped[dict] = mapped_column(JSON, default=dict)

    topic: Mapped[OngoingTopic] = relationship(back_populates="stories")
    story: Mapped[Story] = relationship()


class StoryArticle(Base):
    __tablename__ = "story_articles"

    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), primary_key=True)
    article_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), primary_key=True)

    story: Mapped[Story] = relationship(back_populates="articles")
    article: Mapped[Article] = relationship()


class Briefing(Base):
    __tablename__ = "briefings"
    __table_args__ = (UniqueConstraint("user_id", "briefing_date", name="uq_briefing_user_date"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    briefing_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    briefing_length: Mapped[str] = mapped_column(String(16), default="10_minutes")

    stories: Mapped[list["BriefingStory"]] = relationship(
        back_populates="briefing", cascade="all, delete-orphan", order_by="BriefingStory.rank"
    )


class BriefingStory(Base):
    __tablename__ = "briefing_stories"

    briefing_id: Mapped[str] = mapped_column(ForeignKey("briefings.id"), primary_key=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)

    briefing: Mapped[Briefing] = relationship(back_populates="stories")
    story: Mapped[Story] = relationship()


class SavedStory(Base):
    __tablename__ = "saved_stories"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), primary_key=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    story: Mapped[Story] = relationship()


class OpenedStory(Base):
    __tablename__ = "opened_stories"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), primary_key=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AIRun(Base):
    __tablename__ = "ai_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    task_type: Mapped[str] = mapped_column(String(48), index=True)
    input_reference_type: Mapped[str | None] = mapped_column(String(32))
    input_reference_id: Mapped[str | None] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # pending|success|error|skipped
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(
        String(16), default="running"
    )  # running|success|partial|error
    sources_total: Mapped[int] = mapped_column(Integer, default=0)
    sources_failed: Mapped[int] = mapped_column(Integer, default=0)
    articles_fetched: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    actor_email: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str] = mapped_column(String(40), index=True)
    target_id: Mapped[str | None] = mapped_column(String(64), index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AdminJob(Base, TimestampMixin):
    __tablename__ = "admin_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_type: Mapped[str] = mapped_column(String(48), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    requested_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class OperationalSetting(Base, TimestampMixin):
    __tablename__ = "operational_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class AnalyticsInstallation(Base):
    __tablename__ = "analytics_installations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    secret_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime)


class PrivacyAcknowledgement(Base):
    __tablename__ = "privacy_acknowledgements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("analytics_installations.id"), index=True
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    policy_version: Mapped[str] = mapped_column(String(32), index=True)
    locale: Mapped[str] = mapped_column(String(8), default="ar")
    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("analytics_installations.id"), index=True
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(48), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(32), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    locale: Mapped[str | None] = mapped_column(String(8), index=True)
    platform: Mapped[str | None] = mapped_column(String(16), index=True)
    app_version: Mapped[str | None] = mapped_column(String(24))


class AnalyticsDailyAggregate(Base):
    __tablename__ = "analytics_daily_aggregates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    day: Mapped[str] = mapped_column(String(10), index=True)
    metric: Mapped[str] = mapped_column(String(48), index=True)
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
