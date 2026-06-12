from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import SavedStory, Story, User, UserPreferences
from app.rate_limit import rate_limit
from app.schemas import (
    BRIEFING_LENGTHS,
    CATEGORIES,
    EXPLANATION_LEVELS,
    LANGUAGES,
    NOTIFICATION_PREFERENCES,
    REGIONS,
    BriefingResponse,
    PreferencesIn,
    PreferencesOut,
    SavedStoryOut,
    UserOut,
)
from app.serializers import saved_story_ids, story_to_list_item
from app.services.briefing import (
    READ_MINUTES,
    get_or_create_today_briefing,
    greeting_for_now,
)

router = APIRouter(
    prefix="/me",
    tags=["me"],
    dependencies=[Depends(rate_limit("public", "rate_limit_public"))],
)


def _get_prefs(db: Session, user: User) -> UserPreferences:
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
    if prefs is None:
        prefs = UserPreferences(user_id=user.id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


@router.get("", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/preferences", response_model=PreferencesOut)
def get_preferences(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PreferencesOut:
    prefs = _get_prefs(db, user)
    return PreferencesOut(
        preferred_language=user.preferred_language,
        topics=prefs.topics or [],
        regions=prefs.regions or [],
        briefing_length=prefs.briefing_length,
        explanation_level=prefs.explanation_level,
        notification_preference=prefs.notification_preference,
    )


@router.put("/preferences", response_model=PreferencesOut)
def update_preferences(
    body: PreferencesIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PreferencesOut:
    if body.preferred_language not in LANGUAGES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unsupported language")
    if body.briefing_length not in BRIEFING_LENGTHS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid briefing length")
    if body.explanation_level not in EXPLANATION_LEVELS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid explanation level")
    if body.notification_preference not in NOTIFICATION_PREFERENCES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid notification preference")
    invalid_topics = [t for t in body.topics if t not in CATEGORIES]
    if invalid_topics:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid topics: {invalid_topics}")
    invalid_regions = [r for r in body.regions if r not in REGIONS]
    if invalid_regions:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid regions: {invalid_regions}")

    prefs = _get_prefs(db, user)
    user.preferred_language = body.preferred_language
    prefs.topics = body.topics
    prefs.regions = body.regions
    prefs.briefing_length = body.briefing_length
    prefs.explanation_level = body.explanation_level
    prefs.notification_preference = body.notification_preference
    db.commit()
    return get_preferences(user, db)


@router.get("/briefing/today", response_model=BriefingResponse)
def today_briefing(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> BriefingResponse:
    briefing = get_or_create_today_briefing(db, user)
    saved_ids = saved_story_ids(db, user)
    items = []
    for link in briefing.stories:
        story = db.get(Story, link.story_id)
        if story is not None:
            items.append(story_to_list_item(db, story, saved_ids))
    return BriefingResponse(
        date=briefing.briefing_date,
        briefing_length=briefing.briefing_length,
        estimated_read_time_minutes=READ_MINUTES.get(briefing.briefing_length, 10),
        greeting=greeting_for_now(),
        stories=items,
    )


@router.get("/saved-stories", response_model=list[SavedStoryOut])
def list_saved(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[SavedStoryOut]:
    rows = (
        db.query(SavedStory)
        .filter(SavedStory.user_id == user.id)
        .order_by(SavedStory.saved_at.desc())
        .all()
    )
    saved_ids = {row.story_id for row in rows}
    result = []
    for row in rows:
        story = db.get(Story, row.story_id)
        if story is not None:
            result.append(
                SavedStoryOut(saved_at=row.saved_at, story=story_to_list_item(db, story, saved_ids))
            )
    return result


@router.post("/saved-stories/{story_id}", status_code=status.HTTP_201_CREATED)
def save_story(
    story_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if db.get(Story, story_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found")
    existing = (
        db.query(SavedStory)
        .filter(SavedStory.user_id == user.id, SavedStory.story_id == story_id)
        .first()
    )
    if existing is None:
        db.add(SavedStory(user_id=user.id, story_id=story_id))
        db.commit()
    return {"saved": True, "story_id": story_id}


@router.delete("/saved-stories/{story_id}")
def unsave_story(
    story_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    row = (
        db.query(SavedStory)
        .filter(SavedStory.user_id == user.id, SavedStory.story_id == story_id)
        .first()
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return {"saved": False, "story_id": story_id}
