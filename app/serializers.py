"""Story serialization shared by the public, briefing, and saved endpoints."""

from sqlalchemy.orm import Session

from app.models import Article, SavedStory, Source, Story, StoryArticle, User
from app.schemas import (
    CONFIDENCE_DISPLAY,
    SourceComparisonItem,
    StoryDetail,
    StoryListItem,
    StorySourceLink,
)
from app.services.translations import get_story_translation


def _story_articles(db: Session, story: Story) -> list[tuple[Article, Source | None]]:
    links = db.query(StoryArticle).filter(StoryArticle.story_id == story.id).all()
    result = []
    for link in links:
        article = db.get(Article, link.article_id)
        if article is None:
            continue
        result.append((article, db.get(Source, article.source_id)))
    result.sort(key=lambda pair: pair[0].published_at or pair[0].fetched_at, reverse=True)
    return result


def saved_story_ids(db: Session, user: User | None) -> set[str]:
    if user is None:
        return set()
    rows = db.query(SavedStory.story_id).filter(SavedStory.user_id == user.id).all()
    return {row[0] for row in rows}


def story_to_list_item(
    db: Session,
    story: Story,
    saved_ids: set[str] | None = None,
    language: str | None = None,
) -> StoryListItem:
    translation = get_story_translation(db, story, language)
    headline = translation.headline if translation else story.headline
    summary = translation.summary if translation else story.summary
    pairs = _story_articles(db, story)
    source_names: list[str] = []
    image_url = None
    for article, source in pairs:
        name = source.name if source else "Unknown"
        if name not in source_names:
            source_names.append(name)
        if image_url is None and article.image_url:
            image_url = article.image_url
    return StoryListItem(
        id=story.id,
        headline=headline,
        summary=summary,
        category=story.category,
        region=story.region,
        confidence_label=story.confidence_label,
        confidence_display=CONFIDENCE_DISPLAY.get(story.confidence_label, story.confidence_label),
        source_count=len(source_names),
        sources=source_names[:5],
        image_url=image_url,
        last_updated_at=story.last_updated_at,
        saved=story.id in (saved_ids or set()),
        content_language=translation.language if translation else story.language,
    )


def story_to_detail(
    db: Session,
    story: Story,
    saved_ids: set[str] | None = None,
    language: str | None = None,
) -> StoryDetail:
    translation = get_story_translation(db, story, language)
    pairs = _story_articles(db, story)
    links = [
        StorySourceLink(
            name=source.name if source else "Unknown",
            title=article.title,
            url=article.url,
            published_at=article.published_at,
        )
        for article, source in pairs
    ]
    comparison = [
        SourceComparisonItem(source=c.get("source", ""), framing=c.get("framing", ""))
        for c in (
            translation.source_comparison
            if translation is not None
            else (story.source_comparison or [])
        )
        if isinstance(c, dict)
    ]
    return StoryDetail(
        id=story.id,
        headline=translation.headline if translation else story.headline,
        summary=translation.summary if translation else story.summary,
        what_happened=translation.what_happened if translation else story.what_happened,
        why_it_matters=translation.why_it_matters if translation else story.why_it_matters,
        key_facts=translation.key_facts if translation else (story.key_facts or []),
        unclear_points=(
            translation.unclear_points if translation else (story.unclear_points or [])
        ),
        category=story.category,
        region=story.region,
        confidence_label=story.confidence_label,
        confidence_display=CONFIDENCE_DISPLAY.get(story.confidence_label, story.confidence_label),
        importance_score=story.importance_score,
        sources=links,
        source_comparison=comparison,
        last_updated_at=story.last_updated_at,
        saved=story.id in (saved_ids or set()),
        content_language=translation.language if translation else story.language,
    )
