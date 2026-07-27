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


def briefing_score(
    story: Story,
    prefs: UserPreferences | None,
    *,
    now: datetime | None = None,
) -> float | None:
    """Score an eligible story from 0 to 6 for a user's briefing."""
    if prefs is None:
        return None

    topics = set(prefs.topics or [])
    regions = set(prefs.regions or [])
    matched_topics = int(story.category is not None and story.category in topics)
    matched_regions = int(story.region is not None and story.region in regions)
    if matched_topics + matched_regions == 0:
        return None

    reference_time = now or utcnow()
    age_hours = max(
        0.0,
        (reference_time - story.last_updated_at).total_seconds() / 3600,
    )
    recency = max(0.0, (STORY_LOOKBACK_HOURS - age_hours) / STORY_LOOKBACK_HOURS)
    topic_score = 3 * matched_topics / len(topics) if topics else 0.0
    region_score = 2 * matched_regions / len(regions) if regions else 0.0
    return topic_score + region_score + recency


def select_briefing_stories(
    db: Session,
    prefs: UserPreferences | None,
    count: int,
) -> list[Story]:
    now = utcnow()
    cutoff = now - timedelta(hours=STORY_LOOKBACK_HOURS)
    candidates = (
        db.query(Story)
        .filter(Story.last_updated_at >= cutoff, Story.status == "published")
        .order_by(Story.last_updated_at.desc())
        .limit(300)
        .all()
    )
    scored = [
        (score, story)
        for story in candidates
        if (score := briefing_score(story, prefs, now=now)) is not None
    ]
    scored.sort(
        key=lambda item: (item[0], item[1].last_updated_at),
        reverse=True,
    )
    return [story for _, story in scored[:count]]


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
        story_ids = [link.story_id for link in briefing.stories]
        published_count = (
            db.query(Story)
            .filter(
                Story.id.in_(story_ids),
                Story.status == "published",
            )
            .count()
            if story_ids
            else 0
        )
        if published_count == len(story_ids):
            return briefing
    if briefing is not None:
        # Preferences or publication status changed today: rebuild.
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
