from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.admin_schemas_v1 import (
    ArticleAction,
    ArticleBatchIn,
    OngoingTopicAction,
    OngoingTopicIn,
    ManualStoryIn,
    SourceIn,
    SourcePatch,
    StoryAction,
    StoryPatch,
    TopicStoryIn,
    UrlImportIn,
)
from app.auth import require_owner
from app.database import get_db
from app.models import (
    Article,
    OngoingTopic,
    OngoingTopicStory,
    OngoingTopicTranslation,
    Source,
    Story,
    StoryArticle,
    StoryTranslation,
    User,
    utcnow,
)
from app.rate_limit import rate_limit
from app.services.admin_core import (
    audit,
    enqueue_job,
    job_dict,
    require_mutation_idempotency,
)
from app.services.clustering import attach_article_to_story, create_story_from_article
from app.services.safe_urls import validate_public_url

router = APIRouter(
    prefix="/admin/v1",
    tags=["admin content"],
    dependencies=[
        Depends(rate_limit("admin", "rate_limit_admin")),
        Depends(require_mutation_idempotency),
    ],
)


def _page(query, limit: int, offset: int) -> tuple[list, int]:
    total = query.count()
    return query.offset(offset).limit(limit).all(), total


def _story_dict(db: Session, story: Story) -> dict:
    links = db.query(StoryArticle).filter(StoryArticle.story_id == story.id).all()
    articles = [db.get(Article, link.article_id) for link in links]
    articles = [item for item in articles if item is not None]
    source_names = []
    for article in articles:
        source = db.get(Source, article.source_id)
        if source is not None and source.name not in source_names:
            source_names.append(source.name)
    return {
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
        "importance_score": story.importance_score,
        "confidence_label": story.confidence_label,
        "language": story.language,
        "status": story.status,
        "editor_notes": story.editor_notes,
        "published_at": story.published_at,
        "last_updated_at": story.last_updated_at,
        "source_count": len(source_names),
        "sources": source_names,
        "translation_languages": [row.language for row in story.translations],
    }


def _article_dict(db: Session, article: Article) -> dict:
    source = db.get(Source, article.source_id)
    return {
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
        "processing_status": article.processing_status,
        "status": article.status,
        "failure_reason": article.failure_reason,
        "importance_score": article.importance_score,
        "is_opinion": article.is_opinion,
    }


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


@router.get("/stories")
def list_stories(
    search: str | None = None,
    story_status: str | None = Query(default=None, alias="status"),
    category: str | None = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: str = Query(
        default="last_updated_at", pattern="^(headline|status|category|last_updated_at)$"
    ),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    sort_column = {
        "headline": Story.headline,
        "status": Story.status,
        "category": Story.category,
        "last_updated_at": Story.last_updated_at,
    }[sort]
    query = db.query(Story).order_by(
        sort_column.asc() if direction == "asc" else sort_column.desc()
    )
    if search:
        query = query.filter(
            or_(Story.headline.ilike(f"%{search}%"), Story.summary.ilike(f"%{search}%"))
        )
    if story_status:
        query = query.filter(Story.status == story_status)
    if category:
        query = query.filter(Story.category == category)
    items, total = _page(query, limit, offset)
    return {
        "items": [_story_dict(db, item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/stories/{story_id}")
def get_story(
    story_id: str,
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    return _story_dict(db, story)


@router.patch("/stories/{story_id}")
def update_story(
    story_id: str,
    body: StoryPatch,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(story, key, value)
    story.last_updated_at = utcnow()
    audit(db, actor, "story.updated", "story", story.id, {"fields": sorted(changes)})
    db.commit()
    return _story_dict(db, story)


def _validate_publishable(db: Session, story: Story) -> None:
    missing = [
        name
        for name, value in {
            "headline": story.headline,
            "summary": story.summary,
            "what_happened": story.what_happened,
            "why_it_matters": story.why_it_matters,
        }.items()
        if not value or not str(value).strip()
    ]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Missing publishable fields: {', '.join(missing)}",
        )
    if db.query(StoryArticle).filter(StoryArticle.story_id == story.id).count() < 1:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "At least one source is required"
        )
    has_arabic = (
        story.language == "ar"
        or db.query(StoryTranslation.id)
        .filter(
            StoryTranslation.story_id == story.id,
            StoryTranslation.language == "ar",
        )
        .first()
    )
    if not has_arabic:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Arabic content is required")


@router.post("/stories/{story_id}/action")
def act_on_story(
    story_id: str,
    body: StoryAction,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    target_status = {
        "publish": "published",
        "archive": "archived",
        "reject": "rejected",
        "submit_review": "pending_review",
    }[body.action]
    if body.action == "publish":
        _validate_publishable(db, story)
        story.published_at = utcnow()
        story.published_by_id = actor.id
    story.status = target_status
    story.last_updated_at = utcnow()
    audit(db, actor, f"story.{body.action}", "story", story.id)
    db.commit()
    return _story_dict(db, story)


def _topic_dict(topic: OngoingTopic) -> dict:
    return {
        "id": topic.id,
        "category": topic.category,
        "priority": topic.priority,
        "status": topic.status,
        "expires_at": topic.expires_at,
        "published_at": topic.published_at,
        "translations": {
            row.language: {"title": row.title, "description": row.description}
            for row in topic.translations
        },
        "story_ids": [row.story_id for row in topic.stories],
        "updated_at": topic.updated_at,
    }


@router.get("/ongoing-topics")
def list_topics(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(OngoingTopic).order_by(
        OngoingTopic.priority.desc(), OngoingTopic.updated_at.desc()
    )
    items, total = _page(query, limit, offset)
    return {
        "items": [_topic_dict(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _apply_topic_input(topic: OngoingTopic, body: OngoingTopicIn) -> None:
    topic.category = body.category
    topic.priority = body.priority
    topic.expires_at = body.expires_at.replace(tzinfo=None) if body.expires_at else None
    by_language = {row.language: row for row in topic.translations}
    for language, translation in body.translations.items():
        row = by_language.get(language)
        if row is None:
            row = OngoingTopicTranslation(topic=topic, language=language, title="", description="")
            topic.translations.append(row)
        row.title = translation.title
        row.description = translation.description


@router.post("/ongoing-topics", status_code=status.HTTP_201_CREATED)
def create_topic(
    body: OngoingTopicIn,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    topic = OngoingTopic()
    _apply_topic_input(topic, body)
    db.add(topic)
    db.flush()
    audit(db, actor, "ongoing_topic.created", "ongoing_topic", topic.id)
    db.commit()
    return _topic_dict(topic)


@router.put("/ongoing-topics/{topic_id}")
def update_topic(
    topic_id: str,
    body: OngoingTopicIn,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    topic = db.get(OngoingTopic, topic_id)
    if topic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ongoing topic not found")
    _apply_topic_input(topic, body)
    audit(db, actor, "ongoing_topic.updated", "ongoing_topic", topic.id)
    db.commit()
    return _topic_dict(topic)


@router.post("/ongoing-topics/{topic_id}/action")
def act_on_topic(
    topic_id: str,
    body: OngoingTopicAction,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    topic = db.get(OngoingTopic, topic_id)
    if topic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ongoing topic not found")
    if body.action == "publish":
        languages = {row.language for row in topic.translations if row.title and row.description}
        published_stories = (
            db.query(Story.id)
            .join(OngoingTopicStory, OngoingTopicStory.story_id == Story.id)
            .filter(OngoingTopicStory.topic_id == topic.id, Story.status == "published")
            .count()
        )
        if languages != {"ar", "en"} or published_stories < 1:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Arabic and English content plus a published story are required",
            )
        topic.status = "published"
        topic.published_at = utcnow()
        topic.published_by_id = actor.id
    else:
        topic.status = body.action
    audit(db, actor, f"ongoing_topic.{body.action}", "ongoing_topic", topic.id)
    db.commit()
    return _topic_dict(topic)


@router.post("/ongoing-topics/{topic_id}/stories", status_code=status.HTTP_201_CREATED)
def attach_topic_story(
    topic_id: str,
    body: TopicStoryIn,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    topic = db.get(OngoingTopic, topic_id)
    story = db.get(Story, body.story_id)
    if topic is None or story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic or story not found")
    if db.get(OngoingTopicStory, (topic_id, body.story_id)) is None:
        db.add(OngoingTopicStory(topic_id=topic_id, story_id=body.story_id))
    audit(
        db,
        actor,
        "ongoing_topic.story_attached",
        "ongoing_topic",
        topic_id,
        {"story_id": body.story_id},
    )
    db.commit()
    db.refresh(topic)
    return _topic_dict(topic)


@router.delete("/ongoing-topics/{topic_id}/stories/{story_id}")
def detach_topic_story(
    topic_id: str,
    story_id: str,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    link = db.get(OngoingTopicStory, (topic_id, story_id))
    if link is not None:
        db.delete(link)
    audit(
        db, actor, "ongoing_topic.story_detached", "ongoing_topic", topic_id, {"story_id": story_id}
    )
    db.commit()
    return {"detached": True}


@router.get("/articles")
def list_articles(
    search: str | None = None,
    processing_status: str | None = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(Article).order_by(Article.fetched_at.desc())
    if search:
        query = query.filter(Article.title.ilike(f"%{search}%"))
    if processing_status:
        query = query.filter(Article.processing_status == processing_status)
    items, total = _page(query, limit, offset)
    return {
        "items": [_article_dict(db, item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/articles/{article_id}/action")
def act_on_article(
    article_id: str,
    body: ArticleAction,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_owner),
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
        job, _ = enqueue_job(
            db, actor, "process_articles", {"article_ids": [article.id]}, idempotency_key
        )
        return job_dict(job)
    if body.action == "ignore":
        article.status = "ignored"
    elif body.action == "create_story":
        story = create_story_from_article(db, article)
        audit(db, actor, "article.story_created", "article", article.id, {"story_id": story.id})
        db.commit()
        return {"story_id": story.id}
    elif body.action == "attach":
        story = db.get(Story, body.story_id or "")
        if story is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "A valid story_id is required"
            )
        attach_article_to_story(db, article, story)
    audit(db, actor, f"article.{body.action}", "article", article.id)
    db.commit()
    return _article_dict(db, article)


@router.post("/articles/reprocess-selected", status_code=status.HTTP_202_ACCEPTED)
def reprocess_selected(
    body: ArticleBatchIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    found = {row.id for row in db.query(Article.id).filter(Article.id.in_(body.article_ids)).all()}
    if found != set(body.article_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "One or more articles were not found")
    db.query(Article).filter(Article.id.in_(body.article_ids)).update(
        {
            Article.processing_status: "pending",
            Article.status: "collected",
            Article.failure_reason: None,
        },
        synchronize_session=False,
    )
    db.commit()
    job, _ = enqueue_job(
        db, actor, "process_articles", {"article_ids": body.article_ids}, idempotency_key
    )
    return job_dict(job)


@router.get("/sources")
def list_sources(
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    items = db.query(Source).order_by(Source.name).all()
    return {
        "items": [_source_dict(item) for item in items],
        "total": len(items),
        "limit": len(items),
        "offset": 0,
    }


@router.post("/sources", status_code=status.HTTP_201_CREATED)
def create_source(
    body: SourceIn,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    if db.query(Source.id).filter(Source.name == body.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Source name already exists")
    try:
        rss_url = validate_public_url(str(body.rss_url))
        website_url = validate_public_url(str(body.website_url)) if body.website_url else None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    source = Source(
        **body.model_dump(exclude={"rss_url", "website_url"}),
        rss_url=rss_url,
        website_url=website_url,
    )
    db.add(source)
    db.flush()
    audit(db, actor, "source.created", "source", source.id, {"name": source.name})
    db.commit()
    return _source_dict(source)


@router.patch("/sources/{source_id}")
def update_source(
    source_id: str,
    body: SourcePatch,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    changes = body.model_dump(exclude_unset=True)
    for field in ("rss_url", "website_url"):
        if field in changes and changes[field] is not None:
            try:
                changes[field] = validate_public_url(str(changes[field]))
            except ValueError as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    for key, value in changes.items():
        setattr(source, key, value)
    audit(db, actor, "source.updated", "source", source.id, {"fields": sorted(changes)})
    db.commit()
    return _source_dict(source)


@router.post("/sources/{source_id}/test", status_code=status.HTTP_202_ACCEPTED)
def test_source(
    source_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    if db.get(Source, source_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    job, _ = enqueue_job(db, actor, "test_source", {"source_id": source_id}, idempotency_key)
    return job_dict(job)


@router.post("/studio/manual", status_code=status.HTTP_201_CREATED)
def create_manual_story(
    body: ManualStoryIn,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    story = Story(
        headline=body.headline,
        summary=body.summary or None,
        what_happened=body.what_happened or None,
        why_it_matters=body.why_it_matters or None,
        key_facts=body.key_facts,
        category=body.category,
        region=body.region,
        language=body.language,
        editor_notes=body.editor_notes,
        status="draft",
    )
    db.add(story)
    db.flush()
    audit(db, actor, "studio.manual_story_created", "story", story.id)
    db.commit()
    return _story_dict(db, story)


@router.post("/studio/import-urls", status_code=status.HTTP_202_ACCEPTED)
def import_urls(
    body: UrlImportIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    urls = []
    for item in body.urls:
        try:
            urls.append(validate_public_url(str(item)))
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    job, _ = enqueue_job(db, actor, "import_urls", {"urls": urls}, idempotency_key)
    return job_dict(job)
