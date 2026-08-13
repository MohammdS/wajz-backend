"""Public ongoing-topic queries and serialization."""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Query, Session

from app.models import (
    OngoingTopic,
    OngoingTopicStory,
    OngoingTopicTranslation,
    Story,
    utcnow,
)
from app.schemas import (
    OngoingTopicDetail,
    OngoingTopicListItem,
    StoryListResponse,
)
from app.serializers import story_to_list_item


def _published_stories(db: Session, topic_id: str) -> Query:
    return (
        db.query(Story)
        .join(OngoingTopicStory, OngoingTopicStory.story_id == Story.id)
        .filter(
            OngoingTopicStory.topic_id == topic_id,
            Story.status == "published",
        )
    )


def _translation(topic: OngoingTopic, language: str | None) -> OngoingTopicTranslation:
    by_language = {row.language: row for row in topic.translations}
    requested = language if language in ("ar", "en") else "en"
    return (
        by_language.get(requested)
        or by_language.get("en")
        or by_language.get("ar")
        or topic.translations[0]
    )


def _topic_list_item(
    db: Session,
    topic: OngoingTopic,
    language: str | None,
    saved_ids: set[str],
) -> OngoingTopicListItem:
    translation = _translation(topic, language)
    story_query = _published_stories(db, topic.id)
    story_count = story_query.count()
    latest_story = story_query.order_by(Story.last_updated_at.desc()).first()
    image_url = None
    last_updated_at = topic.updated_at
    if latest_story is not None:
        item = story_to_list_item(
            db,
            latest_story,
            saved_ids,
            language,
        )
        image_url = item.image_url
        last_updated_at = max(last_updated_at, latest_story.last_updated_at)
    return OngoingTopicListItem(
        id=topic.id,
        title=translation.title,
        description=translation.description,
        category=topic.category,
        story_count=story_count,
        image_url=image_url,
        last_updated_at=last_updated_at,
        expires_at=topic.expires_at,
        content_language=translation.language,
    )


def active_topics_query(db: Session, now: datetime | None = None) -> Query:
    now = now or utcnow()
    latest_story_update = (
        select(func.max(Story.last_updated_at))
        .join(OngoingTopicStory, OngoingTopicStory.story_id == Story.id)
        .where(
            OngoingTopicStory.topic_id == OngoingTopic.id,
            Story.status == "published",
        )
        .correlate(OngoingTopic)
        .scalar_subquery()
    )
    return (
        db.query(OngoingTopic)
        .filter(
            OngoingTopic.status == "published",
            or_(OngoingTopic.expires_at.is_(None), OngoingTopic.expires_at > now),
            latest_story_update.is_not(None),
        )
        .order_by(
            OngoingTopic.priority.desc(),
            func.coalesce(latest_story_update, OngoingTopic.updated_at).desc(),
        )
    )


def list_public_topics(
    db: Session,
    *,
    language: str | None,
    saved_ids: set[str],
    limit: int,
    offset: int,
) -> tuple[list[OngoingTopicListItem], int]:
    query = active_topics_query(db)
    total = query.count()
    topics = query.offset(offset).limit(limit).all()
    return [_topic_list_item(db, topic, language, saved_ids) for topic in topics], total


def public_topic_detail(
    db: Session,
    topic_id: str,
    *,
    language: str | None,
    saved_ids: set[str],
    limit: int,
    offset: int,
) -> OngoingTopicDetail | None:
    topic = active_topics_query(db).filter(OngoingTopic.id == topic_id).first()
    if topic is None:
        return None
    topic_item = _topic_list_item(db, topic, language, saved_ids)
    story_query = _published_stories(db, topic.id)
    total = story_query.count()
    stories = story_query.order_by(Story.last_updated_at.desc()).offset(offset).limit(limit).all()
    return OngoingTopicDetail(
        **topic_item.model_dump(),
        stories=StoryListResponse(
            items=[story_to_list_item(db, story, saved_ids, language) for story in stories],
            total=total,
            limit=limit,
            offset=offset,
        ),
    )
