"""Daily briefing generation (PRD 10.1, milestone 7).

Selects a finite, ranked set of recent stories for the user's topics/regions,
sized by their briefing length preference. One briefing per user per day,
regenerated lazily on first request.
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Briefing, BriefingStory, Story, User, UserPreferences, utcnow

STORY_LOOKBACK_HOURS = 36
READ_MINUTES = {"5_minutes": 5, "10_minutes": 10, "20_minutes": 20}


def _preference_boost(story: Story, prefs: UserPreferences | None) -> float:
    if prefs is None:
        return 0.0
    boost = 0.0
    if story.category and story.category in (prefs.topics or []):
        boost += 0.3
    if story.region and story.region in (prefs.regions or []):
        boost += 0.2
    return boost


def select_briefing_stories(db: Session, prefs: UserPreferences | None, count: int) -> list[Story]:
    cutoff = utcnow() - timedelta(hours=STORY_LOOKBACK_HOURS)
    candidates = (
        db.query(Story)
        .filter(Story.last_updated_at >= cutoff)
        .order_by(Story.importance_score.desc())
        .limit(300)
        .all()
    )
    ranked = sorted(
        candidates,
        key=lambda s: s.importance_score + _preference_boost(s, prefs),
        reverse=True,
    )
    # Keep the briefing diverse: cap how many stories one category can take.
    per_category_cap = max(2, count // 3)
    selected: list[Story] = []
    category_counts: dict[str, int] = {}
    for story in ranked:
        key = story.category or "World"
        if category_counts.get(key, 0) >= per_category_cap:
            continue
        selected.append(story)
        category_counts[key] = category_counts.get(key, 0) + 1
        if len(selected) >= count:
            break
    # Backfill if category caps left us short.
    if len(selected) < count:
        for story in ranked:
            if story not in selected:
                selected.append(story)
                if len(selected) >= count:
                    break
    return selected


def get_or_create_today_briefing(db: Session, user: User) -> Briefing:
    settings = get_settings()
    today = date.today().isoformat()
    briefing = (
        db.query(Briefing)
        .filter(Briefing.user_id == user.id, Briefing.briefing_date == today)
        .first()
    )
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
    length = prefs.briefing_length if prefs else "10_minutes"

    if briefing is not None and briefing.briefing_length == length:
        return briefing
    if briefing is not None:
        # Length preference changed today: rebuild.
        db.delete(briefing)
        db.flush()

    count = settings.briefing_story_counts.get(length, 12)
    stories = select_briefing_stories(db, prefs, count)
    briefing = Briefing(user_id=user.id, briefing_date=today, briefing_length=length)
    db.add(briefing)
    db.flush()
    for rank, story in enumerate(stories):
        db.add(BriefingStory(briefing_id=briefing.id, story_id=story.id, rank=rank))
    db.commit()
    db.refresh(briefing)
    return briefing


def greeting_for_now(now: time | None = None) -> str:
    hour = (now or datetime.now().time()).hour
    if 5 <= hour < 12:
        return "Good morning."
    if 12 <= hour < 18:
        return "Good afternoon."
    return "Good evening."
