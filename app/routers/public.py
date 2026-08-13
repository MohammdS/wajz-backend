from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import bearer_scheme, get_current_user
from app.database import get_db
from app.models import Source, Story, User
from app.rate_limit import rate_limit
from app.schemas import (
    CATEGORIES,
    REGIONS,
    OngoingTopicDetail,
    OngoingTopicListResponse,
    SourceOut,
    StoryDetail,
    StoryListResponse,
)
from app.serializers import saved_story_ids, story_to_detail, story_to_list_item
from app.services.ongoing_topics import list_public_topics, public_topic_detail
from app.services.operational_settings import get_runtime_controls, public_runtime_state

router = APIRouter(
    tags=["public"], dependencies=[Depends(rate_limit("public", "rate_limit_public"))]
)


def get_optional_user(
    credentials=Depends(bearer_scheme), db: Session = Depends(get_db)
) -> User | None:
    """Public endpoints personalize the `saved` flag when a token is present."""
    if credentials is None:
        return None
    try:
        return get_current_user(credentials, db)
    except HTTPException:
        return None


@router.get("/categories")
def list_categories() -> dict:
    return {"categories": CATEGORIES, "regions": REGIONS}


@router.get("/runtime")
def runtime_state(db: Session = Depends(get_db)) -> dict:
    return public_runtime_state(db)


@router.get("/sources", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)) -> list[Source]:
    return db.query(Source).filter(Source.active.is_(True)).order_by(Source.name).all()


@router.get("/ongoing-topics", response_model=OngoingTopicListResponse)
def list_ongoing_topics(
    language: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> OngoingTopicListResponse:
    if not get_runtime_controls(db).ongoing_topics_enabled:
        return OngoingTopicListResponse(items=[], total=0, limit=limit, offset=offset)
    requested_language = language or (user.preferred_language if user else None)
    items, total = list_public_topics(
        db,
        language=requested_language,
        saved_ids=saved_story_ids(db, user),
        limit=limit,
        offset=offset,
    )
    return OngoingTopicListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/ongoing-topics/{topic_id}", response_model=OngoingTopicDetail)
def get_ongoing_topic(
    topic_id: str,
    language: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> OngoingTopicDetail:
    if not get_runtime_controls(db).ongoing_topics_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ongoing topic not found")
    detail = public_topic_detail(
        db,
        topic_id,
        language=language or (user.preferred_language if user else None),
        saved_ids=saved_story_ids(db, user),
        limit=limit,
        offset=offset,
    )
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ongoing topic not found")
    return detail


@router.get("/stories", response_model=StoryListResponse)
def list_stories(
    category: str | None = None,
    region: str | None = None,
    language: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> StoryListResponse:
    query = db.query(Story).filter(Story.status == "published")
    if category:
        query = query.filter(Story.category == category)
    if region:
        query = query.filter(Story.region == region)
    total = query.count()
    stories = query.order_by(Story.last_updated_at.desc()).offset(offset).limit(limit).all()
    saved_ids = saved_story_ids(db, user)
    return StoryListResponse(
        items=[
            story_to_list_item(
                db,
                s,
                saved_ids,
                language or (user.preferred_language if user else None),
            )
            for s in stories
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/stories/{story_id}", response_model=StoryDetail)
def get_story(
    story_id: str,
    language: str | None = None,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> StoryDetail:
    story = db.get(Story, story_id)
    if story is None or story.status != "published":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    return story_to_detail(
        db,
        story,
        saved_story_ids(db, user),
        language or (user.preferred_language if user else None),
    )
