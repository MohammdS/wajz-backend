from datetime import timedelta

import pytest

from app.models import Story, UserPreferences, utcnow
from app.services.briefing import briefing_score, select_briefing_stories


def _story(
    headline: str,
    *,
    category: str,
    region: str,
    age_hours: float,
) -> Story:
    return Story(
        headline=headline,
        category=category,
        region=region,
        status="published",
        last_updated_at=utcnow() - timedelta(hours=age_hours),
    )


def test_briefing_score_uses_normalized_matches_and_recency():
    now = utcnow()
    prefs = UserPreferences(
        topics=["Technology", "Economy", "Science"],
        regions=["Europe", "Middle East"],
    )
    story = Story(
        headline="Matched story",
        category="Technology",
        region="Europe",
        last_updated_at=now - timedelta(hours=18),
    )

    assert briefing_score(story, prefs, now=now) == pytest.approx(2.5)


def test_briefing_score_maximum_is_six():
    now = utcnow()
    prefs = UserPreferences(topics=["Technology"], regions=["Europe"])
    story = Story(
        headline="Fresh full match",
        category="Technology",
        region="Europe",
        last_updated_at=now,
    )

    assert briefing_score(story, prefs, now=now) == pytest.approx(6.0)


def test_select_briefing_requires_a_match_and_respects_36_hour_cutoff(db):
    prefs = UserPreferences(
        topics=["Technology", "Economy"],
        regions=["Europe"],
    )
    fresh_topic_and_region = _story(
        "Fresh full match",
        category="Technology",
        region="Europe",
        age_hours=1,
    )
    older_topic_and_region = _story(
        "Older full match",
        category="Technology",
        region="Europe",
        age_hours=20,
    )
    region_only = _story(
        "Region only",
        category="Sports",
        region="Europe",
        age_hours=1,
    )
    unmatched = _story(
        "Unmatched",
        category="Sports",
        region="World",
        age_hours=1,
    )
    expired = _story(
        "Expired",
        category="Technology",
        region="Europe",
        age_hours=37,
    )
    db.add_all(
        [
            fresh_topic_and_region,
            older_topic_and_region,
            region_only,
            unmatched,
            expired,
        ]
    )
    db.commit()

    selected = select_briefing_stories(db, prefs, count=10)

    assert [story.headline for story in selected] == [
        "Fresh full match",
        "Older full match",
        "Region only",
    ]


def test_select_briefing_is_empty_without_preferences(db):
    story = _story(
        "No preference match possible",
        category="Technology",
        region="Europe",
        age_hours=1,
    )
    db.add(story)
    db.commit()

    assert select_briefing_stories(db, None, count=10) == []
    assert (
        select_briefing_stories(
            db,
            UserPreferences(topics=[], regions=[]),
            count=10,
        )
        == []
    )
