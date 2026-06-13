from datetime import datetime, timedelta

import feedparser
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.admin_schemas import (
    AIActionRequest,
    AdminUserPatch,
    ArticleAction,
    ArticleBatchRequest,
    IngestionRequest,
    ManualStory,
    SettingPatch,
    SourceInput,
    SourcePatch,
    StoryAction,
    StoryEdit,
    UrlImport,
)
from app.auth import require_admin, require_role
from app.config import get_settings
from app.database import get_db
from app.models import (
    AIRun,
    AdminSetting,
    Article,
    AuditLog,
    IngestionRun,
    SavedStory,
    Source,
    Story,
    StoryArticle,
    StoryTranslation,
    User,
    UserPreferences,
    utcnow,
)
from app.rate_limit import rate_limit
from app.services.ai import StorySynthesis, get_provider
from app.services.clustering import attach_article_to_story, create_story_from_article
from app.services.ingestion import ingest_source
from app.services.pipeline import (
    analyze_article,
    compute_confidence_label,
    process_pending_articles,
    refresh_story_synthesis,
)
from app.services.safe_fetch import fetch_article_url, validate_public_url
from app.services.translations import generate_missing_translations, generate_story_translations

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[
        Depends(require_admin),
        Depends(rate_limit("admin", "rate_limit_auth")),
    ],
)


def _audit(
    db: Session,
    actor: User,
    action: str,
    target_type: str,
    target_id: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            actor_email=actor.email,
            actor_role=actor.admin_role or "viewer",
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
        )
    )


def _source_dict(source: Source) -> dict:
    return {
        "id": source.id,
        "name": source.name,
        "rss_url": source.rss_url,
        "website_url": source.website_url,
        "language": source.language,
        "country": source.country,
        "region": source.region,
        "category": source.category,
        "source_type": source.source_type,
        "active": source.active,
        "reliability_level": source.reliability_level,
        "reliability_notes": source.reliability_notes,
        "notes": source.notes,
        "last_successful_fetch": source.last_successful_fetch,
        "failure_count": source.failure_count,
        "last_error": source.last_error,
        "healthy": source.active and source.failure_count < 3,
    }


def _article_dict(db: Session, article: Article, include_text: bool = False) -> dict:
    source = db.get(Source, article.source_id)
    data = {
        "id": article.id,
        "title": article.title,
        "url": article.url,
        "source_id": article.source_id,
        "source_name": source.name if source else "Unknown",
        "published_at": article.published_at,
        "fetched_at": article.fetched_at,
        "language": article.language,
        "category": article.category,
        "region": article.region,
        "entities": article.entities or [],
        "topics": article.topic_tags or [],
        "processing_status": article.processing_status,
        "status": article.status,
        "failure_reason": article.failure_reason,
        "summary": article.summary,
        "importance_score": article.importance_score,
        "is_opinion": article.is_opinion,
        "ingestion_run_id": article.ingestion_run_id,
    }
    if include_text:
        data["cleaned_text"] = article.cleaned_text
        data["key_facts"] = article.key_facts or []
        data["why_it_matters"] = article.why_it_matters
        data["unclear_points"] = article.unclear_points or []
    return data


def _story_dict(db: Session, story: Story, include_articles: bool = False) -> dict:
    links = db.query(StoryArticle).filter(StoryArticle.story_id == story.id).all()
    articles = [db.get(Article, link.article_id) for link in links]
    articles = [article for article in articles if article is not None]
    source_names = []
    for article in articles:
        source = db.get(Source, article.source_id)
        if source and source.name not in source_names:
            source_names.append(source.name)
    data = {
        "id": story.id,
        "headline": story.headline,
        "summary": story.summary,
        "what_happened": story.what_happened,
        "why_it_matters": story.why_it_matters,
        "key_facts": story.key_facts or [],
        "unclear_points": story.unclear_points or [],
        "source_comparison": story.source_comparison or [],
        "category": story.category,
        "region": story.region,
        "language": story.language,
        "importance_score": story.importance_score,
        "confidence_label": story.confidence_label,
        "status": story.status,
        "editor_notes": story.editor_notes,
        "published_at": story.published_at,
        "last_updated_at": story.last_updated_at,
        "source_count": len(source_names),
        "sources": source_names,
        "translation_languages": [
            row.language
            for row in db.query(StoryTranslation)
            .filter(StoryTranslation.story_id == story.id)
            .all()
        ],
    }
    if include_articles:
        data["articles"] = [_article_dict(db, article) for article in articles]
    return data


def _page(query, page: int, page_size: int) -> tuple[list, int]:
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


@router.get("/session")
def admin_session(user: User = Depends(require_admin)) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.admin_role,
    }


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    today = datetime.combine(utcnow().date(), datetime.min.time())
    active_cutoff = utcnow() - timedelta(days=30)
    latest_run = db.query(IngestionRun).order_by(IngestionRun.started_at.desc()).first()
    settings = get_settings()
    language_count = max(1, len(settings.supported_content_languages))
    translated = db.query(func.count(StoryTranslation.id)).scalar() or 0
    story_count = db.query(func.count(Story.id)).scalar() or 0
    return {
        "stories_today": db.query(Story).filter(Story.created_at >= today).count(),
        "articles_today": db.query(Article).filter(Article.fetched_at >= today).count(),
        "pending_review_stories": db.query(Story)
        .filter(Story.status == "pending_review")
        .count(),
        "failed_feeds": db.query(Source).filter(Source.failure_count > 0).count(),
        "failed_articles": db.query(Article).filter(Article.status == "failed").count(),
        "active_users": db.query(User).filter(User.last_active_at >= active_cutoff).count(),
        "ai_failures": db.query(AIRun).filter(AIRun.status == "error").count(),
        "latest_ingestion": (
            {
                "id": latest_run.id,
                "status": latest_run.status,
                "started_at": latest_run.started_at,
                "completed_at": latest_run.completed_at,
                "articles_fetched": latest_run.articles_fetched,
            }
            if latest_run
            else None
        ),
        "pending_translations": max(0, story_count * language_count - translated),
        "unhealthy_sources": db.query(Source)
        .filter(Source.active.is_(True), Source.failure_count >= 3)
        .count(),
    }


@router.get("/stories")
def list_stories(
    search: str | None = None,
    story_status: str | None = Query(default=None, alias="status"),
    category: str | None = None,
    region: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(Story).order_by(Story.last_updated_at.desc())
    if search:
        query = query.filter(
            or_(Story.headline.ilike(f"%{search}%"), Story.summary.ilike(f"%{search}%"))
        )
    if story_status:
        query = query.filter(Story.status == story_status)
    if category:
        query = query.filter(Story.category == category)
    if region:
        query = query.filter(Story.region == region)
    items, total = _page(query, page, page_size)
    return {"items": [_story_dict(db, item) for item in items], "total": total}


@router.get("/stories/{story_id}")
def get_story(story_id: str, db: Session = Depends(get_db)) -> dict:
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    return _story_dict(db, story, include_articles=True)


@router.put("/stories/{story_id}")
def update_story(
    story_id: str,
    body: StoryEdit,
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(story, field, value)
    story.last_updated_at = utcnow()
    _audit(db, actor, "story.update", "story", story.id, {"fields": list(changes)})
    db.commit()
    return _story_dict(db, story, include_articles=True)


@router.post("/stories/{story_id}/action")
def story_action(
    story_id: str,
    body: StoryAction,
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    if body.action == "publish":
        story.status = "published"
        story.published_at = utcnow()
        story.published_by_id = actor.id
    elif body.action == "archive":
        story.status = "archived"
    elif body.action == "reject":
        story.status = "rejected"
    elif body.action == "save_draft":
        story.status = "draft"
    elif body.action == "submit_review":
        story.status = "pending_review"
    elif body.action == "rerun_synthesis":
        refresh_story_synthesis(db, story)
        story.status = "pending_review"
    elif body.action == "rerun_translation":
        generate_story_translations(db, story, get_provider())
    _audit(db, actor, f"story.{body.action}", "story", story.id)
    db.commit()
    return _story_dict(db, story, include_articles=True)


@router.get("/articles")
def list_articles(
    search: str | None = None,
    article_status: str | None = Query(default=None, alias="status"),
    source_id: str | None = None,
    category: str | None = None,
    region: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(Article).order_by(Article.fetched_at.desc())
    if search:
        query = query.filter(
            or_(Article.title.ilike(f"%{search}%"), Article.url.ilike(f"%{search}%"))
        )
    if article_status:
        query = query.filter(Article.status == article_status)
    if source_id:
        query = query.filter(Article.source_id == source_id)
    if category:
        query = query.filter(Article.category == category)
    if region:
        query = query.filter(Article.region == region)
    items, total = _page(query, page, page_size)
    return {"items": [_article_dict(db, item) for item in items], "total": total}


@router.get("/articles/{article_id}")
def get_article(article_id: str, db: Session = Depends(get_db)) -> dict:
    article = db.get(Article, article_id)
    if article is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Article not found")
    return _article_dict(db, article, include_text=True)


@router.post("/articles/{article_id}/action")
def article_action(
    article_id: str,
    body: ArticleAction,
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    article = db.get(Article, article_id)
    if article is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Article not found")
    if body.action == "reprocess":
        article.processing_status = "pending"
        article.status = "collected"
        article.failure_reason = None
        db.commit()
        analyze_article(db, article)
    elif body.action == "ignore":
        article.status = "ignored"
    elif body.action == "create_story":
        story = create_story_from_article(db, article)
        story.status = "draft"
        article.status = "clustered"
    elif body.action == "attach":
        story = db.get(Story, body.story_id or "")
        if story is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
        attach_article_to_story(db, article, story)
        article.status = "clustered"
    _audit(db, actor, f"article.{body.action}", "article", article.id)
    db.commit()
    return _article_dict(db, article, include_text=True)


@router.get("/sources")
def list_sources(db: Session = Depends(get_db)) -> list[dict]:
    return [_source_dict(item) for item in db.query(Source).order_by(Source.name).all()]


@router.post("/sources", status_code=status.HTTP_201_CREATED)
def create_source(
    body: SourceInput,
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    if db.query(Source).filter(Source.name == body.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Source name already exists")
    validate_public_url(body.rss_url)
    source = Source(**body.model_dump())
    db.add(source)
    db.flush()
    _audit(db, actor, "source.create", "source", source.id)
    db.commit()
    return _source_dict(source)


@router.put("/sources/{source_id}")
def update_source(
    source_id: str,
    body: SourcePatch,
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("rss_url"):
        validate_public_url(changes["rss_url"])
    for field, value in changes.items():
        setattr(source, field, value)
    _audit(db, actor, "source.update", "source", source.id, {"fields": list(changes)})
    db.commit()
    return _source_dict(source)


@router.post("/sources/{source_id}/test")
def test_source(
    source_id: str,
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    validate_public_url(source.rss_url)
    response = httpx.get(source.rss_url, timeout=15, follow_redirects=True)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    _audit(db, actor, "source.test", "source", source.id)
    db.commit()
    return {"ok": not bool(feed.bozo), "entries": len(feed.entries)}


@router.post("/sources/{source_id}/run")
def run_source(
    source_id: str,
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    run = IngestionRun(status="running", sources_total=1)
    db.add(run)
    db.commit()
    try:
        count = ingest_source(db, source, run.id)
        run.status = "succeeded"
        run.articles_fetched = count
    except Exception as exc:
        run.status = "failed"
        run.sources_failed = 1
        run.error_message = str(exc)[:2000]
    run.completed_at = utcnow()
    _audit(db, actor, "ingestion.source_run", "source", source.id, {"run_id": run.id})
    db.commit()
    return {"run_id": run.id, "status": run.status, "articles_fetched": run.articles_fetched}


@router.post("/ingestion/run")
def run_ingestion_filtered(
    body: IngestionRequest,
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(Source).filter(Source.active.is_(True))
    if body.source_ids:
        query = query.filter(Source.id.in_(body.source_ids))
    if body.category:
        query = query.filter(Source.category == body.category)
    if body.region:
        query = query.filter(Source.region == body.region)
    sources = query.all()
    run = IngestionRun(status="running", sources_total=len(sources))
    db.add(run)
    db.commit()
    errors = []
    for source in sources:
        try:
            run.articles_fetched += ingest_source(db, source, run.id)
        except Exception as exc:
            db.rollback()
            run = db.get(IngestionRun, run.id)
            run.sources_failed += 1
            errors.append(f"{source.name}: {exc}")
    run.status = (
        "succeeded"
        if not errors
        else "partial"
        if run.sources_failed < run.sources_total
        else "failed"
    )
    run.error_message = "; ".join(errors)[:2000] or None
    run.completed_at = utcnow()
    _audit(db, actor, "ingestion.run", "ingestion_run", run.id)
    db.commit()
    return {"id": run.id, "status": run.status, "articles_fetched": run.articles_fetched}


@router.post("/ingestion/retry-failed")
def retry_failed(
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    articles = db.query(Article).filter(Article.status == "failed").all()
    for article in articles:
        article.status = "collected"
        article.processing_status = "pending"
        article.failure_reason = None
    _audit(db, actor, "article.retry_failed", "article_batch", details={"count": len(articles)})
    db.commit()
    return process_pending_articles(db, limit=max(100, len(articles)))


@router.post("/ingestion/retry-failed-feeds")
def retry_failed_feeds(
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    source_ids = [
        source.id
        for source in db.query(Source)
        .filter(Source.active.is_(True), Source.failure_count > 0)
        .all()
    ]
    return run_ingestion_filtered(IngestionRequest(source_ids=source_ids), actor, db)


@router.post("/articles/reprocess-selected")
def reprocess_selected(
    body: ArticleBatchRequest,
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    articles = db.query(Article).filter(Article.id.in_(body.article_ids)).all()
    for article in articles:
        article.status = "collected"
        article.processing_status = "pending"
        article.failure_reason = None
    _audit(
        db,
        actor,
        "article.reprocess_selected",
        "article_batch",
        details={"article_ids": body.article_ids},
    )
    db.commit()
    return process_pending_articles(db, limit=len(articles))


@router.get("/ingestion-runs")
def list_ingestion_runs(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[dict]:
    runs = db.query(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit).all()
    return [
        {
            "id": run.id,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "status": run.status,
            "sources_total": run.sources_total,
            "sources_failed": run.sources_failed,
            "articles_fetched": run.articles_fetched,
            "error_message": run.error_message,
            "articles": [
                _article_dict(db, article)
                for article in db.query(Article)
                .filter(Article.ingestion_run_id == run.id)
                .limit(100)
                .all()
            ],
        }
        for run in runs
    ]


@router.post("/ingestion-runs/{run_id}/cancel")
def cancel_ingestion_run(
    run_id: str,
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    run = db.get(IngestionRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ingestion run not found")
    if run.status not in {"queued", "running"}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only queued or running runs can be cancelled",
        )
    run.status = "cancelled"
    run.completed_at = utcnow()
    _audit(db, actor, "ingestion.cancel", "ingestion_run", run.id)
    db.commit()
    return {"id": run.id, "status": run.status}


@router.post("/processing/run")
def trigger_processing(
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    result = process_pending_articles(db)
    _audit(db, actor, "processing.run", "article_batch", details=result)
    db.commit()
    return result


@router.post("/translations/run")
def trigger_translation_backfill(
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    result = generate_missing_translations(db)
    _audit(db, actor, "translation.backfill", "story_batch", details=result)
    db.commit()
    return result


def _manual_source(db: Session, hostname: str, url: str) -> Source:
    name = f"Manual: {hostname}"
    source = db.query(Source).filter(Source.name == name).first()
    if source is None:
        source = Source(
            name=name,
            website_url=f"https://{hostname}",
            rss_url=url,
            source_type="manual_url",
            reliability_level="unknown",
            active=False,
        )
        db.add(source)
        db.flush()
    return source


@router.post("/studio/from-urls")
def studio_from_urls(
    body: UrlImport,
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    provider = get_provider()
    articles = []
    payload = []
    for requested_url in body.urls:
        fetched = fetch_article_url(str(requested_url))
        existing = db.query(Article).filter(Article.url == fetched["url"]).first()
        if existing:
            article = existing
        else:
            source = _manual_source(db, fetched["hostname"], fetched["url"])
            article = Article(
                source_id=source.id,
                title=fetched["title"],
                url=fetched["url"],
                raw_text=fetched["raw_text"],
                cleaned_text=fetched["cleaned_text"],
                status="cleaned",
                processing_status="pending",
            )
            db.add(article)
            db.flush()
            analyze_article(db, article)
        articles.append(article)
        source = db.get(Source, article.source_id)
        payload.append(
            {
                "source": source.name if source else fetched["hostname"],
                "title": article.title,
                "summary": article.summary,
                "key_facts": article.key_facts,
                "why_it_matters": article.why_it_matters,
                "unclear_points": article.unclear_points,
                "text": article.cleaned_text,
            }
        )
    if len(payload) == 1:
        article = articles[0]
        story = create_story_from_article(db, article)
    else:
        synthesis = provider.synthesize_story(payload)
        story = Story(
            headline=synthesis.headline,
            summary=synthesis.summary,
            what_happened=synthesis.what_happened,
            why_it_matters=synthesis.why_it_matters,
            key_facts=synthesis.key_facts,
            unclear_points=synthesis.unclear_points,
            source_comparison=synthesis.source_comparison,
            category=articles[0].category,
            region=articles[0].region,
            language=articles[0].language or "en",
            importance_score=max(article.importance_score for article in articles),
            status="draft",
        )
        db.add(story)
        db.flush()
        for article in articles:
            db.add(StoryArticle(story_id=story.id, article_id=article.id))
        story.confidence_label = compute_confidence_label(db, story)
    story.status = body.status
    if body.status == "published":
        story.published_at = utcnow()
        story.published_by_id = actor.id
    _audit(
        db,
        actor,
        "studio.import_urls",
        "story",
        story.id,
        {"url_count": len(body.urls), "status": body.status},
    )
    db.commit()
    return _story_dict(db, story, include_articles=True)


@router.post("/studio/manual")
def studio_manual(
    body: ManualStory,
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    story = Story(
        headline=body.title,
        summary=body.summary,
        what_happened=body.full_synthesis,
        why_it_matters=body.why_it_matters,
        key_facts=body.key_facts,
        category=body.category,
        region=body.region,
        language=body.language,
        importance_score=body.importance_score,
        confidence_label=body.confidence_label,
        editor_notes=body.editor_notes,
        status=body.status,
        source_comparison=[
            {"source": source, "framing": ""} for source in body.sources
        ],
    )
    if body.status == "published":
        story.published_at = utcnow()
        story.published_by_id = actor.id
    db.add(story)
    db.flush()
    _audit(db, actor, "studio.manual_story", "story", story.id, {"status": body.status})
    db.commit()
    return _story_dict(db, story)


@router.get("/studio/templates")
def studio_templates() -> list[dict]:
    return [
        {"id": "breaking_news", "name": "Breaking News", "status": "pending_review"},
        {"id": "developing_story", "name": "Developing Story", "status": "pending_review"},
        {"id": "explainer", "name": "Explainer", "status": "draft"},
        {"id": "regional_update", "name": "Regional Update", "status": "draft"},
        {"id": "source_comparison", "name": "Source Comparison", "status": "draft"},
    ]


@router.post("/studio/ai-action")
def studio_ai_action(
    body: AIActionRequest,
    actor: User = Depends(require_role("editor")),
    db: Session = Depends(get_db),
) -> dict:
    provider = get_provider()
    analysis = provider.analyze_article(body.title, body.text, "Admin draft")
    result: object
    if body.action == "generate_summary":
        result = analysis.short_summary
    elif body.action == "generate_key_facts":
        result = analysis.key_facts
    elif body.action == "generate_why_it_matters":
        result = analysis.why_it_matters
    elif body.action == "detect_uncertainty":
        result = analysis.unclear_points
    elif body.action == "detect_opinion":
        result = analysis.is_opinion
    elif body.action == "generate_source_comparison":
        result = provider.synthesize_story(
            [{"source": "Admin draft", "title": body.title, "text": body.text}]
        ).source_comparison
    else:
        base = StorySynthesis(
            headline=body.title,
            summary=analysis.short_summary,
            what_happened=analysis.short_summary,
            why_it_matters=analysis.why_it_matters,
            key_facts=analysis.key_facts,
            unclear_points=analysis.unclear_points,
        )
        target = "ar" if body.action == "generate_arabic" else body.target_language or "ar"
        translated = provider.translate_story(base, "en", target)
        result = translated.__dict__ if translated else None
    _audit(db, actor, f"studio.{body.action}", "draft")
    db.commit()
    return {"action": body.action, "result": result}


@router.get("/users")
def list_users(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(User).order_by(User.created_at.desc())
    if search:
        query = query.filter(
            or_(User.email.ilike(f"%{search}%"), User.display_name.ilike(f"%{search}%"))
        )
    users, total = _page(query, page, page_size)
    return {
        "items": [
            {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "preferred_language": user.preferred_language,
                "admin_role": user.admin_role,
                "account_status": user.account_status,
                "last_active_at": user.last_active_at,
                "created_at": user.created_at,
                "saved_stories_count": db.query(SavedStory)
                .filter(SavedStory.user_id == user.id)
                .count(),
                "preferences": (
                    {
                        "topics": prefs.topics,
                        "regions": prefs.regions,
                        "briefing_length": prefs.briefing_length,
                        "explanation_level": prefs.explanation_level,
                    }
                    if (prefs := db.query(UserPreferences)
                        .filter(UserPreferences.user_id == user.id)
                        .first())
                    else None
                ),
            }
            for user in users
        ],
        "total": total,
    }


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    body: AdminUserPatch,
    actor: User = Depends(require_role("super_admin")),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == actor.id and body.account_status == "disabled":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot disable your own account")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    _audit(db, actor, "user.update", "user", user.id, changes)
    db.commit()
    return {
        "id": user.id,
        "email": user.email,
        "admin_role": user.admin_role,
        "account_status": user.account_status,
    }


@router.get("/ai-runs")
def list_ai_runs(
    task_type: str | None = None,
    run_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = db.query(AIRun).order_by(AIRun.created_at.desc())
    if task_type:
        query = query.filter(AIRun.task_type == task_type)
    if run_status:
        query = query.filter(AIRun.status == run_status)
    return [
        {
            "id": run.id,
            "task_type": run.task_type,
            "input_reference_type": run.input_reference_type,
            "input_reference_id": run.input_reference_id,
            "model_name": run.model_name,
            "status": run.status,
            "error_message": run.error_message,
            "created_at": run.created_at,
            "completed_at": run.completed_at,
        }
        for run in query.limit(limit).all()
    ]


@router.get("/audit-logs")
def list_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {
            "id": item.id,
            "actor_email": item.actor_email,
            "actor_role": item.actor_role,
            "action": item.action,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "details": item.details,
            "created_at": item.created_at,
        }
        for item in db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    ]


@router.get("/settings")
def list_settings(
    actor: User = Depends(require_role("super_admin")),
    db: Session = Depends(get_db),
) -> list[dict]:
    del actor
    return [
        {
            "key": item.key,
            "value": item.value,
            "description": item.description,
            "updated_at": item.updated_at,
        }
        for item in db.query(AdminSetting).order_by(AdminSetting.key).all()
    ]


@router.put("/settings/{key}")
def update_setting(
    key: str,
    body: SettingPatch,
    actor: User = Depends(require_role("super_admin")),
    db: Session = Depends(get_db),
) -> dict:
    setting = db.get(AdminSetting, key)
    if setting is None:
        setting = AdminSetting(key=key)
        db.add(setting)
    setting.value = body.value
    setting.description = body.description
    _audit(db, actor, "setting.update", "setting", key)
    db.commit()
    return {"key": setting.key, "value": setting.value, "description": setting.description}
