"""AI processing pipeline (PRD 12).

For each pending article: analyze (classify + summarize), then cluster into a
story, then refresh the story's multi-source synthesis and confidence label.
Every AI step is recorded in ai_runs for observability (PRD 21.4).
"""

import logging

from sqlalchemy.orm import Session

from app.models import AIRun, Article, Source, Story, StoryArticle, utcnow
from app.observability import dispatch_alert, record_ai_run
from app.services.ai import get_provider
from app.services.clustering import (
    attach_article_to_story,
    create_story_from_article,
    find_matching_story,
)
from app.services.translations import generate_story_translations
from app.services.operational_settings import get_runtime_controls
from app.services.ongoing_topic_matching import auto_attach_story_to_topics

logger = logging.getLogger(__name__)

RELIABILITY_RANK = {"high": 3, "medium": 2, "low": 1, "unknown": 1}


def _record_run(db: Session, task_type: str, ref_type: str, ref_id: str, model: str) -> AIRun:
    run = AIRun(
        task_type=task_type,
        input_reference_type=ref_type,
        input_reference_id=ref_id,
        model_name=model,
    )
    db.add(run)
    db.flush()
    return run


def _finish_run(run: AIRun, status: str, error: str | None = None) -> None:
    run.status = status
    run.error_message = (error or "")[:2000] or None
    run.completed_at = utcnow()
    record_ai_run(run.task_type, status)


def analyze_article(db: Session, article: Article) -> bool:
    """Run classification + summarization on one article. Returns success."""
    provider = get_provider()
    run = _record_run(db, "article_analysis", "article", article.id, provider.model_name)
    try:
        source = db.get(Source, article.source_id)
        analysis = provider.analyze_article(
            article.title, article.cleaned_text or "", source.name if source else "Unknown"
        )
        article.category = analysis.category
        article.region = analysis.region
        article.language = analysis.language
        article.topic_tags = analysis.topic_tags
        article.entities = analysis.entities
        article.importance_score = analysis.importance_score
        article.summary = analysis.short_summary
        article.key_facts = analysis.key_facts
        article.why_it_matters = analysis.why_it_matters
        article.unclear_points = analysis.unclear_points
        article.is_opinion = analysis.is_opinion
        article.processing_status = "processed"
        article.status = "processed"
        article.failure_reason = None
        _finish_run(run, "success")
        db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - a failing article must not stop the batch
        db.rollback()
        # The run row was rolled back with the transaction; re-record the failure.
        failed_run = _record_run(db, "article_analysis", "article", article.id, provider.model_name)
        _finish_run(failed_run, "error", str(exc))
        article.processing_status = "failed"
        article.status = "failed"
        article.failure_reason = str(exc)[:2000]
        db.commit()
        logger.warning("Article analysis failed for %s: %s", article.id, exc)
        return False


def compute_confidence_label(db: Session, story: Story) -> str:
    """PRD 12.7 basic logic."""
    links = db.query(StoryArticle).filter(StoryArticle.story_id == story.id).all()
    articles = [db.get(Article, link.article_id) for link in links]
    articles = [a for a in articles if a is not None]
    if not articles:
        return "low_confidence"

    if all(a.is_opinion for a in articles):
        return "opinion_analysis"

    reliable_sources = set()
    weak_only = True
    for article in articles:
        source = db.get(Source, article.source_id)
        rank = RELIABILITY_RANK.get(source.reliability_level if source else "unknown", 1)
        if rank >= 2:
            reliable_sources.add(article.source_id)
            weak_only = False
    if weak_only:
        return "low_confidence"
    if len(reliable_sources) >= 3:
        return "confirmed_by_multiple_sources"
    if len({a.source_id for a in articles}) >= 2:
        return "developing"
    return "single_source"


def refresh_story_synthesis(db: Session, story: Story) -> None:
    """Regenerate the multi-source summary for stories with 2+ articles."""
    links = db.query(StoryArticle).filter(StoryArticle.story_id == story.id).all()
    article_ids = [link.article_id for link in links]
    articles = [a for a in (db.get(Article, aid) for aid in article_ids) if a is not None]
    story.confidence_label = compute_confidence_label(db, story)
    if len(articles) < 2:
        db.commit()
        if get_runtime_controls(db).translations_enabled:
            generate_story_translations(db, story, get_provider())
        return

    provider = get_provider()
    run = _record_run(db, "story_synthesis", "story", story.id, provider.model_name)
    try:
        payload = []
        for article in articles:
            source = db.get(Source, article.source_id)
            payload.append(
                {
                    "source": source.name if source else "Unknown",
                    "title": article.title,
                    "summary": article.summary,
                    "key_facts": article.key_facts,
                    "why_it_matters": article.why_it_matters,
                    "unclear_points": article.unclear_points,
                    "text": article.cleaned_text,
                }
            )
        synthesis = provider.synthesize_story(payload)
        story.headline = synthesis.headline or story.headline
        story.summary = synthesis.summary or story.summary
        story.what_happened = synthesis.what_happened or story.what_happened
        story.why_it_matters = synthesis.why_it_matters or story.why_it_matters
        story.key_facts = synthesis.key_facts or story.key_facts
        story.unclear_points = synthesis.unclear_points
        story.source_comparison = synthesis.source_comparison
        for article in articles:
            article.status = "summarized"
        _finish_run(run, "success")
        db.commit()
        if get_runtime_controls(db).translations_enabled:
            generate_story_translations(db, story, provider)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        failed_run = _record_run(db, "story_synthesis", "story", story.id, provider.model_name)
        _finish_run(failed_run, "error", str(exc))
        db.commit()
        logger.warning("Story synthesis failed for %s: %s", story.id, exc)


def process_pending_articles(
    db: Session,
    limit: int = 100,
    article_ids: list[str] | None = None,
) -> dict:
    """Main pipeline entry: analyze pending articles and cluster them into stories."""
    query = db.query(Article).filter(Article.processing_status == "pending")
    if article_ids is not None:
        query = query.filter(Article.id.in_(article_ids))
    pending = query.order_by(Article.fetched_at.asc()).limit(limit).all()
    processed = failed = 0
    touched_story_ids: set[str] = set()

    for article in pending:
        if not analyze_article(db, article):
            failed += 1
            continue
        story = find_matching_story(db, article)
        if story is not None:
            attach_article_to_story(db, article, story)
        else:
            story = create_story_from_article(db, article)
        article.status = "clustered"
        db.commit()
        touched_story_ids.add(story.id)
        processed += 1

    for story_id in touched_story_ids:
        story = db.get(Story, story_id)
        if story is not None:
            refresh_story_synthesis(db, story)
            if get_runtime_controls(db).ongoing_auto_attach_enabled:
                auto_attach_story_to_topics(db, story)

    if failed:
        dispatch_alert(
            "pipeline.article_failures",
            "warning",
            {"failed": failed, "processed": processed},
        )

    return {"processed": processed, "failed": failed, "stories_touched": len(touched_story_ids)}
