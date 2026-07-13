"""Stored story translations and language fallback."""

import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AIRun, Story, StoryTranslation, utcnow
from app.observability import record_ai_run
from app.services.ai.base import AIProvider, StorySynthesis

logger = logging.getLogger(__name__)


def story_content(story: Story) -> StorySynthesis:
    return StorySynthesis(
        headline=story.headline,
        summary=story.summary or "",
        what_happened=story.what_happened or "",
        why_it_matters=story.why_it_matters or "",
        key_facts=story.key_facts or [],
        unclear_points=story.unclear_points or [],
        source_comparison=story.source_comparison or [],
    )


def upsert_translation(
    db: Session,
    story: Story,
    language: str,
    content: StorySynthesis,
    provider: str,
) -> StoryTranslation:
    translation = (
        db.query(StoryTranslation)
        .filter(
            StoryTranslation.story_id == story.id,
            StoryTranslation.language == language,
        )
        .first()
    )
    if translation is None:
        translation = StoryTranslation(story_id=story.id, language=language)
        db.add(translation)
    translation.headline = content.headline
    translation.summary = content.summary or None
    translation.what_happened = content.what_happened or None
    translation.why_it_matters = content.why_it_matters or None
    translation.key_facts = content.key_facts
    translation.unclear_points = content.unclear_points
    translation.source_comparison = content.source_comparison
    translation.provider = provider
    return translation


def store_source_translation(db: Session, story: Story) -> StoryTranslation:
    return upsert_translation(
        db,
        story,
        story.language or "en",
        story_content(story),
        "source",
    )


def generate_story_translations(
    db: Session,
    story: Story,
    provider: AIProvider,
) -> None:
    source_language = story.language or "en"
    source = story_content(story)
    store_source_translation(db, story)
    db.commit()

    for language in get_settings().supported_content_languages:
        if language == source_language:
            continue
        run = AIRun(
            task_type="story_translation",
            input_reference_type="story",
            input_reference_id=story.id,
            model_name=provider.model_name,
        )
        db.add(run)
        db.flush()
        try:
            translated = provider.translate_story(source, source_language, language)
            if translated is None:
                run.status = "skipped"
                run.error_message = "Translation is unavailable for the active provider"
            else:
                upsert_translation(db, story, language, translated, provider.name)
                run.status = "success"
            record_ai_run(run.task_type, run.status)
            run.completed_at = utcnow()
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failed = AIRun(
                task_type="story_translation",
                input_reference_type="story",
                input_reference_id=story.id,
                model_name=provider.model_name,
                status="error",
                error_message=str(exc)[:2000],
                completed_at=utcnow(),
            )
            db.add(failed)
            record_ai_run(failed.task_type, failed.status)
            db.commit()
            logger.warning("Story translation failed for %s/%s: %s", story.id, language, exc)


def generate_missing_translations(db: Session) -> dict[str, int]:
    from app.services.ai import get_provider

    provider = get_provider()
    languages = get_settings().supported_content_languages
    stories = db.query(Story).all()
    attempted = completed = 0
    for story in stories:
        existing = {
            row[0]
            for row in db.query(StoryTranslation.language)
            .filter(StoryTranslation.story_id == story.id)
            .all()
        }
        if all(language in existing for language in languages):
            continue
        attempted += 1
        generate_story_translations(db, story, provider)
        refreshed = {
            row[0]
            for row in db.query(StoryTranslation.language)
            .filter(StoryTranslation.story_id == story.id)
            .all()
        }
        if all(language in refreshed for language in languages):
            completed += 1
    return {
        "stories_checked": len(stories),
        "stories_attempted": attempted,
        "stories_completed": completed,
    }


def get_story_translation(
    db: Session,
    story: Story,
    language: str | None,
) -> StoryTranslation | None:
    requested = (language or story.language or "en").lower()
    translation = (
        db.query(StoryTranslation)
        .filter(
            StoryTranslation.story_id == story.id,
            StoryTranslation.language == requested,
        )
        .first()
    )
    if translation is not None:
        return translation
    return (
        db.query(StoryTranslation)
        .filter(
            StoryTranslation.story_id == story.id,
            StoryTranslation.language == (story.language or "en"),
        )
        .first()
    )
